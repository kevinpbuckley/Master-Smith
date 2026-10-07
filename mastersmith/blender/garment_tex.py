"""Clean a garment seed's base-colour atlas before it is baked onto the garment's own UVs (venv python: scipy, PIL):
    .venv/Scripts/python.exe garment_tex.py <in.png> <out.png> [--mode dark|light] [--knee 0.18] [--gain 0.42]
Why (2026-10-06, PilotGrinder's review): the old tame_highlights scaled each texel's RGB by its own factor; the seed's
chroma noise came through as a pink/green speckle that read as camouflage at portrait distance, and pale flecks of the
seed's lighting stayed on the sleeve and the trouser backs. Here the atlas is split into luma and chroma (BT.601):
the chroma is smoothed (the speckle is chroma noise round the leather's own colour), the luma alone is compressed above
a knee (dark outfits: the studio highlights painted into the leather), and small pale flecks (luma well above the
local median, a few mm across) are put back to the local median. A light outfit (white lab coat, yellow collar) uses
--mode light: chroma smoothing and fleck removal only, no compression."""
import argparse
import json
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--mode", default="dark", choices=["dark", "light"])
ap.add_argument("--knee", type=float, default=0.18)
ap.add_argument("--gain", type=float, default=0.42)
ap.add_argument("--chroma_sigma", type=float, default=5.0, help="px at 4K")
ap.add_argument("--fleck", type=float, default=0.07, help="luma above the local median that marks a fleck")
# 2026-10-06 (MissionCommander's uniform): the broad chroma pull and the fleck removal turned small saturated trim -
# crimson collar tabs, gold stars, brass buttons, gold shoulder boards - into the cloth's olive. Opt-in, defaults unchanged:
ap.add_argument("--broad_share", type=float, default=0.7, help="how far the chroma is pulled to its broad average")
ap.add_argument("--accent_keep", type=float, default=0.0,
                help="chroma deviation from the broad average (BT.601 units) above which the fine chroma is kept and no "
                     "fleck is removed (0 = off; ~0.06 keeps trim)")
ap.add_argument("--accent_mask", default="", help="write a metal-trim mask PNG here (white = gold/brass by hue)")
ap.add_argument("--accent_hue", type=float, nargs=2, default=[28.0, 62.0], help="sRGB hue window of the metal trim (deg)")
ap.add_argument("--accent_min_sat", type=float, default=0.42)
ap.add_argument("--accent_min_val", type=float, default=0.33)
a = ap.parse_args()

im = np.asarray(Image.open(a.src).convert("RGB"), np.float32) / 255.0
h, w, _ = im.shape
s = w / 4096.0
R, G, B = im[..., 0], im[..., 1], im[..., 2]
Y = 0.299 * R + 0.587 * G + 0.114 * B
Cb, Cr = B - Y, R - Y
rep = {"size": [w, h], "mode": a.mode}
# chroma: Gaussian round each texel (the speckle is ~5-10 px at 4K); the shirt/leather border blurs by ~2 mm only
sig = a.chroma_sigma * s
Cb2, Cr2 = ndimage.gaussian_filter(Cb, sig), ndimage.gaussian_filter(Cr, sig)
# the pink/green blotches are 50-100 px across at 4K: the chroma is also pulled 70% toward a broad (40 px) average, so
# the leather keeps one hue while the luma keeps every crease (v6's first texture still read mottled in the portrait)
broad = 40 * s
Cb_f, Cr_f = Cb2, Cr2
Cb_b, Cr_b = ndimage.gaussian_filter(Cb, broad), ndimage.gaussian_filter(Cr, broad)
bs = float(a.broad_share)
Cb2 = (1 - bs) * Cb2 + bs * Cb_b
Cr2 = (1 - bs) * Cr2 + bs * Cr_b
acc = np.zeros_like(Y)
if a.accent_keep > 0:
    # trim keeps its own (fine) chroma: where the fine chroma stands far from the broad average
    dev = np.sqrt((Cb_f - Cb_b) ** 2 + (Cr_f - Cr_b) ** 2)
    t_ = np.clip((dev - 0.5 * a.accent_keep) / (0.5 * a.accent_keep), 0, 1)
    acc = ndimage.gaussian_filter(t_ * t_ * (3 - 2 * t_), max(1.0, 1.5 * s))
    Cb2 = acc * Cb_f + (1 - acc) * Cb2
    Cr2 = acc * Cr_f + (1 - acc) * Cr2
    rep["accent_share"] = round(float((acc > 0.5).mean()), 4)
rep["chroma_std_before"] = [round(float(Cb.std()), 4), round(float(Cr.std()), 4)]
# pale flecks: luma well above its local median, in areas no larger than a few mm (an opening by a 9 px disc keeps
# broad highlights, removes the flecks)
small = max(3, int(round(9 * s)))
Ymed = ndimage.median_filter(Y[::4, ::4], size=max(3, int(round(15 * s))))
Ymed = np.kron(Ymed, np.ones((4, 4), np.float32))[:h, :w]
opened = ndimage.grey_opening(Y, size=(small, small))
fleck = ((Y - Ymed) > a.fleck) & ((Y - opened) > a.fleck * 0.6)
fleck = ndimage.binary_dilation(fleck, iterations=max(1, int(round(2 * s))))
if a.accent_keep > 0:
    fleck &= acc < 0.3                      # a brass button or a gold star is not a pale fleck
Y2 = np.where(fleck, np.minimum(Y, Ymed + 0.01), Y)
rep["fleck_px"] = int(fleck.sum())
if a.mode == "dark":
    k = a.knee
    Y2 = np.where(Y2 > k, k + (Y2 - k) * a.gain, Y2)
    # chroma in proportion: a compressed highlight keeps the leather's saturation instead of turning grey
    ratio = np.where(Y > 1e-4, np.clip(Y2 / np.maximum(Y, 1e-4), 0.35, 1.0), 1.0)
    ratio = ndimage.gaussian_filter(ratio, sig)
    Cb2, Cr2 = Cb2 * np.sqrt(ratio), Cr2 * np.sqrt(ratio)
R2 = Y2 + Cr2
B2 = Y2 + Cb2
G2 = (Y2 - 0.299 * R2 - 0.114 * B2) / 0.587
out = np.clip(np.stack([R2, G2, B2], -1), 0, 1)
Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(a.dst)
if a.accent_mask:
    # gold / brass trim by hue on the cleaned colours (sRGB): garment_fit's "metal_accents" makes it metallic and glossier
    mx_, mn_ = out.max(-1), out.min(-1)
    d_ = np.maximum(mx_ - mn_, 1e-6)
    r_, g_, b_ = out[..., 0], out[..., 1], out[..., 2]
    hue_ = np.where(mx_ == r_, ((g_ - b_) / d_) % 6, np.where(mx_ == g_, (b_ - r_) / d_ + 2, (r_ - g_) / d_ + 4)) * 60
    sat_ = np.where(mx_ > 1e-4, d_ / np.maximum(mx_, 1e-4), 0)
    m_ = (hue_ > a.accent_hue[0]) & (hue_ < a.accent_hue[1]) & (sat_ > a.accent_min_sat) & (mx_ > a.accent_min_val)
    m_ = ndimage.binary_opening(m_, iterations=1)
    mf = ndimage.gaussian_filter(m_.astype(np.float32), max(0.8, 1.0 * s))
    Image.fromarray((np.clip(mf, 0, 1) * 255 + 0.5).astype(np.uint8)).save(a.accent_mask)
    rep["accent_mask_share"] = round(float(m_.mean()), 4)
rep["luma_mean"] = [round(float(Y.mean()), 4), round(float(Y2.mean()), 4)]
rep["luma_p99"] = [round(float(np.percentile(Y, 99)), 4), round(float(np.percentile(Y2, 99)), 4)]
print(json.dumps(rep))
sys.exit(0)

"""Checks on a freshly drawn part picture that need no vision model (2026-09-29): the picture model drew the M4A1's
grip mirrored and it assembled backwards; comparing the picture with the approved side view catches that. (A
whole-object three-quarter picture could not be told from a part's by comparing pictures: the agent reads them.)"""
import math
import os

import numpy as np
from PIL import Image


def object_box(rgb, tol=0.1):
    """(x0, y0, x1, y1) of whatever differs from the picture's border colour, or None for an empty picture."""
    a = np.asarray(rgb.convert("RGB")).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > tol
    if fg.mean() < 0.002:
        return None
    ys, xs = np.nonzero(fg)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def end_heights(path, frac=0.12, tol=0.1):
    """How tall the silhouette is at its right end against its left end (the outer `frac` of its length each). A gun
    drawn muzzle-right is thin at the right (0.16 the bullpup, 0.17 the M4A1, 0.54 the shotgun); one drawn backwards
    reads 2-6. Pods and launchers with round ends read about 1 and say nothing (2026-10-02, measured on every
    weapon hero in out/). -> ratio, or None for an empty picture"""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > tol
    if fg.mean() < 0.002:
        return None
    xs = np.nonzero(fg.any(axis=0))[0]
    x0, x1 = int(xs.min()), int(xs.max())
    k = max(2, int(frac * (x1 - x0)))

    def height(c0, c1):
        rows = np.nonzero(fg[:, c0:c1].any(axis=1))[0]
        return int(rows.max() - rows.min() + 1) if len(rows) else 0
    return round(height(x1 - k, x1 + 1) / float(max(height(x0, x0 + k), 1)), 2)


REF_CHECKLIST = ("Read every picture: the same object in each; the hero side-on and level (not three-quarter); the muzzle "
                 "or nose to the RIGHT; the back view shows the back (no muzzle or nose: a front drawn again has been "
                 "approved before); a muzzle an open dark bore (no lens, plug, cap or glow); the design matches the brief "
                 "(three tubes are three tubes).")


def contact_sheet(job_dir, category, out, thumb=360):
    """Every picture in ref/ on one labelled sheet the agent can Read in one look, with the warnings the pixels can
    give (2026-10-01: 9 of 38 Proteus pictures were redrawn - heroes three-quarter or facing left, a back view that
    was the front, a closed muzzle). -> (sheet path, [warnings])"""
    from PIL import ImageDraw
    ref = os.path.join(job_dir, "ref")
    pics = sorted(f for f in os.listdir(ref) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and f != os.path.basename(out))
    warnings = []
    if category == "weapon" and "ref_0.png" in pics:
        r = end_heights(os.path.join(ref, "ref_0.png"))
        if r is not None and r > 1.6:
            warnings.append("ref_0.png: the right end is %.1fx taller than the left - is the muzzle on the LEFT? (it must "
                            "point right; --mirror on view/grid, or redraw)" % r)
    if "ref_back.png" in pics and "ref_front.png" in pics:
        warnings.append("ref_back.png: confirm it shows the BACK, not the front drawn again")
    cells = []
    for f in pics:
        im = Image.open(os.path.join(ref, f)).convert("RGB")
        im.thumbnail((thumb, thumb))
        cell = Image.new("RGB", (thumb, thumb + 24), (255, 255, 255))
        cell.paste(im, ((thumb - im.size[0]) // 2, 24 + (thumb - im.size[1]) // 2))
        ImageDraw.Draw(cell).text((6, 6), f, fill=(0, 0, 0))
        cells.append(cell)
    cols = min(4, max(1, len(cells)))
    rows = (len(cells) + cols - 1) // cols
    head = 40 + 16 * len(warnings)
    sheet = Image.new("RGB", (cols * (thumb + 8) + 8, head + rows * (thumb + 32) + 8), (236, 238, 241))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), "%s - %s" % (os.path.basename(job_dir), REF_CHECKLIST[:150]), fill=(0, 0, 0))
    for i, w in enumerate(warnings):
        d.text((8, 26 + 16 * i), "! " + w[:170], fill=(170, 20, 10))
    for i, cell in enumerate(cells):
        sheet.paste(cell, (8 + (i % cols) * (thumb + 8), head + (i // cols) * (thumb + 32)))
    sheet.save(out)
    return out, warnings


def _ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / max(math.sqrt(float((a * a).sum() * (b * b).sum())), 1e-9))


def side_facing(plan_side, side_box, part_side, width=96):
    """Does the part's own side picture face the same way as the part in the approved side view? The approved view is
    cropped to the part's percent box (neighbours and all), the part picture to its object, both greyed to the same
    size; the correlation with the part picture as drawn and mirrored says which way it faces.
    -> {"ncc", "ncc_mirrored", "mirrored"}"""
    ref = Image.open(plan_side).convert("RGB")
    W, H = ref.size
    x0, x1, zt, zb = (float(v) for v in side_box)
    crop = ref.crop((int(x0 / 100 * W), int(zt / 100 * H), max(int(x1 / 100 * W), int(x0 / 100 * W) + 2),
                     max(int(zb / 100 * H), int(zt / 100 * H) + 2)))
    part = Image.open(part_side).convert("RGB")
    box = object_box(part)
    if box is None:
        return {"ncc": 0.0, "ncc_mirrored": 0.0, "mirrored": False}
    part = part.crop(box)
    h = max(8, int(round(width * crop.size[1] / float(crop.size[0]))))
    a = np.asarray(crop.convert("L").resize((width, h), Image.BILINEAR)).astype(np.float32)
    b = np.asarray(part.convert("L").resize((width, h), Image.BILINEAR)).astype(np.float32)
    n, m = _ncc(a, b), _ncc(a, b[:, ::-1])
    # a clear answer only: a part a few pixels wide in the side view (the M4A1's trigger, -0.19 against 0.08) matches
    # its crop either way about as badly
    return {"ncc": round(n, 3), "ncc_mirrored": round(m, 3), "mirrored": bool(m > n + 0.08 and m > 0.35)}

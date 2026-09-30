"""Checks on a freshly drawn part picture that need no vision model (2026-09-29): the picture model drew the M4A1's
grip mirrored and it assembled backwards; comparing the picture with the approved side view catches that. (A
whole-object three-quarter picture could not be told from a part's by comparing pictures: the agent reads them.)"""
import math

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

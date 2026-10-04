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


def sheet_cells(path, count, min_fill=0.002):
    """The `count` panels of a turnaround sheet (2026-10-04, Mixar's detect-views as the
    prompt: one picture call for several views). The picture model lays the panels out as it likes (three views
    came back as two above one wide one, with divider lines, whatever the prompt said), so the panels are FOUND:
    the foreground with thin lines opened away, its connected pieces, the `count` largest kept, read in rows
    from the top and left to right. When the count is not what was asked (a view missing, two panels run
    together) every panel is refused with the count, never matched to the wrong view.
    -> [{"cell": k, "box": (x0, y0, x1, y1) or None, "reason": ...}] for k in reading order"""
    from scipy import ndimage
    im = Image.open(path).convert("RGB")
    W, H = im.size
    a = np.asarray(im).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > 0.1
    k = max(3, int(round(min(W, H) / 200.0)))                       # divider lines are a few pixels wide
    opened = ndimage.binary_opening(fg, structure=np.ones((k, k), bool))
    joined = ndimage.binary_dilation(opened, structure=np.ones((2 * k + 1, 2 * k + 1), bool))   # a sight back onto its gun
    labels, _found = ndimage.label(joined)
    want = int(count)
    boxes = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        if (x1 - x0) * (y1 - y0) / float(W * H) >= min_fill:
            boxes.append((x0, y0, x1, y1))
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    if len(boxes) != want:
        reason = "found %d panel%s, asked for %d%s" % (len(boxes), "" if len(boxes) == 1 else "s", want,
                                                      " (two ran together)" if len(boxes) < want else "")
        return [{"cell": i, "box": None, "reason": reason} for i in range(want)]
    # reading order: rows by vertical overlap from the top, then left to right
    rows_out = []
    for b in sorted(boxes, key=lambda b: b[1]):
        for row in rows_out:
            top, bottom = row[0][1], row[0][3]
            if b[1] < bottom - 0.25 * (bottom - top):
                row.append(b)
                break
        else:
            rows_out.append([b])
    ordered = [b for row in rows_out for b in sorted(row, key=lambda b: b[0])]
    out = []
    for i, (x0, y0, x1, y1) in enumerate(ordered):
        # the box back to the un-dilated object, inside the picture
        sub = fg[max(0, y0 - k):min(H, y1 + k), max(0, x0 - k):min(W, x1 + k)]
        ys, xs = np.nonzero(sub)
        bx = (max(0, x0 - k) + int(xs.min()), max(0, y0 - k) + int(ys.min()),
              max(0, x0 - k) + int(xs.max()) + 1, max(0, y0 - k) + int(ys.max()) + 1)
        out.append({"cell": i, "box": bx, "reason": ""})
    return out


def object_aspect(path):
    """Width over height of the object in a picture (its box, not the picture's), or None for an empty one."""
    box = object_box(Image.open(path).convert("RGB"))
    return (box[2] - box[0]) / float(max(box[3] - box[1], 1)) if box else None


def same_picture(path_a, path_b, size=64):
    """Correlation of two pictures' greyscale silhouettes-and-shading at a thumbnail size, each cropped to its
    object, the second also mirrored: a view that is another drawn again (or mirrored) reads over 0.9; different
    views of one object well under."""
    def thumb(path):
        im = Image.open(path).convert("RGB")
        box = object_box(im)                      # both cropped to their object: a sheet panel is framed tighter than a hero
        im = im.crop(box) if box else im
        return np.asarray(im.convert("L").resize((size, size), Image.BILINEAR)).astype(np.float32)
    a, b = thumb(path_a), thumb(path_b)
    return round(max(_ncc(a, b), _ncc(a, b[:, ::-1])), 3)      # the bullpup's "top" was its hero mirrored (2026-10-04)


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

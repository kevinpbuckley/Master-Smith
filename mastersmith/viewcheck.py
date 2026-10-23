"""Do the reference views agree with each other before anything is seeded (owner, 2026-10-23: "make sure that is true
of our image before moving on to modeling")? The Mk II sheet's hero showed a broad round-bowed saucer and its top view
a pointed arrowhead; three seed models each followed the picture they were given and every build lost its silhouette
score to the panel it had not seen. Pure numpy and PIL, no vision model: each orthographic view gives two of the
object's three extents as a scale-free ratio, and the three ratios must close (side H/L = front H/W x top W/L)."""
import json
import math
import os

import numpy as np
from PIL import Image

from .picturecheck import object_box

# which two extents each standard view shows, as (horizontal, vertical) of the picture
VIEW_AXES = {"side": ("L", "H"), "left": ("L", "H"), "front": ("W", "H"), "back": ("W", "H"), "top": ("L", "W"), "bottom": ("L", "W")}
RATIO_TOL = 0.12          # 12% between two readings of the same proportion (orthographic drawings of one object)
COLOUR_TOL = 0.04         # mean foreground chromaticity (r, g of r+g+b = 1) between any view and the hero: a back view
                          # is darker than the hero (its fans and shadows), a repaint is a different hue


def _foreground(path):
    im = Image.open(path).convert("RGB")
    box = object_box(im)
    if box is None:
        return None, None
    a = np.asarray(im).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > 0.1
    return box, a[fg].mean(axis=0)


def _chroma(rgb):
    c = np.array(rgb, dtype=np.float64)
    return c[:2] / max(float(c.sum()), 1e-6)


def view_extents(path):
    """{"w": px, "h": px, "colour": [r, g, b]} of the object in a view, or None for an empty picture."""
    box, colour = _foreground(path)
    if box is None:
        return None
    return {"w": box[2] - box[0], "h": box[3] - box[1], "colour": [round(float(c), 3) for c in colour]}


def proportions(views):
    """Every reading of the object's L:W:H the views give, as ratios of each view's extents:
    {"H/L": [...], "H/W": [...], "W/L": [...]} with the view that gave each. `views` is {name: extents}."""
    out = {"H/L": [], "H/W": [], "W/L": []}
    for name, e in views.items():
        if not e or name not in VIEW_AXES:
            continue
        hor, ver = VIEW_AXES[name]
        r = e["h"] / float(max(e["w"], 1))
        if (hor, ver) == ("L", "H"):
            out["H/L"].append((name, r))
        elif (hor, ver) == ("W", "H"):
            out["H/W"].append((name, r))
        else:
            out["W/L"].append((name, r))            # a top view's vertical extent is the length, so W/L = w/h
            out["W/L"][-1] = (name, e["w"] / float(max(e["h"], 1)))
    return out


def check(ref_dir, hero="ref_0.png"):
    """The consistency report for a job's ref/: the three proportions read from the views, whether they close, which
    views disagree, and each view's colour against the hero's. -> {"pass", "ratios", "dims", "warnings", "views"}"""
    views, warnings = {}, []
    for name in VIEW_AXES:
        p = os.path.join(ref_dir, "ref_%s.png" % name)
        if os.path.isfile(p):
            e = view_extents(p)
            if e is None:
                warnings.append("ref_%s.png is empty" % name)
            else:
                views[name] = e
    hero_path = os.path.join(ref_dir, hero)
    hero_e = view_extents(hero_path) if os.path.isfile(hero_path) else None
    ratios = proportions(views)
    report = {"views": views, "ratios": {k: {n: round(r, 3) for n, r in v} for k, v in ratios.items()}, "warnings": warnings}
    # two views that show the same two extents must agree (front vs back, side vs left)
    for key, reads in ratios.items():
        for i, (n1, r1) in enumerate(reads):
            for n2, r2 in reads[i + 1:]:
                if abs(math.log(r1 / r2)) > math.log(1 + RATIO_TOL):
                    warnings.append("%s reads %s %.2f but %s reads %.2f: not the same object" % (n1, key, r1, n2, r2))
    # the three proportions must close: H/L = H/W x W/L
    med = {k: float(np.median([r for _, r in v])) for k, v in ratios.items() if v}
    if len(med) == 3:
        predicted = med["H/W"] * med["W/L"]
        err = abs(math.log(med["H/L"] / predicted))
        report["closure"] = {"H/L_side": round(med["H/L"], 3), "H/L_from_front_and_top": round(predicted, 3),
                             "error": round(math.exp(err) - 1, 3)}
        if err > math.log(1 + RATIO_TOL):
            which = "the top view" if abs(math.log(med["W/L"])) > 0 else "a view"
            warnings.append("the views do not describe one object: side says H/L %.2f, front x top say %.2f (%.0f%% apart); "
                            "the width in the top view and the front view, or the height in the side and front views, disagree"
                            % (med["H/L"], predicted, (math.exp(err) - 1) * 100))
        report["dims_ratio"] = {"L": 1.0, "W": round(med["W/L"], 3), "H": round(med["H/L"], 3)}
    elif views:
        missing = [k for k in ("H/L", "H/W", "W/L") if k not in med]
        report["closure"] = None
        warnings.append("cannot close the proportions: no view gives %s (side+front+top needed)" % ", ".join(missing))
    # colour: every view roughly the hero's object colour
    if hero_e:
        report["hero_colour"] = hero_e["colour"]
        for name, e in views.items():
            d = float(np.abs(_chroma(e["colour"]) - _chroma(hero_e["colour"])).max())
            if d > COLOUR_TOL:
                warnings.append("ref_%s.png colour differs from the hero (chromaticity %.3f apart): a repaint or a different object" % (name, d))
    report["warnings"] = warnings
    report["pass"] = bool(views) and not warnings
    return report


def write(ref_dir, hero="ref_0.png"):
    """check() saved as ref/consistency.json; returns the report."""
    rep = check(ref_dir, hero)
    with open(os.path.join(ref_dir, "consistency.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=1)
    return rep


def read(ref_dir):
    p = os.path.join(ref_dir, "consistency.json")
    if not os.path.isfile(p):
        return None
    return json.load(open(p, encoding="utf-8"))

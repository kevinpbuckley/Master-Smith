"""Baked tangent-space normals that point INTO the surface: the bake ray of a thin leaf or fin hit the back face of the
high-poly sheet instead of the one in front of it, and the texel rendered black (the Training Pool's kelp, coral and
bluefish, 2026-10-03). Pure numpy, tested."""
import numpy as np


def flip_inward(px, covered=None):
    """px: (h, w, >=3) floats in 0..1, a tangent-space normal map; covered: (h, w) bool, the texels a surface landed on.
    A texel whose normal has a negative Z faces into the low-poly surface, which no surface in front of it can give: it
    is the back face of a thin sheet, and that face's normal negated is the front face's. Those are turned outward.
    -> share of the covered texels that were flipped"""
    n = px[:, :, :3] * 2.0 - 1.0
    bad = n[:, :, 2] < 0.0
    if covered is not None:
        bad &= covered
    n[bad] = -n[bad]
    px[:, :, :3] = (n + 1.0) * 0.5
    total = int(covered.sum()) if covered is not None else bad.size
    return float(bad.sum()) / max(total, 1)

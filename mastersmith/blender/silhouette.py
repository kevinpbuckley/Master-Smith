"""Silhouette envelopes for registration (pure numpy, tested). A sea fan, a kelp or a branching coral is a lattice: its
side silhouette is mostly holes, and the overlap of two lattices is near noise even when they are the same object
turned the same way (the Training Pool's sea fan registered at IoU 0.20 and was rolled onto its side, 2026-10-03).
Their envelopes - the lattice closed and its holes filled - carry the shape."""
import numpy as np


def _grow(m, r):
    """Each pixel set when any pixel within r (a square window) is set."""
    if r <= 0:
        return m.copy()
    h, w = m.shape
    p = np.pad(m, r)
    rows = np.zeros((h + 2 * r, w), bool)
    for d in range(2 * r + 1):
        rows |= p[:, d:d + w]
    out = np.zeros((h, w), bool)
    for d in range(2 * r + 1):
        out |= rows[d:d + h, :]
    return out


def fill_holes(m):
    """The mask with every background region not reached from the border filled in."""
    outside = np.zeros_like(m)
    outside[0, :], outside[-1, :], outside[:, 0], outside[:, -1] = ~m[0, :], ~m[-1, :], ~m[:, 0], ~m[:, -1]
    while True:
        grown = outside.copy()
        grown[1:, :] |= outside[:-1, :]
        grown[:-1, :] |= outside[1:, :]
        grown[:, 1:] |= outside[:, :-1]
        grown[:, :-1] |= outside[:, 1:]
        grown &= ~m
        if (grown == outside).all():
            return ~outside
        outside = grown


def envelope(m, r=None):
    """The mask closed by r pixels (default 5% of its size) and its holes filled."""
    r = max(2, int(round(0.05 * max(m.shape)))) if r is None else r
    closed = ~_grow(~_grow(m, r), r)
    return fill_holes(closed | m)


def fill_ratio(m):
    """Share of the mask's own bounding box it covers: about 0.7-0.9 for a solid object, under 0.45 for a lattice."""
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return 0.0
    return float(m.sum()) / float((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1))


def iou(a, b):
    return float((a & b).sum()) / float(max((a | b).sum(), 1))

"""Where a weapon's shots leave: its open bores, found end-on from the front. Pure numpy (Blender's Python has no
scipy), so the tests can run it; assemble.py casts the rays. 2026-10-01: every weapon's Muzzle socket sat at the
middle of its box (the box centre, not the bore; the pylon on top put the bore lower), a four-tube launcher needed
Muzzle_0..3 by hand, and a capped or lens-plugged muzzle went out unnoticed ("should just be hollow")."""
from collections import deque

import numpy as np

MELEE = r"\b(sword|longsword|knife|dagger|axe|mace|hammer|spear|halberd|katana|machete|club|shield|bow|crossbow|baton)\b"
RANGED = r"\b(gun|rifle|carbine|pistol|shotgun|launcher|cannon|blaster|thrower|flamethrower|smg|revolver|musket|turret|coil)\b"


def is_melee(description):
    """True for a sword, a knife, an axe: no muzzle to find."""
    import re
    text = (description or "").lower()
    return re.search(MELEE, text) is not None and re.search(RANGED, text) is None


def components(mask):
    """4-connected regions of a boolean grid -> list of (rows, cols) index arrays."""
    seen = np.zeros(mask.shape, bool)
    out = []
    h, w = mask.shape
    for r0, c0 in zip(*np.nonzero(mask)):
        if seen[r0, c0]:
            continue
        seen[r0, c0] = True
        q, rows, cols = deque([(r0, c0)]), [], []
        while q:
            r, c = q.popleft()
            rows.append(r)
            cols.append(c)
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = r + dr, c + dc
                if 0 <= a < h and 0 <= b < w and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    q.append((a, b))
        out.append((np.array(rows), np.array(cols)))
    return out


def _holes(rows, cols):
    """Cells inside a region's bounding box that are not the region and cannot reach the box's edge: an annulus (the
    gap round a barrel inside a handguard) has the barrel as its hole, a bore has none."""
    r0, c0 = rows.min(), cols.min()
    box = np.zeros((rows.max() - r0 + 3, cols.max() - c0 + 3), bool)
    box[rows - r0 + 1, cols - c0 + 1] = True
    outside = np.zeros(box.shape, bool)
    q = deque([(0, 0)])
    outside[0, 0] = True
    h, w = box.shape
    while q:
        r, c = q.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = r + dr, c + dc
            if 0 <= a < h and 0 <= b < w and not box[a, b] and not outside[a, b]:
                outside[a, b] = True
                q.append((a, b))
    return int((~box & ~outside).sum())


def openings(depth, cell, length):
    """Round, enclosed recesses in a depth map seen from the front. `depth` [rows = z up, cols = y]: how far a ray
    from just ahead of the front travels back before it meets the model (np.inf: it never does). `cell`: one grid
    step in metres; `length`: the asset's length. -> [{"row", "col" (centre, fractional), "diameter_m", "rim_depth_m",
    "bore_depth_m" (how far past the rim the rays run; inf through a tube), "open" (deep enough to be a bore)}],
    front-most first."""
    depth = np.asarray(depth, float)
    shallow = max(2.0 * cell, 0.002 * length)              # a recess at all
    deep = max(3.0 * cell, 0.01 * length)                  # a bore: a capped muzzle is a pit a few mm deep
    found = []
    for rows, cols in components(depth > shallow):
        h, w = depth.shape
        if rows.min() == 0 or cols.min() == 0 or rows.max() == h - 1 or cols.max() == w - 1:
            continue                                       # open to the edge: the background or the body behind
        n = len(rows)
        ext = (np.ptp(rows) + 1, np.ptp(cols) + 1)
        if n < 6 or max(ext) / max(min(ext), 1) > 1.6:
            continue                                       # specks, and slots: a muzzle is round, not oval
        if n / (np.pi * (max(ext) / 2.0) ** 2) < 0.5 or _holes(rows, cols) > 0.15 * n:
            continue                                       # not a disc: a ring round a barrel, a crescent
        region = np.zeros((h + 4, w + 4), bool)              # padded, so the ring never wraps round the grid
        region[rows + 2, cols + 2] = True
        ring = np.zeros_like(region)
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            ring |= np.roll(np.roll(region, dr, 0), dc, 1)
        ring = (ring & ~region)[2:-2, 2:-2]
        rim = depth[ring]
        rim = rim[np.isfinite(rim)]
        if not len(rim):
            continue
        rim_d = float(np.median(rim))
        if rim_d > 0.15 * length:
            continue                                       # a recess far back on the body, not at the business end
        inner = depth[rows, cols]
        bore = float(np.median(inner)) - rim_d
        found.append({"row": float(rows.mean()), "col": float(cols.mean()), "cells": int(n),
                      "diameter_m": round(float(2.0 * np.sqrt(n / np.pi) * cell), 5), "rim_depth_m": round(rim_d, 5),
                      "bore_depth_m": float(bore) if np.isfinite(bore) else float("inf"), "open": bool(bore >= deep)})
    found.sort(key=lambda o: o["rim_depth_m"])
    return found


def muzzle_openings(depth, cell, length, front_tol=None):
    """The openings at the weapon's front face: the front-most one and every other within `front_tol` of it (a
    four-tube launcher's tubes, a twin barrel), at least a bore's width across. -> list as `openings` gives"""
    found = [o for o in openings(depth, cell, length) if o["diameter_m"] >= max(2.5 * cell, 0.003 * length)]
    # open bores first: a capped pit is the muzzle only when no bore is open (then it is reported as closed)
    found = [o for o in found if o["open"]] or found[:1]
    if not found:
        return []
    tol = front_tol if front_tol is not None else max(0.03 * length, 3 * cell)
    first = found[0]["rim_depth_m"]
    return [o for o in found if o["rim_depth_m"] <= first + tol]


def cluster_tubes(yz, k, iters=20):
    """k tube centres from the front-most vertices' (y, z), when the tubes are loaded or capped and show no open bore
    (the Volley's four tubes hold torpedo noses, 2026-10-02): k-means seeded round the centroid, top first (Proteus's
    rig script did this for Muzzle_0..3). -> (centres [k x 2], labels)"""
    yz = np.asarray(yz, float)
    c = yz.mean(axis=0)
    spread = max(float(np.ptp(yz[:, 0])), float(np.ptp(yz[:, 1]))) / 3.0
    ang = np.pi / 2 - 2 * np.pi * np.arange(k) / k            # the first at the top, then round
    centres = c + spread * np.stack([np.cos(ang), np.sin(ang)], axis=1)
    lab = np.zeros(len(yz), int)
    for _ in range(iters):
        lab = ((yz[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
        centres = np.array([yz[lab == j].mean(0) if (lab == j).any() else centres[j] for j in range(k)])
    return centres, lab


def order_muzzles(points):
    """Muzzle_0..n in a fixed order: top first, then from the asset's right (-Y) to its left (Proteus's Volley used
    this order for Muzzle_0..3, 2026-10-01). points: [(x, y, z)] -> indices"""
    return sorted(range(len(points)), key=lambda i: (-round(points[i][2], 3), points[i][1]))

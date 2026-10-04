"""Wind masks for a generated plant (pure numpy + heapq, tested): what a SpeedTree mesh carries in its vertex colours,
derived from a fused Tripo surface whose leaves cannot be cut out for Pivot Painter. R = the distance ALONG the
surface from the holdfast (0 at the root, 1 at the farthest tip): the bend, and the phase of a wave running up the
stalk. Height alone moved a swept kelp's level blades as one rigid block (owner, 2026-10-03: "a bit too rigid").
G = flutter: the thin parts (blades, fronds) away from the root. B = a random phase per blade, so blades flap out of
step. Thickness comes from the caller (a ray through the surface inside Blender)."""
import heapq

import numpy as np


def geodesic(verts, edges, seeds):
    """Shortest distance along the mesh edges from any seed vertex (Dijkstra). Unreached vertices are inf."""
    n = len(verts)
    nbr = [[] for _ in range(n)]
    lengths = np.linalg.norm(verts[edges[:, 0]] - verts[edges[:, 1]], axis=1)
    for (a, b), w in zip(edges.tolist(), lengths.tolist()):
        nbr[a].append((b, w))
        nbr[b].append((a, w))
    dist = np.full(n, np.inf)
    heap = []
    for s in seeds:
        dist[s] = 0.0
        heap.append((0.0, int(s)))
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for u, w in nbr[v]:
            nd = d + w
            if nd < dist[u]:
                dist[u] = nd
                heapq.heappush(heap, (nd, u))
    return dist


def components(mask, edges):
    """Connected components of the masked vertices over the edges -> label per vertex (-1 outside the mask)."""
    n = len(mask)
    label = np.where(mask, np.arange(n), -1)
    e = edges[mask[edges[:, 0]] & mask[edges[:, 1]]]
    if len(e) == 0:
        return label
    while True:
        m = np.minimum(label[e[:, 0]], label[e[:, 1]])
        before = label.copy()
        np.minimum.at(label, e[:, 0], m)
        np.minimum.at(label, e[:, 1], m)
        label[mask] = label[label[mask]]                 # pointer jumping: long blades settle in a few passes
        if (label == before).all():
            return label


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def masks(verts, edges, thickness, seed=7):
    """-> (stem, flutter, phase), each per vertex in 0..1. verts: (n, 3) with +Z up; thickness: (n,) distance through
    the surface along -normal (inf where nothing was hit)."""
    z = verts[:, 2]
    height = max(float(z.max() - z.min()), 1e-6)
    root = np.nonzero(z <= z.min() + 0.03 * height)[0]          # the holdfast's underside
    dist = geodesic(verts, edges, root)
    reach = dist[np.isfinite(dist)].max() if np.isfinite(dist).any() else height
    # a loose piece the walk cannot reach falls back to its height share
    stem = np.where(np.isfinite(dist), dist / max(reach, 1e-6), (z - z.min()) / height)
    stem = np.clip(stem, 0.0, 1.0)
    thin = 1.0 - smoothstep(0.004 * height, 0.02 * height, np.where(np.isfinite(thickness), thickness, 1e9))
    flutter = thin * smoothstep(0.08, 0.35, stem)
    labels = components(flutter > 0.4, edges)
    rng = np.random.default_rng(seed)
    table = rng.random(len(verts))
    phase = np.where(labels >= 0, table[np.maximum(labels, 0)], 0.5 * stem)
    return stem.astype(np.float32), flutter.astype(np.float32), phase.astype(np.float32)

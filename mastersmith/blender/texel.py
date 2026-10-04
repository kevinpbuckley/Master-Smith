"""Texel density of the delivery, pure numpy (2026-10-04, from Mixar's bundled texel-density checker): pixels of
the atlas per centimetre of surface, per face and per part. The gate checked the LOD budget, the maps, the size,
the roughness and the hull, never the pixels a part got: a part lost in a small atlas tile passed. A hero prop
at 2048 px on a metre is about 10 px/cm, a vehicle at 2048 px over 14 m about 1 px/cm: the number is reported, and
the gate warns only when one part gets far less than the asset's mean."""
import numpy as np


def _fan(loop_start, loop_total):
    """(polygon of each fan triangle, its first, second and third corner loop) for every polygon fan-triangulated."""
    loop_start = np.asarray(loop_start, np.int64)
    loop_total = np.asarray(loop_total, np.int64)
    tri_counts = np.maximum(loop_total - 2, 0)
    poly = np.repeat(np.arange(len(loop_start)), tri_counts)
    base = np.repeat(np.cumsum(tri_counts) - tri_counts, tri_counts)
    k = np.arange(int(tri_counts.sum())) - base
    a = loop_start[poly]
    return poly, a, a + 1 + k, a + 2 + k


def polygon_areas(co, loop_vertex, loop_start, loop_total):
    """Area of every polygon in the units of `co` (world or object space), fan-triangulated from its first corner."""
    co = np.asarray(co, np.float64).reshape(-1, 3)
    loop_vertex = np.asarray(loop_vertex, np.int64)
    poly, l0, l1, l2 = _fan(loop_start, loop_total)
    v0, v1, v2 = co[loop_vertex[l0]], co[loop_vertex[l1]], co[loop_vertex[l2]]
    cross = np.cross(v1 - v0, v2 - v0)
    tri = 0.5 * np.sqrt((cross * cross).sum(axis=1))
    return np.bincount(poly, weights=tri, minlength=len(loop_start))


def uv_polygon_areas(uv, loop_start, loop_total):
    """Area of every polygon in UV space (0-1 square = 1), unsigned, by the same fan."""
    uv = np.asarray(uv, np.float64).reshape(-1, 2)
    poly, l0, l1, l2 = _fan(loop_start, loop_total)
    a, b, c = uv[l0], uv[l1], uv[l2]
    tri = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    return np.bincount(poly, weights=tri, minlength=len(loop_start))


def uv_centroids(uv, loop_start, loop_total):
    uv = np.asarray(uv, np.float64).reshape(-1, 2)
    poly = np.repeat(np.arange(len(loop_start)), np.asarray(loop_total, np.int64))
    n = np.maximum(np.asarray(loop_total, np.float64), 1.0)
    return np.stack([np.bincount(poly, weights=uv[:, 0], minlength=len(loop_start)) / n,
                     np.bincount(poly, weights=uv[:, 1], minlength=len(loop_start)) / n], axis=1)


def px_per_cm(area_m2, uv_area, atlas_px):
    """Texel density of each polygon: the atlas pixels across its UV footprint over its centimetres across."""
    area_m2 = np.asarray(area_m2, np.float64)
    uv_area = np.asarray(uv_area, np.float64)
    out = np.full(len(area_m2), np.nan)
    ok = (area_m2 > 1e-12) & (uv_area > 0)
    out[ok] = float(atlas_px) * np.sqrt(uv_area[ok] / (area_m2[ok] * 1e4))
    return out


def summarize(area_m2, uv_area, atlas_px, tiles=None, centroids=None, low=0.4):
    """-> {"px_per_cm" (area-weighted mean), "p10_px_per_cm", "atlas_used" (share of the square covered),
    "parts": [{"name", "px_per_cm", "area_share"}] by atlas tile, "warnings": [...]}. `tiles`: [(name, u0, v0,
    side)] and `centroids` (n, 2) assign faces to parts; a part under `low` of the mean is warned about."""
    area_m2 = np.asarray(area_m2, np.float64)
    uv_area = np.asarray(uv_area, np.float64)
    d = px_per_cm(area_m2, uv_area, atlas_px)
    ok = np.isfinite(d)
    out = {"atlas_px": int(atlas_px), "px_per_cm": None, "p10_px_per_cm": None, "atlas_used": round(float(uv_area.sum()), 4),
           "parts": [], "warnings": []}
    if not ok.any():
        out["warnings"].append("no face has a UV footprint: the atlas is empty")
        return out
    w = area_m2[ok]
    mean = float((d[ok] * w).sum() / max(w.sum(), 1e-12))
    order = np.argsort(d[ok])
    cum = np.cumsum(w[order]) / max(w.sum(), 1e-12)
    out["px_per_cm"] = round(mean, 2)
    out["p10_px_per_cm"] = round(float(d[ok][order][int(np.searchsorted(cum, 0.10))]), 2)
    if tiles and centroids is not None:
        c = np.asarray(centroids, np.float64).reshape(-1, 2)
        total = max(float(w.sum()), 1e-12)
        for name, u0, v0, side in tiles:
            sel = ok & (c[:, 0] >= u0) & (c[:, 0] <= u0 + side) & (c[:, 1] >= v0) & (c[:, 1] <= v0 + side)
            if not sel.any():
                continue
            pw = area_m2[sel]
            pd = float((d[sel] * pw).sum() / max(pw.sum(), 1e-12))
            out["parts"].append({"name": name, "px_per_cm": round(pd, 2), "area_share": round(float(pw.sum()) / total, 4)})
            if pd < low * mean and pw.sum() / total > 0.002:
                out["warnings"].append("%s gets %.1f px/cm, under %.0f%% of the asset's %.1f (lost in a small atlas tile)"
                                       % (name, pd, low * 100, mean))
    if out["atlas_used"] < 0.2:
        out["warnings"].append("only %.0f%% of the atlas is used (small tiles, big gaps)" % (out["atlas_used"] * 100))
    return out

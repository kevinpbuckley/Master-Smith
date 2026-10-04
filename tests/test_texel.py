"""Texel density (2026-10-04): pixels per centimetre from a mesh's world areas and its UV footprints, per part by
atlas tile, and the warning for a part lost in a small tile."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mastersmith", "blender"))
import texel  # noqa: E402


def quad(x0, y0, side_m, u0, v0, side_uv):
    """A square of `side_m` metres on the ground mapped to a `side_uv` square of the atlas: (co, uv) for one polygon."""
    co = [(x0, y0, 0), (x0 + side_m, y0, 0), (x0 + side_m, y0 + side_m, 0), (x0, y0 + side_m, 0)]
    uv = [(u0, v0), (u0 + side_uv, v0), (u0 + side_uv, v0 + side_uv), (u0, v0 + side_uv)]
    return co, uv


def mesh(quads):
    co, uv, loop_vertex, loop_start, loop_total = [], [], [], [], []
    for c, u in quads:
        loop_start.append(len(loop_vertex))
        loop_total.append(4)
        loop_vertex += list(range(len(co), len(co) + 4))
        co += c
        uv += u
    return np.array(co, float), np.array(uv, float), np.array(loop_vertex), np.array(loop_start), np.array(loop_total)


def test_a_metre_square_over_the_whole_atlas_is_the_textbook_density():
    co, uv, lv, ls, lt = mesh([quad(0, 0, 1.0, 0, 0, 1.0)])
    area, uva = texel.polygon_areas(co, lv, ls, lt), texel.uv_polygon_areas(uv, ls, lt)
    assert np.allclose(area, [1.0]) and np.allclose(uva, [1.0])
    assert np.allclose(texel.px_per_cm(area, uva, 2048), [20.48])       # 2048 px over 100 cm
    s = texel.summarize(area, uva, 2048)
    assert s["px_per_cm"] == 20.48 and s["atlas_used"] == 1.0 and not s["warnings"]


def test_a_part_in_a_small_tile_is_warned_about_by_name():
    # two metre squares: the body in a 0.9 tile, the magazine squeezed into a 0.05 tile of the same 2048 atlas
    co, uv, lv, ls, lt = mesh([quad(0, 0, 1.0, 0, 0, 0.9), quad(2, 0, 1.0, 0.92, 0, 0.05)])
    area, uva = texel.polygon_areas(co, lv, ls, lt), texel.uv_polygon_areas(uv, ls, lt)
    tiles = [("Body", 0, 0, 0.9), ("Magazine", 0.92, 0, 0.05)]
    s = texel.summarize(area, uva, 2048, tiles, texel.uv_centroids(uv, ls, lt))
    by = {p["name"]: p["px_per_cm"] for p in s["parts"]}
    assert abs(by["Body"] - 18.43) < 0.01 and abs(by["Magazine"] - 1.02) < 0.01
    assert any(w.startswith("Magazine gets 1.0 px/cm") for w in s["warnings"]), s["warnings"]
    assert s["p10_px_per_cm"] < s["px_per_cm"]


def test_degenerate_faces_and_an_empty_atlas_do_not_break_it():
    co, uv, lv, ls, lt = mesh([quad(0, 0, 0.0, 0, 0, 0.0)])
    s = texel.summarize(texel.polygon_areas(co, lv, ls, lt), texel.uv_polygon_areas(uv, ls, lt), 1024)
    assert s["px_per_cm"] is None and "empty" in s["warnings"][0]

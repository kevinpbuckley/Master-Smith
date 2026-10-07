"""garment_refit_core (blender/garment_refit_core.py) on synthetic data: the shrink gap mapping keeps layer order, the
collar/band hold is 1 at the feature and 0 beyond the band, a mixed label band is told from a clean one, and an old
mesh's vertices are matched to a rebuilt one with an extra vertex by UV."""
import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "garment_refit_core", Path(__file__).resolve().parents[1] / "mastersmith/blender/garment_refit_core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


# --------------------------------------------------------------------------------------------------------- shrink_pull

def test_gaps_under_the_floor_are_untouched():
    gap = np.array([0.0, 0.005, 0.009, 0.010])
    out = core.gap_after_pull(gap, k=0.7, floor=0.010)
    assert np.allclose(out, gap)


def test_shrink_keeps_monotonic_layer_order_above_the_floor():
    # a belt (12 mm gap) stays proud of the shirt (4 mm gap) after the pull, whatever k and floor in range
    for k in (0.0, 0.3, 0.7, 0.99):
        for floor in (0.0, 0.006, 0.010, 0.02):
            gaps = np.linspace(0.0, 0.05, 40)
            after = core.gap_after_pull(gaps, k=k, floor=floor)
            assert np.all(np.diff(after) >= -1e-12), (k, floor)


def test_shrink_pulls_by_the_kept_share_above_the_floor():
    out = core.gap_after_pull(np.array([0.040]), k=0.7, floor=0.010)
    # 10 mm floor + 70% of the remaining 30 mm = 10 + 21 = 31 mm
    assert abs(out[0] - 0.031) < 1e-9


# ------------------------------------------------------------------------------------------------------ smoothstep_hold

def test_hold_is_one_at_the_feature_and_zero_beyond_the_band():
    d = np.array([0.0, 0.06 * 0.06, 0.03, 0.06, 0.10])
    out = core.smoothstep_hold(d, band=0.06)
    assert out[0] == 1.0
    assert out[3] == 0.0 and out[4] == 0.0
    assert 0.0 < out[2] < 1.0


def test_hold_is_monotonically_decreasing_with_distance():
    d = np.linspace(0, 0.06, 50)
    out = core.smoothstep_hold(d, band=0.06)
    assert np.all(np.diff(out) <= 1e-12)


# --------------------------------------------------------------------------------------------------- bone families

def test_bone_family_sides_and_groups():
    assert core.bone_family("upperarm_l") == "arm_l"
    assert core.bone_family("thigh_r") == "leg_r"
    assert core.bone_family("spine_03") == "torso"
    assert core.bone_family("neck_01") == "torso"


# ------------------------------------------------------------------------------------------------------- mixed band

def test_a_clean_vertex_is_not_a_mixed_band():
    # almost all torso, a sliver of arm: below the default 0.12 share
    assert not core.is_mixed_band({"spine_05": 0.95, "upperarm_l": 0.05})


def test_a_blended_seam_vertex_is_a_mixed_band():
    # the fit smoothed an armpit seam across torso and arm in real proportion
    assert core.is_mixed_band({"spine_05": 0.7, "upperarm_l": 0.3})


def test_mixed_band_share_threshold_is_configurable():
    w = {"spine_05": 0.85, "upperarm_l": 0.15}
    assert not core.is_mixed_band(w, share=0.2)
    assert core.is_mixed_band(w, share=0.1)


# ------------------------------------------------------------------------------------------------------- UV matching

def test_uv_matching_skips_one_extra_new_vertex():
    rng = np.random.default_rng(0)
    n = 30
    old_uv = rng.random((n, 2))
    old_pos = rng.random((n, 3))
    # the new mesh is the old one, same order, plus one extra vertex at a UV far from every old one
    extra_uv = np.array([[5.0, 5.0]])
    extra_pos = np.array([[50.0, 50.0, 50.0]])
    new_uv = np.vstack([old_uv, extra_uv])
    new_pos = np.vstack([old_pos, extra_pos])
    idx, worst = core.match_by_uv(old_uv, new_uv, old_pos, new_pos)
    assert worst < 1e-9
    assert list(idx) == list(range(n))          # every old vertex found its own new one, not the extra
    assert n not in idx


def test_uv_matching_breaks_a_tie_by_position():
    # two new vertices share the OLD vertex's UV exactly (a seam the mesher split): the nearer in space wins
    old_uv = np.array([[0.5, 0.5]])
    old_pos = np.array([[0.0, 0.0, 0.0]])
    new_uv = np.array([[0.5, 0.5], [0.5, 0.5]])
    new_pos = np.array([[10.0, 10.0, 10.0], [0.001, 0.0, 0.0]])
    idx, worst = core.match_by_uv(old_uv, new_uv, old_pos, new_pos)
    assert worst == 0.0
    assert idx[0] == 1


# ----------------------------------------------------------------------------------------------- laplacian_smooth

def test_laplacian_smooth_keeps_pinned_vertices_fixed():
    # a 4-vertex ring; vertex 0 held, the rest start at a spike and should relax toward it, but 0 never moves
    values = np.array([[10.0], [0.0], [0.0], [0.0]])
    edges = np.array([[0, 1], [1, 2], [2, 3], [3, 0]])
    keep = np.array([True, False, False, False])
    out = core.laplacian_smooth(values, edges, n=4, iterations=20, keep_mask=keep)
    assert out[0, 0] == 10.0
    assert out[1, 0] > 0.0 and out[2, 0] > 0.0        # the spike spread to its neighbours


def test_laplacian_smooth_is_a_no_op_with_zero_iterations():
    values = np.array([[1.0], [2.0]])
    edges = np.array([[0, 1]])
    out = core.laplacian_smooth(values, edges, n=2, iterations=0)
    assert np.allclose(out, values)

"""The SDF kit: every primitive and operator by sampling, and marching cubes to a closed mesh."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersmith import sdfkit  # noqa: E402
from mastersmith.sdfkit import box, capsule, cone, cylinder, mm, plane, rounded_box, smooth_union, sphere, torus, wedge  # noqa: E402


def d(s, *pts):
    return s(np.array(pts, dtype=float))


def test_primitives_measure_distance():
    assert np.allclose(d(sphere(0.01), [0, 0, 0], [0.02, 0, 0]), [-0.01, 0.01])
    assert np.allclose(d(box((0.02, 0.04, 0.06)), [0, 0, 0], [0.02, 0, 0], [0, 0.03, 0]), [-0.01, 0.01, 0.01])
    assert np.allclose(d(cylinder(0.01, 0.1, "x"), [0, 0, 0], [0, 0.02, 0], [0.06, 0, 0]), [-0.01, 0.01, 0.01])
    assert np.allclose(d(cylinder(0.01, 0.1, "z"), [0, 0, 0.06]), [0.01])
    assert d(cone(0.02, 0.01, 0.1, "x"), [-0.05, 0.02, 0])[0] < 1e-6 < d(cone(0.02, 0.01, 0.1, "x"), [0.05, 0.02, 0])[0]
    assert np.allclose(d(capsule([0, 0, 0], [0.1, 0, 0], 0.01), [0.05, 0, 0], [0.12, 0, 0]), [-0.01, 0.01])
    assert np.allclose(d(torus(0.05, 0.01, "z"), [0.05, 0, 0], [0.07, 0, 0]), [-0.01, 0.01])
    assert np.allclose(d(plane([0, 0, 1], 0.01), [0, 0, 0], [0, 0, 0.02]), [-0.01, 0.01])
    assert d(rounded_box((0.02, 0.02, 0.02), 0.002), [0.01, 0.01, 0.01])[0] > 0 > d(rounded_box((0.02, 0.02, 0.02), 0.002), [0, 0, 0])[0]
    w = wedge((0.1, 0.04, 0.02), axis="z", across="y", taper=0.5)
    assert d(w, [0, 0.015, -0.009])[0] < 0 < d(w, [0, 0.015, 0.009])[0]     # narrow at the top, full at the bottom
    assert mm(5.56) == 0.00556


def test_operators_and_transforms():
    a, b = sphere(0.01), sphere(0.01).translate([0.015, 0, 0])
    assert d(a | b, [0.0075, 0, 0])[0] < 0 and d(a & b, [0.0075, 0, 0])[0] < 0 and d(a & b, [-0.005, 0, 0])[0] > 0
    assert d(a - b, [0.008, 0, 0])[0] > 0 and d(a - b, [-0.005, 0, 0])[0] < 0
    su = smooth_union(a, b, 0.005)
    assert d(su, [0.0075, 0.009, 0])[0] < d(a | b, [0.0075, 0.009, 0])[0]     # the fillet fills the notch
    r = cylinder(0.01, 0.1, "x").rotate("z", 90)
    assert d(r, [0, 0.04, 0])[0] < 0 and d(r, [0.04, 0, 0])[0] > 0
    assert np.allclose(d(sphere(0.01).scale(2), [0, 0, 0]), [-0.02])
    m = sphere(0.005).translate([0, 0.02, 0]).mirror("y")
    assert d(m, [0, -0.02, 0])[0] < 0 and d(m, [0, 0.02, 0])[0] < 0
    sh = sphere(0.01).shell(0.002)
    assert d(sh, [0.01, 0, 0])[0] < 0 and d(sh, [0, 0, 0])[0] > 0
    el = sphere(0.005).elongate([0.02, 0, 0])
    assert d(el, [0.02, 0, 0])[0] < 0 and d(el, [0.03, 0, 0])[0] > 0
    rep = box((0.002, 0.01, 0.01)).repeat([0.01, 0, 0], [5, 1, 1])
    assert all(v < 0 for v in d(rep, [-0.02, 0, 0], [0, 0, 0], [0.02, 0, 0])) and d(rep, [0.03, 0, 0])[0] > 0
    assert d(rep, [0.005, 0, 0])[0] > 0                                       # between two slots


def test_mesh_is_closed_and_the_right_size():
    v, f = sdfkit.mesh(cylinder(0.01, 0.1, "x") - cylinder(0.003, 0.2, "x"), [-0.05, -0.01, -0.01], [0.05, 0.01, 0.01], 0.001)
    size = v.max(axis=0) - v.min(axis=0)
    assert abs(size[0] - 0.1) < 0.003 and abs(size[1] - 0.02) < 0.003
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts == 2).all()                                                # watertight
    assert d(cylinder(0.01, 0.1, "x") - cylinder(0.003, 0.2, "x"), [0, 0, 0])[0] > 0   # the bore is a hole


def test_part_script_runs_in_the_kit_namespace():
    src = "def part(kit, L, W, H):\n    return kit.cylinder(W / 2, L, axis='x') - kit.cylinder(kit.mm(3), L * 2, axis='x')\n"
    s = sdfkit.run_part_script(src, 0.1, 0.02, 0.02)
    assert d(s, [0, 0.006, 0])[0] < 0 and d(s, [0, 0, 0])[0] > 0
    with pytest.raises(ValueError):
        sdfkit.run_part_script("x = 1\n", 1, 1, 1)
    with pytest.raises(Exception):
        sdfkit.run_part_script("def part(kit, L, W, H):\n    import os\n    return kit.sphere(1)\n", 1, 1, 1)


def test_glb_is_written_y_up_so_blender_reads_z_up(tmp_path):
    import trimesh
    v, f = sdfkit.mesh(box((0.1, 0.02, 0.3)), [-0.05, -0.01, -0.15], [0.05, 0.01, 0.15], 0.005)   # tall in Z
    p = sdfkit.write_glb(v, f, str(tmp_path / "t.glb"))
    ext = trimesh.load(p, force="mesh").extents                  # glTF frame: Y up
    assert ext[1] == pytest.approx(0.3, abs=0.02) and ext[2] == pytest.approx(0.02, abs=0.02)
    g = sdfkit.to_gltf_axes([[1.0, 2.0, 3.0]])[0]
    assert list(g) == [1.0, 3.0, -2.0]                           # Blender's import (x, -z, y) gives (1, 2, 3) back


def test_auto_voxel_keeps_the_grid_in_memory():
    assert sdfkit.auto_voxel(0.1, 0.02, 0.02) == pytest.approx(0.1 / 320)
    v = sdfkit.auto_voxel(1.5, 1.6, 0.7)                         # the two-pod part that was OOM-killed at 1 mm
    pts = (1.5 / v) * (1.6 / v) * (0.7 / v)
    assert v > 0.001 and pts <= 8_000_000


def test_hull_primitives():
    """2026-10-25: the primitives the Mk II's exact hull is written with."""
    from mastersmith.sdfkit import ellipsoid, faceted, faceted_edges, facet_normals, lerp_profile, plane_through, polygon2d, prism
    sq = polygon2d([(-1, -1), (1, -1), (1, 1), (-1, 1)])
    assert np.allclose(sq(np.array([[0.0, 0.0], [2.0, 0.0], [0.5, 0.5]])), [-1.0, 1.0, -0.5])
    assert np.allclose(sq(np.array([[0.0, 0.0]])), polygon2d([(-1, 1), (1, 1), (1, -1), (-1, -1)])(np.array([[0.0, 0.0]])))  # either winding
    pr = prism([(-1, -1), (1, -1), (1, 1), (-1, 1)], 0.2, axis="z")
    assert np.allclose(d(pr, [0, 0, 0], [0, 0, 0.3], [1.5, 0, 0]), [-0.1, 0.2, 0.5])
    fin = prism([(-1, 0), (1, 0), (0, 1)], 0.04, axis="y")                 # a triangle in the x-z plane
    assert d(fin, [0, 0, 0.5])[0] < 0 < d(fin, [0, 0.05, 0.5])[0]
    e = ellipsoid((2.0, 1.0, 0.5))
    assert np.allclose(d(e, [2.0, 0, 0], [0, 0, 0.5], [0, 2.0, 0]), [0.0, 0.0, 1.0], atol=1e-9)
    assert d(e, [0, 0, 0])[0] < 0
    assert np.allclose(d(plane_through([0, 0, 1], [1, 0, 1], [0, 1, 1]), [0, 0, 0], [0, 0, 2]), [-1.0, 1.0])
    ns = facet_normals([30, 60], [0, 90, 180, 270])
    assert len(ns) == 9 and np.allclose([np.linalg.norm(n) for n in ns], 1)
    fc = faceted((1.0, 1.0, 1.0), ns)                                       # circumscribes the unit sphere
    assert d(fc, [0, 0, 1.0])[0] <= 1e-9 and d(fc, [0, 0, 0])[0] < 0 and d(fc, [0.99, 0, 0])[0] < 0.2  # the top is a tangent plane; the sides stand a little off the sphere
    ridge = faceted_edges((1.0, 1.0, 1.0), ns, 0.05)
    # the crease between the pitch-60 yaw-0 facet and the top: near both planes; mid-facet only one is close
    assert d(ridge, [0.0, 0.0, 1.0])[0] > 0           # under the top plane only (the others are far): not a crease
    assert d(ridge, [np.cos(np.radians(75)), 0, np.sin(np.radians(75)) + 0.03])[0] < 0.1
    prof = lerp_profile([(0, 1.0), (1, 2.0), (3, 2.0)])
    assert np.allclose(prof(np.array([-1, 0.5, 2, 5])), [1.0, 1.5, 2.0, 2.0])


def test_faceted_bars_follow_the_creases():
    from mastersmith.sdfkit import faceted, faceted_bars, faceted_edge_lines, facet_normals
    ns = facet_normals([30, 60], [0, 90, 180, 270])          # a 9-plane polyhedron round the unit sphere
    segs = faceted_edge_lines((1.0, 1.0, 1.0), ns)
    assert 12 <= len(segs) <= 24
    fc = faceted((1.0, 1.0, 1.0), ns)
    for a, b in segs:                                          # every edge lies on the polyhedron's surface
        assert abs(fc(np.array([(a + b) / 2]))[0]) < 1e-6
    bars = faceted_bars((1.0, 1.0, 1.0), ns, 0.02)
    a, b = segs[0]
    assert d(bars, (a + b) / 2)[0] < 0 < d(bars, (a + b) / 2 + np.array([0, 0, 0.1]))[0]


def test_decimate_keeps_a_box_sharp():
    from mastersmith.sdfkit import box, decimate, mesh
    v, f = mesh(box((0.2, 0.1, 0.05)), [-0.1, -0.05, -0.025], [0.1, 0.05, 0.025], 0.002)
    v2, f2 = decimate(v, f, 2000)
    assert len(f2) <= max(2000, len(f) // 10) or len(f) <= 2000
    assert np.allclose(v2.min(0), v.min(0), atol=0.003) and np.allclose(v2.max(0), v.max(0), atol=0.003)


def test_a_part_script_may_return_its_own_triangles():
    """2026-10-25 (hard r2): a 2 mm steel blade is triangles, not a field; collapsed faces are dropped."""
    src = ("def part(kit, L, W, H):\n"
           "    v = kit.np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0]], dtype=float)\n"
           "    return kit.mesh_part(v, [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3], [0, 1, 4]])\n")
    m = sdfkit.run_part_script(src, 1, 1, 1)
    assert isinstance(m, sdfkit.MeshPart) and len(m.faces) == 4
    with pytest.raises(ValueError):
        sdfkit.mesh_part([[0, 0, 0]], [[0, 1, 2]])

"""The nature category (2026-10-03, the Training Pool's coral, kelp, shells and fish): sized by the longest side, a
foliage budget, no glass, a category file the picture and seed stages can read; a thin sheet's inward normals."""
import importlib.util
from pathlib import Path

import numpy as np

from mastersmith import skills
from mastersmith.spec import Spec
from mastersmith.stages.plan import longest_side


def test_a_nature_brief_keeps_its_category_and_gets_a_foliage_budget():
    s = Spec(name="KelpMedium", description="one rooted kelp plant", category="nature")
    assert s.category == "nature"
    assert s.tri_budget == 8000
    assert s.glass is False


def test_a_nature_object_is_sized_by_its_longest_side():
    # the coral seeded deeper than its side picture: 0.70 x 1.09 x 0.74 m for a 0.9 m brief
    dims = longest_side((0.70, 1.09, 0.74), 0.9)
    assert abs(max(dims) - 0.9) < 1e-9
    assert abs(dims[0] / dims[2] - 0.70 / 0.74) < 1e-9          # one scale: the proportions stay the seed's
    # a kelp standing taller than it is long: its height becomes the brief's 4.4 m
    assert abs(longest_side((2.0, 1.0, 4.0), 4.4)[2] - 4.4) < 1e-9


def test_the_nature_category_file_is_read():
    assert "nature" in skills.all_categories()
    meta = skills.load("nature")["meta"]
    assert meta["origin"] == "bottom"
    assert meta["default_tris"] == 8000
    assert meta["forward_axis"] == "long"


def test_normals_baked_from_a_thin_sheets_back_face_are_turned_out():
    path = Path(__file__).resolve().parents[1] / "mastersmith/blender/normalfix.py"
    spec = importlib.util.spec_from_file_location("normalfix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    px = np.zeros((2, 2, 4), np.float32)
    px[..., :3] = [0.5, 0.5, 1.0]                     # flat, facing out
    px[0, 1, :3] = [0.6, 0.4, 0.05]                   # a back-face hit: (0.2, -0.2, -0.9)
    px[1, 1, :3] = [0.5, 0.5, 0.0]                    # inward too, but in the gutter (not covered): left alone
    covered = np.array([[True, True], [True, False]])
    share = module.flip_inward(px, covered)
    assert share == 1 / 3
    assert np.allclose(px[0, 1, :3], [0.4, 0.6, 0.95])            # (-0.2, 0.2, 0.9): out of the surface
    assert np.allclose(px[0, 0, :3], [0.5, 0.5, 1.0])
    assert np.allclose(px[1, 1, :3], [0.5, 0.5, 0.0])


def _silhouette():
    path = Path(__file__).resolve().parents[1] / "mastersmith/blender/silhouette.py"
    spec = importlib.util.spec_from_file_location("silhouette", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_lattice_is_registered_by_its_envelope():
    s = _silhouette()
    fan = np.zeros((96, 96), bool)
    for k in range(8, 88, 8):                          # a fan of thin branches: a lattice of one-pixel lines
        fan[k, 10:86] = True
        fan[10:86, k] = True
    moved = np.roll(np.roll(fan, 2, axis=0), 2, axis=1)  # the same fan, two pixels off
    assert s.fill_ratio(fan) < 0.45
    assert s.iou(fan, moved) < 0.3                     # raw: near noise
    assert s.iou(s.envelope(fan), s.envelope(moved)) > 0.9
    solid = np.zeros((96, 96), bool)
    solid[20:80, 10:90] = True
    assert s.fill_ratio(solid) > 0.9
    ring = np.zeros((40, 40), bool)
    ring[5:35, 5:35] = True
    ring[10:30, 10:30] = False
    assert s.fill_holes(ring)[20, 20]                  # a hole inside is filled, the outside is not
    assert not s.fill_holes(ring)[0, 0]

"""The reference views must describe one object before anything is seeded (2026-10-23: the Mk II sheet's hero was a
saucer and its top view an arrowhead; every seed followed the picture it got and lost the silhouette score)."""
import os

from PIL import Image, ImageDraw

from mastersmith import viewcheck


def _view(path, w, h, colour=(200, 60, 50), size=400):
    im = Image.new("RGB", (size, size), "white")
    x0, y0 = (size - w) // 2, (size - h) // 2
    ImageDraw.Draw(im).ellipse([x0, y0, x0 + w, y0 + h], fill=colour)
    im.save(path)


def _refs(tmp_path, L, W, H, colours=None, scale=0.8):
    """Orthographic views of one L x W x H box, each drawn at its own scale (a view is cropped tighter than another)."""
    ref = tmp_path / "ref"
    ref.mkdir(exist_ok=True)
    colours = colours or {}
    k = 300.0 / max(L, W, H)
    _view(str(ref / "ref_0.png"), 300, 160, colours.get("hero", (200, 60, 50)))
    _view(str(ref / "ref_side.png"), int(L * k), int(H * k), colours.get("side", (200, 60, 50)))
    _view(str(ref / "ref_front.png"), int(W * k * scale), int(H * k * scale), colours.get("front", (200, 60, 50)))
    _view(str(ref / "ref_back.png"), int(W * k), int(H * k), colours.get("back", (200, 60, 50)))
    _view(str(ref / "ref_top.png"), int(W * k), int(L * k), colours.get("top", (200, 60, 50)))
    return str(ref)


def test_views_of_one_object_close_and_pass(tmp_path):
    ref = _refs(tmp_path, L=4.0, W=3.8, H=1.6)
    rep = viewcheck.write(ref)
    assert rep["pass"] and rep["warnings"] == [] and os.path.isfile(os.path.join(ref, "consistency.json"))
    assert rep["closure"]["error"] < 0.05
    assert abs(rep["dims_ratio"]["W"] - 0.95) < 0.03 and abs(rep["dims_ratio"]["H"] - 0.4) < 0.03


def test_a_top_view_of_a_narrower_object_fails_closure(tmp_path):
    # the sheet's case: hero/front/side a wide saucer, the top view half as wide
    ref = _refs(tmp_path, L=4.0, W=3.8, H=1.6)
    k = 300.0 / 4.0
    _view(os.path.join(ref, "ref_top.png"), int(1.9 * k), int(4.0 * k))
    rep = viewcheck.check(ref)
    assert not rep["pass"]
    assert any("do not describe one object" in w for w in rep["warnings"])
    assert rep["closure"]["error"] > 0.5


def test_front_and_back_that_disagree_are_named(tmp_path):
    ref = _refs(tmp_path, L=4.0, W=3.8, H=1.6)
    k = 300.0 / 4.0
    _view(os.path.join(ref, "ref_back.png"), int(2.4 * k), int(1.6 * k))
    rep = viewcheck.check(ref)
    assert any(w.startswith("front reads H/W") or w.startswith("back reads H/W") for w in rep["warnings"])


def test_a_repainted_view_is_flagged_and_a_weapon_set_still_runs(tmp_path):
    ref = _refs(tmp_path, L=4.0, W=3.8, H=1.6, colours={"top": (40, 40, 160)})
    rep = viewcheck.check(ref)
    assert any("colour differs" in w and "ref_top" in w for w in rep["warnings"])
    # a weapon has side and front only: the proportions cannot close, which is said, and nothing else fails
    os.remove(os.path.join(ref, "ref_top.png"))
    os.remove(os.path.join(ref, "ref_back.png"))
    rep = viewcheck.check(ref)
    assert any("cannot close" in w for w in rep["warnings"]) and rep["closure"] is None
    assert viewcheck.read(str(tmp_path / "nowhere")) is None

"""The model registry (owner, 2026-09-29): built-in models with prices, local models registered by command line,
and the views a whole-object seed is made from."""
import json
import os
import sys

import pytest
from PIL import Image

from mastersmith import models


def test_builtins_resolve_with_aliases_and_kinds():
    assert models.resolve("hitem3d3mv")["key"] == "hi3d-mv"
    assert models.resolve("local", kind="seed")["endpoint"].startswith("local/")
    with pytest.raises(KeyError):
        models.resolve("nano", kind="seed")
    with pytest.raises(KeyError):
        models.resolve("nope")


def test_add_list_remove_a_local_command(tmp_path):
    reg = str(tmp_path / "local_models.json")
    models.add("hunyuan-local", "seed", "hy.exe --in {image} --out {out}", label="Hunyuan3D local", path=reg)
    assert models.all_models(reg)["hunyuan-local"]["source"] == "local command"
    assert models.price_of(models.resolve("hunyuan-local", path=reg)) == 0.0
    with pytest.raises(ValueError):
        models.add("hi3d", "seed", "x {image} {out}", path=reg)            # a built-in name
    with pytest.raises(ValueError):
        models.add("bad", "seed", "x {image}", path=reg)                    # writes nothing
    models.remove("hunyuan-local", path=reg)
    assert "hunyuan-local" not in models.all_models(reg)


def test_run_command_fills_placeholders_and_needs_the_output(tmp_path):
    out = tmp_path / "seed.glb"
    img = tmp_path / "in put.png"
    img.write_bytes(b"png")
    cmd = '"%s" -c "import sys,shutil; shutil.copy(sys.argv[1], sys.argv[2])" {image} {out}' % sys.executable
    m = dict(key="copy", command=cmd)
    models.run_command(m, str(out), image=str(img), images=[str(img)])
    assert out.read_bytes() == b"png"
    m = dict(key="nothing", command='"%s" -c "pass" {out}' % sys.executable)
    with pytest.raises(RuntimeError):
        models.run_command(m, str(tmp_path / "never.glb"), image=str(img), images=[str(img)])


def _pic(path):
    Image.new("RGB", (40, 20), "white").save(path)


def test_seed_views_by_category_and_payload_slots(tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    for f in ("ref_0", "ref_front"):
        _pic(ref / (f + ".png"))
    v = models.seed_views("weapon", str(ref), str(tmp_path))
    assert v["left"].endswith("ref_0.png") and os.path.exists(v["right"]) and "back" not in v
    urls = {r: "u_" + r for r in v}
    ep, payload = models.seed_payload(models.resolve("hi3d-mv"), urls)
    assert payload["left_image_url"] == "u_left" and payload["front_image_url"] == "u_front" and "back_image_url" not in payload
    with pytest.raises(ValueError):
        models.seed_payload(models.resolve("tripo-mv"), urls)               # no back view
    ep, payload = models.seed_payload(models.resolve("hi3d"), urls, primary="left")
    assert payload["image_url"] == "u_left"
    for f in ("ref_side", "ref_back"):
        _pic(ref / (f + ".png"))
    v = models.seed_views("vehicle", str(ref), str(tmp_path))
    assert v["left"].endswith("ref_side.png") and v["hero"].endswith("ref_0.png") and "back" in v


def test_a_one_part_plan_is_valid():
    from mastersmith.stages.plan import validate_plan
    plan = validate_plan({"parts": [{"name": "Body", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100],
                                      "material": {"keep_texture": True}}]}, [0.84, 0.07, 0.26])
    assert len(plan["parts"]) == 1 and plan["parts"][0]["material"]["keep_texture"] is True


def test_vendor_front_axis_and_segment_models():
    # 2026-10-04 (Mixar's per-engine table): Tripo seeds face +X after import; registration takes it as a prior
    assert models.resolve("tripo")["front"] == "+X" and models.resolve("tripo-mv")["front"] == "+X"
    assert models.front_yaw("+X") == 0 and models.front_yaw("-Y") == 90 and models.front_yaw("+Y") == -90
    assert models.front_yaw(None) is None and models.front_yaw("") is None
    # the pictured view turns it: a side-view seed's muzzle lies on +Y (the bullpup, 2026-10-04), a back view faces away
    assert models.front_yaw("+X", "left") == -90 and models.front_yaw("+X", "back") == 180
    assert models.front_yaw("-Y", "left") == 0 and models.front_yaw("+X", "hero") is None
    seg = models.resolve("hunyuan-part", kind="segment")
    assert seg["endpoint"] == "fal-ai/hunyuan-3d/v3.1/part" and models.price_of(seg) == 0.45
    with pytest.raises(KeyError):
        models.resolve("hunyuan-part", kind="seed")


def test_registered_model_may_say_which_way_it_faces(tmp_path):
    reg = str(tmp_path / "local_models.json")
    m = models.add("hy-local", "seed", "hy.exe --in {image} --out {out}", path=reg, front="-y")
    assert m["front"] == "-Y" and models.all_models(reg)["hy-local"]["front"] == "-Y"
    with pytest.raises(ValueError):
        models.add("hy-bad", "seed", "hy.exe --in {image} --out {out}", path=reg, front="up")

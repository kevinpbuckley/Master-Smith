"""`ms plan` takes every key AGENTS.md documents and names every one it does not take (2026-10-02: validate_plan
dropped unknown keys silently and was patched six times in one day for keys the agent had already written)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersmith.stages import plan as planmod  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIMS = (1.0, 0.1, 0.3)


def _part(**extra):
    p = {"name": "Body", "what": "x", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100],
         "material": {"color": "#808080", "finish": "painted", "keep_texture": True}}
    p.update(extra)
    return p


def test_every_documented_plan_key_is_known():
    text = open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read()
    section = text.split("## The plan JSON", 1)[1].split("\n## ", 1)[0]
    keys = set(re.findall(r'"([a-z_]+)":', section))
    known = planmod.TOP_KEYS | planmod.PART_KEYS | planmod.ZONE_KEYS | planmod.MATERIAL_KEYS | planmod.GLOW_KEYS
    assert keys, "no keys found in the plan section"
    assert keys <= known, sorted(keys - known)


def test_unknown_and_invalid_keys_are_named():
    raw = {"parts": [_part(zones=[{"name": "Canopy", "side_box": [40, 60, 0, 30], "pick": "pail", "shine": 1,
                                   "material": {"finish": "glass", "sparkle": True}}], colour_lock=True)],
           "notes": "", "extra": 1}
    plan = planmod.validate_plan(raw, DIMS)
    text = " | ".join(plan["ignored"])
    for bit in ("plan.extra", "Body.colour_lock", "Canopy].shine", "pick='pail'", "material.sparkle"):
        assert bit in text, (bit, text)
    zone = plan["parts"][0]["zones"][0]
    assert "pick" not in zone                       # the bad value is not taken
    assert planmod.validate_plan(plan, DIMS)["ignored"] == []   # a validated plan fed back is clean


def test_emissive_strength_and_fitted_panes_pass_through():
    fitted = {"name": "Windscreen", "side_box": [70, 80, 10, 30], "pick": "fitted",
              "vertices": [[0.1, -0.02, 0.1], [0.2, -0.02, 0.1], [0.15, 0.02, 0.12]], "triangles": [[0, 1, 2]],
              "tolerance": 0.01, "bounds": [[0, -0.05, 0], [0.3, 0.05, 0.2]], "material": {"finish": "glass"}}
    lamp = {"name": "Lamp", "side_box": [90, 95, 40, 50], "material": {"finish": "emissive", "strength": 9}}
    broken = dict(fitted, name="Broken", triangles=[[0, 1, 7]])
    plan = planmod.validate_plan({"parts": [_part(zones=[fitted, lamp, broken])]}, DIMS)
    zones = {z["name"]: z for z in plan["parts"][0]["zones"]}
    assert zones["Windscreen"]["pick"] == "fitted" and zones["Windscreen"]["tolerance"] == 0.01
    assert zones["Windscreen"]["triangles"] == [[0, 1, 2]] and len(zones["Windscreen"]["bounds"]) == 2
    assert zones["Lamp"]["material"]["strength"] == 9
    assert "Broken" not in zones and any("Broken" in w and "dropped" in w for w in plan["ignored"])

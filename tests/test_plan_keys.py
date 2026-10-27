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


def test_glass_alpha_passes_through_clamped():
    """2026-10-04: a glass zone's own pane (alpha, colour, roughness) reaches the assembler; non-glass drops it."""
    assert "alpha" in planmod.MATERIAL_KEYS
    m = planmod.clean_material({"finish": "glass", "color": "#060808", "alpha": 0.6, "roughness": 0.08})
    assert m["glass"] and m["alpha"] == 0.6 and m["roughness"] == 0.08 and m["color"] == "#060808"
    # 2026-10-23: a clear canopy's lower specular reaches the assembler too (the Mk II pane at 0.45 read as a mirror)
    assert "specular" in planmod.MATERIAL_KEYS
    m = planmod.clean_material({"finish": "glass", "alpha": 0.2, "specular": 0.18})
    assert m["specular"] == 0.18 and m["alpha"] == 0.2
    assert planmod.clean_material({"finish": "glass", "alpha": 0.2, "specular": 2.0})["specular"] == 0.8
    assert "specular" not in planmod.clean_material({"finish": "painted", "specular": 0.2})
    assert planmod.clean_material({"finish": "glass", "alpha": 0.95})["alpha"] == 0.7
    assert planmod.clean_material({"finish": "glass", "alpha": True}).get("alpha") is None
    assert planmod.clean_material({"finish": "painted", "alpha": 0.5}).get("alpha") is None


def test_an_interior_part_may_carve_a_box_of_its_own():
    """2026-10-23: the box an insert fills and the box the seed's cockpit is carved out of are two different things."""
    insert = _part(name="Cockpit", interior=True, side_box=[60, 85, 25, 65], front_span=[37, 63],
                   carve_box=[60, 90, 10, 65])
    nozzle = _part(name="Nozzle", carve=True, side_box=[0, 10, 40, 60], carve_box=[0, 12, 40, 60])
    plan = planmod.validate_plan({"parts": [_part(), insert, nozzle]}, DIMS)
    parts = {p["name"]: p for p in plan["parts"]}
    cp = parts["Cockpit"]
    assert cp["carve_box"] == [60, 90, 10, 65] and "carve_span" not in cp
    assert cp["carve_min"][0] == cp["box_min"][0] and cp["carve_max"][0] > cp["box_max"][0]   # longer than the fill box
    assert cp["carve_max"][2] > cp["box_max"][2] and cp["carve_min"][1:] == cp["box_min"][1:]  # up into the canopy, same span
    assert cp["sharpen"] is False                                   # an interior part is unsharpened by default
    assert "carve_min" not in parts["Nozzle"] and any("Nozzle.carve_box" in s for s in plan["ignored"])
    assert "sharpen" not in parts["Nozzle"]
    assert planmod.validate_plan(plan, DIMS)["ignored"] == []       # carve_min/carve_max fed back are not "ignored"
    told = planmod.validate_plan({"parts": [_part(name="Cab", interior=True, sharpen=True, carve_box=[1, 2])]}, DIMS)
    assert "sharpen" not in told["parts"][0] and any("Cab.carve_box" in s for s in told["ignored"])


def test_a_zone_may_name_segmentation_labels_instead_of_a_box():
    # 2026-10-04: `ms segment` labels the seed's faces; a zone names labels, with or without a box
    raw = {"parts": [_part(zones=[{"name": "Barrel", "segment": 3, "material": {"finish": "metal", "metal": True}},
                                   {"name": "Pads", "segment": [1, 4], "side_box": [0, 50, 0, 100], "material": {"finish": "rubber"}},
                                   {"name": "Bad", "segment": "three", "side_box": [0, 50, 0, 100], "material": {"finish": "rubber"}}])],
           "notes": ""}
    plan = planmod.validate_plan(raw, DIMS)
    zones = {z["name"]: z for z in plan["parts"][0]["zones"]}
    assert zones["Barrel"]["segment"] == 3 and zones["Barrel"]["box_given"] is False
    assert zones["Barrel"]["side_box"] == [0, 100, 0, 100]                    # the whole part: the labels decide
    assert zones["Pads"]["segment"] == [1, 4] and zones["Pads"]["box_given"] is True
    assert "segment" not in zones["Bad"] and any("Bad].segment" in s for s in plan["ignored"])


def test_a_skinned_part_may_fit_its_seed_to_a_box_of_its_own():
    """2026-10-25 (hard r2): the skin's seed fills its own box; fitted to the sdf hull's it was squeezed 5% narrower."""
    hull = _part(name="Hull", skin="Body", side_box=[1, 98, 4, 100], front_span=[3, 97], skin_box=[0, 100, 0, 100], skin_span=[0, 100])
    plain = _part(name="Fin", side_box=[0, 20, 0, 50], skin_box=[0, 100, 0, 100])
    plan = planmod.validate_plan({"parts": [hull, plain]}, DIMS)
    parts = {p["name"]: p for p in plan["parts"]}
    h = parts["Hull"]
    assert h["skin_min"][0] < h["box_min"][0] and h["skin_max"][1] > h["box_max"][1]
    assert "skin_min" not in parts["Fin"] and any("Fin.skin_box" in s for s in plan["ignored"])
    assert planmod.validate_plan(plan, DIMS)["ignored"] == []


def test_kept_texture_floor_keys_and_clear_glass():
    """2026-10-26: a kept texture's roughness floor and metallic ceiling reach the assembler; a clear canopy's alpha
    goes down to 0.08."""
    m = planmod.clean_material({"finish": "painted", "keep_texture": True, "roughness_min": 0.62, "metal_max": 0.02})
    assert m["roughness_min"] == 0.62 and m["metal_max"] == 0.02
    assert "roughness_min" not in planmod.clean_material({"finish": "painted"})
    # 2026-10-26: "weather" on paint, clamped to 0-1, never on glass
    assert planmod.clean_material({"finish": "painted", "weather": 1.7})["weather"] == 1.0
    assert "weather" not in planmod.clean_material({"finish": "glass", "weather": 0.5})
    assert planmod.clean_material({"finish": "glass", "alpha": 0.1})["alpha"] == 0.1
    assert planmod.clean_material({"finish": "glass", "alpha": 0.01})["alpha"] == 0.08


def test_streaks_and_edge_alpha_pass_through_clamped():
    """2026-10-26 (hard r14): "streaks" on paint and "edge_alpha" on glass reach the assembler, clamped."""
    paint = {"name": "Deck", "side_box": [0, 50, 0, 50], "material": {"finish": "painted", "weather": 0.6, "streaks": 3}}
    glass = {"name": "Pane", "side_box": [50, 90, 0, 40], "material": {"finish": "glass", "alpha": 0.2, "edge_alpha": 0.7}}
    plan = planmod.validate_plan({"parts": [_part(zones=[paint, glass])]}, DIMS)
    zones = {z["name"]: z for z in plan["parts"][0]["zones"]}
    assert zones["Deck"]["material"]["streaks"] == 1.0 and zones["Deck"]["material"]["weather"] == 0.6
    assert zones["Pane"]["material"]["edge_alpha"] == 0.7
    assert "edge_alpha" not in zones["Deck"]["material"]
    assert plan["ignored"] == []


def test_dirt_reach_and_sdf_box_margin():
    """2026-10-26 (hard r15): "dirt_reach" reaches the assembler clamped; an sdf part's box may stand past the frame
    (the Mk II's raised fin tip), any other part's is clamped to it."""
    paint = {"name": "Deck", "side_box": [0, 50, 0, 50], "material": {"finish": "painted", "weather": 0.6, "dirt_reach": 0.5}}
    sdf = _part(name="Fin", method="sdf", side_box=[0, 20, -6, 50], zones=[paint])
    vendor = _part(name="Pod", side_box=[0, 20, -6, 50])
    plan = planmod.validate_plan({"parts": [sdf, vendor]}, DIMS)
    parts = {p["name"]: p for p in plan["parts"]}
    assert parts["Fin"]["zones"][0]["material"]["dirt_reach"] == 0.2
    assert parts["Fin"]["side_box"][2] == -6 and abs(parts["Fin"]["box_max"][2] - (0.15 + 0.06 * 0.3)) < 1e-9
    assert parts["Pod"]["side_box"][2] == 0 and abs(parts["Pod"]["box_max"][2] - 0.15) < 1e-9
    assert plan["ignored"] == []


def test_bump_key():
    """2026-10-26 (hard r16): a surface's "bump" reaches the assembler clamped to 0-1; glass takes none."""
    paint = {"name": "Deck", "side_box": [0, 50, 0, 50], "material": {"finish": "painted", "bump": 1.7}}
    part = _part(name="Veneer", method="sdf", zones=[paint], material={"finish": "painted", "bump": 0.05})
    plan = planmod.validate_plan({"parts": [part]}, DIMS)
    p = plan["parts"][0]
    assert p["material"]["bump"] == 0.05 and p["zones"][0]["material"]["bump"] == 1.0
    assert plan["ignored"] == []


def test_flat_normal_key():
    """2026-10-26 (hard r17): "flat_normal": true on a part reaches the assembler; anything else is not set."""
    plan = planmod.validate_plan({"parts": [_part(name="Veneer", method="sdf", flat_normal=True),
                                            _part(name="Other", method="sdf", flat_normal="yes")]}, DIMS)
    a, b = plan["parts"]
    assert a.get("flat_normal") is True and "flat_normal" not in b
    assert plan["ignored"] == []

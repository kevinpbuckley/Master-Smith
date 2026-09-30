"""A code part can opt out of the reference detail projection (2026-09-28: the projected hood interior of the
drawn sight printed a pale patch on the coded sight)."""
from mastersmith.stages.plan import validate_plan


def test_reference_detail_flag_is_kept_and_defaults_true():
    raw = {"parts": [
        {"name": "FrontSight", "method": "code", "side_box": [70, 80, 0, 20], "front_span": [40, 60], "reference_detail": False},
        {"name": "Barrel", "method": "code", "side_box": [80, 95, 25, 33], "front_span": [45, 55]}]}
    plan = validate_plan(raw, [0.68, 0.078, 0.26])
    by = {p["name"]: p for p in plan["parts"]}
    assert by["FrontSight"]["reference_detail"] is False
    assert by["Barrel"]["reference_detail"] is True


def test_color_lock_keeps_the_planned_colour():
    from mastersmith.stages.plan import clean_material
    m = clean_material({"color": "#1e2024", "finish": "metal", "color_lock": True})
    assert m["color_lock"] is True and m["color"] == "#1e2024"
    assert clean_material({"color": "#1e2024"})["color_lock"] is False


def test_skin_edge_break_interior_flags_pass_through():
    # 2026-09-29: code parts dressed in a diffused texture, razor edges opted into, a cockpit checked to fit its hull
    raw = {"parts": [
        {"name": "Barrel", "method": "code", "side_box": [80, 95, 25, 33], "front_span": [45, 55], "skin": True, "edge_break": False},
        {"name": "Cockpit", "method": "vendor", "side_box": [20, 40, 10, 30], "front_span": [40, 60], "interior": True},
        {"name": "Body", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100]}]}
    by = {p["name"]: p for p in validate_plan(raw, [10.0, 2.0, 3.0])["parts"]}
    assert by["Barrel"]["skin"] is True and by["Barrel"]["edge_break"] is False
    assert by["Cockpit"]["interior"] is True
    assert "skin" not in by["Body"] and "interior" not in by["Body"]


def test_zone_pick_keep_and_strength_pass_through():
    # 2026-09-29: a glass zone picked by the seed's texture, an emissive zone's strength
    raw = {"parts": [{"name": "Body", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100],
                      "zones": [{"name": "Canopy", "side_box": [60, 90, 10, 50], "pick": "dark", "keep": 2, "material": {"finish": "glass", "glass": True}},
                                {"name": "Lamp", "side_box": [90, 95, 40, 45], "strength": 9, "pick": "nonsense", "material": {"finish": "emissive"}}]}]}
    z = validate_plan(raw, [14.0, 5.0, 6.0])["parts"][0]["zones"]
    assert z[0]["pick"] == "dark" and z[0]["keep"] == 2
    assert z[1]["strength"] == 9 and "pick" not in z[1]


def test_glass_zone_pale_auto_and_fill_pass_through():
    # 2026-09-29: a Tripo canopy is painted pale on its panes; "auto" picks the style, "fill" shells the holes
    raw = {"parts": [{"name": "Body", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100],
                      "zones": [{"name": "Canopy", "side_box": [60, 90, 10, 50], "pick": "pale", "fill": False, "line": False, "shell": True, "material": {"finish": "glass"}},
                                {"name": "Visor", "side_box": [60, 70, 10, 20], "pick": "auto", "fill": "yes", "material": {"finish": "glass"}}]}]}
    z = validate_plan(raw, [14.0, 5.0, 6.0])["parts"][0]["zones"]
    assert z[0]["pick"] == "pale" and z[0]["fill"] is False and z[0]["line"] is False and z[0]["shell"] is True
    assert z[1]["pick"] == "auto" and "fill" not in z[1]


def test_lettering_boxes_pass_through():
    # 2026-09-29: painted words print whole and read the right way on the far side
    raw = {"parts": [{"name": "Body", "method": "vendor", "side_box": [0, 100, 0, 100], "front_span": [0, 100],
                      "lettering": [[74, 84, 67, 74], [80, 70, 10, 20], "junk", [1, 2, 3]]}]}
    part = validate_plan(raw, [14.0, 5.0, 6.0])["parts"][0]
    assert part["lettering"] == [[74.0, 84.0, 67.0, 74.0]]

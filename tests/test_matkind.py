"""`ms closeup --hide glass` must find a glass zone's own pane material (2026-10-23: the Mk II's
MI_ProteusMkII_Glass_Body_Canopy was taken as body and every no-glass close-up was the plain render)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mastersmith", "blender"))
import matkind  # noqa: E402


def test_delivered_material_names_are_sorted_into_kinds():
    k = matkind.material_kind
    assert k("MI_ProteusMkII", "ProteusMkII") == "body"
    assert k("MI_ProteusMkII_Glass", "ProteusMkII") == "glass"
    assert k("MI_ProteusMkII_Glass_Body_Canopy", "ProteusMkII") == "glass"
    assert k("MI_ProteusMkII_Interior", "ProteusMkII") == "lining"
    assert k("MI_ProteusMkII_Frame", "ProteusMkII") == "frame"
    assert k("MI_Havoc_Glass_Body_Windscreen") == "glass"            # without the asset name too
    assert k("MI_GlassCannon", "GlassCannon") == "body"               # the asset's own name is not a kind
    assert k("MI_GlassCannon_Glass_Body_Scope", "GlassCannon") == "glass"
    assert k(None) == "body" and k("") == "body"

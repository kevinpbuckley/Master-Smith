"""Which delivered material a slot is, from its name alone (pure python: tests load it without Blender).

The assembler names its materials MI_<Name> (the atlas body), MI_<Name>_Glass (one glass part) or
MI_<Name>_Glass_<Part>_<Zone> (a glass zone with its own pane colour), MI_<Name>_Interior (the cockpit lining),
MI_<Name>_Frame (the canopy frame band). 2026-10-23: `ms closeup --hide glass` tested the name's END for "_glass",
so the Mk II's MI_ProteusMkII_Glass_Body_Canopy was "body" and every no-glass close-up was the plain render."""

KINDS = ("glass", "interior", "frame")


def material_kind(name, asset=None):
    """'glass' | 'lining' | 'frame' | 'body' for a delivered material's name."""
    n = str(name or "")
    if asset and n.lower().startswith(("mi_%s_" % asset).lower()):
        n = n[len(asset) + 4:]
    else:
        n = n[3:] if n.lower().startswith("mi_") else n
    tokens = [t.lower() for t in n.split("_") if t]
    for t in tokens:
        if t == "glass":
            return "glass"
        if t == "interior":
            return "lining"
        if t == "frame":
            return "frame"
    return "body"

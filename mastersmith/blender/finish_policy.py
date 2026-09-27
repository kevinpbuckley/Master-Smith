"""Pure safety decisions for finishing; kept free of bpy for regression tests."""


# Dihedral angle above which an edge is a hard edge (split normals). OFF by default: collapse decimation leaves a thin
# barrel with about five sides, and any angle-based split then shades it as flat facets. Measured on the Hi3D bullpup
# (2026-09-26, same seed, identical cameras): 40 and 60 degrees both turned the barrel's round highlight flat and dull,
# while the gain on the stock's facets was marginal; the baked normal map already carries the creases. A skill may
# opt in with `hard_edge_angle` for assets that are all flat panels (crates, buildings, boxy vehicles).
HARD_EDGE_ANGLES = {}


def hard_edge_angle(category, texture_fixes=(), override=None):
    """Degrees, or None for all-smooth shading. A skill's `hard_edge_angle` overrides the category (0 turns it off);
    the organic smoothing repair always wins."""
    if "smooth_organic_normals" in (texture_fixes or ()):
        return None
    if override is not None:
        try:
            value = float(override)
        except (TypeError, ValueError):
            value = None
        return value if value and 5.0 <= value <= 89.0 else None
    return HARD_EDGE_ANGLES.get(category)


def detail_bake_skip_reason(material_names, preserve_seed_maps=False):
    if preserve_seed_maps:
        return "preserve_seed_maps: retain the source normal/AO instead of generating a replacement"
    # Joined vendor parts each have a full 0..1 atlas. The legacy baker has ONE target image per pass,
    # so different materials write on top of each other. Sharing a UV layer name is not a shared atlas.
    if len(set(material_names)) > 1:
        return "multiple material UV domains: the shared-atlas baker cannot safely combine them"
    return None

"""Reduce generated surface exaggeration without changing a seed's geometry or colour maps."""


def depth_zones(zones, planned_min, planned_max, actual_min, actual_max):
    """Carry material masks with a kept-depth seed instead of leaving its wider side faces unassigned."""
    width = planned_max - planned_min
    if width <= 1e-9:
        return zones, 1.0
    scale = (actual_max - actual_min) / width
    result = []
    for zone in zones:
        copy = dict(zone, box_min=list(zone["box_min"]), box_max=list(zone["box_max"]))
        for bound in ("box_min", "box_max"):
            copy[bound][1] = actual_min + (zone[bound][1] - planned_min) * scale
        result.append(copy)
    return result, scale


def apply(mats, material, length_m):
    """Keep microstructure while removing mirror-like patches and oversized procedural relief."""
    finish = material.get("finish", "painted")
    if finish in ("glass", "emissive") or material.get("glass"):
        return 0
    floors = {"metal": 0.52, "painted": 0.58, "polymer": 0.65, "rubber": 0.86,
              "wood": 0.65, "fabric": 0.8, "concrete": 0.8}
    floor = max(floors.get(finish, 0.58), min(0.9, float(material.get("roughness", 0.0))))
    count = 0
    for mat in mats:
        if not mat or not mat.node_tree or mat.get("ms_glass"):
            continue
        tree = mat.node_tree
        bsdf = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        # 2026-09-30: Tripo's normals plus stacked 1 mm bumps and glossy edge wear read as melted metal.
        for node in list(tree.nodes):
            if node.type in ("NORMAL_MAP", "BUMP"):
                strength = node.inputs["Strength"]
                gain = 0.25 if node.type == "NORMAL_MAP" else 0.2
                if strength.is_linked:
                    source = strength.links[0].from_socket
                    scale = tree.nodes.new("ShaderNodeMath")
                    scale.operation = "MULTIPLY"
                    scale.inputs[1].default_value = gain
                    tree.links.new(source, scale.inputs[0])
                    tree.links.new(scale.outputs[0], strength)
                else:
                    strength.default_value *= gain
                if node.type == "BUMP" and not node.inputs["Distance"].is_linked:
                    node.inputs["Distance"].default_value = min(
                        node.inputs["Distance"].default_value, max(0.000025, min(0.00015, length_m * 0.0001)))
        roughness = bsdf.inputs["Roughness"]
        if roughness.is_linked:
            source = roughness.links[0].from_socket
            clamp = tree.nodes.new("ShaderNodeClamp")
            clamp.inputs["Min"].default_value = floor
            clamp.inputs["Max"].default_value = 0.95
            tree.links.new(source, clamp.inputs["Value"])
            tree.links.new(clamp.outputs["Result"], roughness)
        else:
            roughness.default_value = min(0.95, max(floor, roughness.default_value))
        if finish in ("painted", "polymer", "rubber", "wood", "fabric", "concrete"):
            metallic = bsdf.inputs["Metallic"]
            for link in list(metallic.links):
                tree.links.remove(link)
            metallic.default_value = 0.0
        count += 1
    return count

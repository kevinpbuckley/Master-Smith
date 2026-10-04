"""Assemble planned parts into one game-ready asset (inside Blender). No repairs: every part arrives built and
checked; this only places, budgets, bakes and packages.
    blender -b -Y --python assemble.py -- <args.json>
args: {"name", "out_dir", "tri_budget", "engine", "atlas_size", "render_size", "spec", "reference",
       "parts": [{"name", "kind": "code"|"vendor", "glb" | "blend", "yaw", "box_min": [x,y,z], "box_max": [x,y,z],
                  "material": {"color", "metal", "roughness", "glass"}}]}
Frame: +X forward, +Y left, +Z up, metres, origin at the centre of the whole asset."""
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import blib  # noqa: E402
from mastersmith import sculpt  # noqa: E402
import texel  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME = args["name"]
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
report = {"name": NAME, "notes": [], "files": [], "maps": [], "lods": [], "parts": []}


def log(msg):
    print("[assemble] " + msg, flush=True)
    report["notes"].append(msg)


def import_part(p):
    before = set(bpy.data.objects)
    if p.get("blend"):
        with bpy.data.libraries.load(os.path.abspath(p["blend"]), link=False) as (src, dst):
            dst.objects = [n for n in src.objects]
        for o in dst.objects:
            if o is not None and o.type == "MESH":
                bpy.context.collection.objects.link(o)
    else:
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(p["glb"]))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in [o for o in new if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    if not meshes:
        raise RuntimeError("part %s has no mesh" % p["name"])
    blib.select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    o.name = "Part_" + p["name"]
    return o


def fit(o, p):
    """Code parts were built in their box's own frame: moved to the box centre. Vendor parts arrive at their own size,
    long axis along X and upright: turned by the facing yaw, then scaled to fill the box on every side (within 1.8x of
    the median scale) and centred."""
    bmin, bmax = Vector(p["box_min"]), Vector(p["box_max"])
    centre, size = (bmin + bmax) * 0.5, bmax - bmin
    if p["kind"] == "code":
        # a code part's box is its tight bounds: a build that falls short of it on an axis by more than 8% is scaled to
        # fill it (at most 1.5x). The bullpup's barrel was built 7 mm across in a 10.6 mm box, every build (2026-09-27)
        lo_c, hi_c = blib.dims(o)
        ext_c = hi_c - lo_c
        fill = [min(2.0, size[i] / ext_c[i]) if ext_c[i] > 1e-9 and size[i] / ext_c[i] > 1.08 else 1.0 for i in range(3)]
        if p.get("centreline"):
            # a round part scales evenly across its section: stretched one way only, the muzzle brake came out oval
            fill[1] = fill[2] = math.sqrt(fill[1] * fill[2])
        if fill != [1.0, 1.0, 1.0]:
            o.data.transform(Matrix.Translation(-(lo_c + hi_c) * 0.5))
            o.data.transform(Matrix.Diagonal(Vector(fill).to_4d()))
        g = float(p.get("cover") or 1.0)          # grown a little over the vendor body's soft copy of this part
        if g != 1.0:
            o.data.transform(Matrix.Diagonal(Vector((g, g, g, 1.0))))
        o.data.transform(Matrix.Translation(centre))
        return {"scale": g, "filled": [round(v, 3) for v in fill]}
    if p.get("yaw"):
        o.data.transform(Matrix.Rotation(math.radians(float(p["yaw"])), 4, "Z"))
    lo, hi = blib.dims(o)
    ext = hi - lo
    ratios = [size[i] / max(ext[i], 1e-9) for i in range(3)]
    # the box was measured from the same picture the part was drawn from: the part FILLS it on every side, so it meets
    # its neighbours. A uniform fit left the pistol's grip and the shotgun's stock short of the frame and receiver
    # (2026-09-27). A part more than 1.8x out of proportion with its box is kept in proportion on that axis instead.
    s = sorted(ratios)[1]
    scale = [r if r / s <= 1.8 and s / r <= 1.8 else s for r in ratios]
    if p.get("fill_box"):
        scale = list(ratios)                      # a small part: its box, read off the picture, rules on every side
    if p.get("keep_depth"):
        # seeded from a three-quarter picture, the vendor saw the part's real depth: its width keeps the length and
        # height scale instead of being stretched to the planned front span, which counts every protrusion (the
        # bullpup body was squeezed to 76% of its width and was a mess from the front, 2026-09-27)
        scale[1] = math.sqrt(scale[0] * scale[2])
    o.data.transform(Matrix.Translation(-(lo + hi) * 0.5))
    o.data.transform(Matrix.Diagonal(Vector(scale).to_4d()))
    o.data.transform(Matrix.Translation(centre))
    return {"scale": [round(v, 4) for v in scale], "proportion": [round(v / s, 3) for v in scale]}


def weld_seams(o):
    """Merge the copies of each seam vertex (positions identical; UVs and normals are per corner and stay). A Tripo seed
    is split along every UV seam - 10-19k open edges on the Training Pool pilots - and the collapse decimator kept each
    island's rim on its own: the 8k LOD0 of a coral or a kelp came out with ~5,600 open edges, torn leaves and black
    bake holes (2026-10-03). Welded first it decimates as one closed surface. -> vertices merged"""
    lo, hi = blib.dims(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    n = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=max((hi - lo).length * 1e-6, 1e-9))
    merged = n - len(bm.verts)
    if merged:
        bm.to_mesh(o.data)
        o.data.update()
    bm.free()
    return merged


def decimate_to(o, target):
    have = blib.tri_count(o)
    if have <= target:
        return have
    weld_seams(o)
    # each pass takes at most 98%: a 149k conch seed stopped at 2,980 triangles of its 2,000 (2026-10-03), so a
    # second pass takes the rest
    for _ in range(3):
        have = blib.tri_count(o)
        if have <= target * 1.02:
            break
        m = o.modifiers.new("dec", "DECIMATE")
        m.ratio = max(0.02, target / float(have))
        m.use_collapse_triangulate = True
        blib.select_only([o])
        bpy.ops.object.modifier_apply(modifier="dec")
    return blib.tri_count(o)


def surface_area(o):
    return sum(p.area for p in o.data.polygons)


def add_reference_detail(o, det):
    """Project the reference's fine detail (a grey high-pass map, 0.5 = none) onto a code part's materials, from the
    side picture on faces that look sideways and the front picture on faces that look forward: it darkens and lightens
    the base colour and drives a bump, so the colour and normal bakes both carry it. Parts sit in the asset frame
    (identity transforms), the frame the plan's pictures were cropped to."""
    L_, W_, H_ = (float(v) for v in det["dims"])
    s = float(det.get("strength", 0.6))
    images = {}
    for view in ("side", "front"):
        if det.get(view) and os.path.exists(det[view]):
            img = bpy.data.images.load(os.path.abspath(det[view]), check_existing=True)
            img.colorspace_settings.name = "Non-Color"
            images[view] = img
    if "side" not in images:
        return False
    # the part's own materials: a `mats` here read the script-level loop variable of the zone pass, so assembly
    # crashed on a job with no zoned vendor part and put the detail on another part's zone otherwise (2026-09-29)
    for m in {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree}:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        N, K = t.nodes, t.links

        def op(kind, a, c=None):
            n = N.new("ShaderNodeMath")
            n.operation = kind
            for i, v in enumerate((a, c)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    n.inputs[i].default_value = float(v)
                else:
                    K.new(v, n.inputs[i])
            return n.outputs[0]
        geo = N.new("ShaderNodeNewGeometry")
        pos = N.new("ShaderNodeSeparateXYZ")
        nrm = N.new("ShaderNodeSeparateXYZ")
        K.new(geo.outputs["Position"], pos.inputs[0])
        K.new(geo.outputs["Normal"], nrm.inputs[0])

        def look(img, u_sock, u_len):
            uv = N.new("ShaderNodeCombineXYZ")
            K.new(op("ADD", op("DIVIDE", u_sock, u_len), 0.5), uv.inputs[0])
            K.new(op("ADD", op("DIVIDE", pos.outputs["Z"], H_), 0.5), uv.inputs[1])
            tex = N.new("ShaderNodeTexImage")
            tex.image = img
            tex.extension = "EXTEND"
            K.new(uv.outputs[0], tex.inputs["Vector"])
            return op("SUBTRACT", tex.outputs["Color"], 0.5)
        term = op("MULTIPLY", look(images["side"], pos.outputs["X"], L_), op("MULTIPLY", nrm.outputs["Y"], nrm.outputs["Y"]))
        if "front" in images:
            term = op("ADD", term, op("MULTIPLY", look(images["front"], pos.outputs["Y"], W_),
                                      op("MULTIPLY", nrm.outputs["X"], nrm.outputs["X"])))
        base = b.inputs["Base Color"]
        if base.is_linked:
            src = base.links[0].from_socket
        else:
            rgb = N.new("ShaderNodeRGB")
            rgb.outputs[0].default_value = tuple(base.default_value)
            src = rgb.outputs[0]
        scale = N.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        K.new(src, scale.inputs[0])
        K.new(op("ADD", op("MULTIPLY", term, 2.0 * s), 1.0), scale.inputs["Scale"])
        K.new(scale.outputs["Vector"], base)
        if not b.inputs["Normal"].is_linked:
            bump = N.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = min(1.0, 0.5 * s)
            bump.inputs["Distance"].default_value = 0.0006
            K.new(term, bump.inputs["Height"])
            K.new(bump.outputs["Normal"], b.inputs["Normal"])
    return True


# the plan's colour in linear RGB, floored, a dark metal lifted to its reflectance: shared with build_part.py, tested
from colour import METAL_MIN_REFLECTANCE, planned_linear  # noqa: E402,F401


def image_mean_luminance(img):
    """Mean linear luminance of an image's opaque texels, on a subsample."""
    w, h = img.size
    if not w or not h:
        return None
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(-1, 4)[:: max(1, (w * h) // 65536)]
    a = a[a[:, 3] > 0.5] if (a[:, 3] > 0.5).any() else a
    if img.colorspace_settings.name == "sRGB":
        rgb = np.where(a[:, :3] <= 0.04045, a[:, :3] / 12.92, ((a[:, :3] + 0.055) / 1.055) ** 2.4)
    else:
        rgb = a[:, :3]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    # a mesher's atlas is mostly black padding: the mean over the whole image read 0.04 for a mid-grey receiver and
    # the brightness correction pushed its texels to white (2026-09-28). Only texels with some light count.
    used = lum[lum > 0.004]
    return float(used.mean()) if len(used) > 100 else float(lum.mean())


def tint_to_plan(o, colour, mats=None, metal=False, luminance_only=False, force=False, flat=False):
    """A vendor part takes its planned colour, keeping its own light and dark variation: base colour = planned colour x
    (texel luminance / the texture's mean luminance), clamped. Tripo keeps a washed-out grey where the plan says matte
    black (the pistol frame, 2026-09-27); this is the part's material being set as planned while it is assembled, the
    shape and the texture's detail are the vendor's."""
    lin = planned_linear(colour, metal)
    if lin is None:
        return False
    done = False
    for m in (mats if mats is not None else {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree}):
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        base = b.inputs["Base Color"]
        rgb = t.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = (*lin, 1.0)
        if not base.is_linked or flat:
            # flat (2026-09-30): a face the mesher textured wrong takes the planned colour alone (a seed with no back
            # view printed its glowing muzzle onto the rear cap; tinting kept the lightning lines at +-50%)
            t.links.new(rgb.outputs[0], base)
            done = True
            continue
        src = base.links[0].from_socket
        img, todo, seen = None, [src.node], set()
        while todo and img is None:                        # the image upstream of the base colour
            n = todo.pop()
            if n.name in seen:
                continue
            seen.add(n.name)
            if n.type == "TEX_IMAGE" and n.image:
                img = n.image
            todo.extend(l.from_node for i in n.inputs for l in i.links)
        mean = image_mean_luminance(img) if img is not None else None
        if not mean or mean <= 1e-4:
            continue
        want = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        if luminance_only:
            # a kept texture (its own colours are right, e.g. an olive panel on a grey body) is only brought to the
            # picture's brightness: a part drawn alone on white came out near-white (2026-09-28)
            k = max(0.25, min(4.0, want / max(mean, 1e-4)))
            if 0.85 <= k <= 1.18:
                t.nodes.remove(rgb)
                continue
            scale = t.nodes.new("ShaderNodeVectorMath")
            scale.operation = "SCALE"
            K_ = t.links
            K_.new(src, scale.inputs[0])
            scale.inputs["Scale"].default_value = k
            for l in list(base.links):
                t.links.remove(l)
            K_.new(scale.outputs["Vector"], base)
            t.nodes.remove(rgb)
            done = True
            continue
        if not force and 0.7 <= mean / max(want, 1e-4) <= 1.4:
            # the vendor's texture is already about the planned tone: keep it, with its own colour separation (the
            # TRELLIS pistol's black slide against its frame, its stippled grip) - the tint is for washed-out seeds
            # like Tripo's grey frame
            t.nodes.remove(rgb)
            continue
        bw = t.nodes.new("ShaderNodeRGBToBW")
        t.links.new(src, bw.inputs[0])
        ratio = t.nodes.new("ShaderNodeMath")
        ratio.operation = "DIVIDE"
        t.links.new(bw.outputs[0], ratio.inputs[0])
        ratio.inputs[1].default_value = mean
        clamp = t.nodes.new("ShaderNodeMapRange")          # keep the detail, not the vendor's blown highlights
        clamp.clamp = True
        clamp.inputs["From Min"].default_value = 0.0
        clamp.inputs["From Max"].default_value = 2.0
        clamp.inputs["To Min"].default_value = 0.0
        clamp.inputs["To Max"].default_value = 2.0
        t.links.new(ratio.outputs[0], clamp.inputs["Value"])
        soft = t.nodes.new("ShaderNodeMath")               # halve the swing: 0.5 + 0.5 x ratio, 0.5..1.5
        soft.operation = "MULTIPLY_ADD"
        t.links.new(clamp.outputs["Result"], soft.inputs[0])
        soft.inputs[1].default_value = 0.5
        soft.inputs[2].default_value = 0.5
        scale = t.nodes.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        t.links.new(rgb.outputs[0], scale.inputs[0])
        t.links.new(soft.outputs[0], scale.inputs["Scale"])
        t.links.new(scale.outputs["Vector"], base)
        done = True
    return done


def surface_detail(o, mat, strength=1.0, mats=None, vendor=False):
    """The material pass a texture artist gives a moulded or cast part, on a vendor seed before the bake: worn, lighter
    raised edges and darker recesses from the mesh's curvature (Cycles pointiness on the full-detail seed), a fine grain
    in the normal, and roughness that varies with it and polishes on the worn edges. A vendor's texture alone read as
    soft grey plastic on the bullpup (owner, 2026-09-27). Everything is procedural in object space, so it bakes into
    the atlas like the seed's own texture."""
    metal = bool(mat.get("metal"))
    finish = mat.get("finish") or ("metal" if metal else "polymer")
    rubber = finish == "rubber"
    # a mesher's surface is bumpy everywhere, so curvature finds "edges" all over it: a vendor part gets a tenth of
    # the wear a clean code part gets and a quarter of the grime (a third and 0.6 still mottled the bullpup's polymer
    # receiver like grey stone, owner 2026-09-29; white flecks over the pistol's slide, 2026-09-28)
    wear_k = 0.1 if vendor else 1.0
    grime_k = 0.25 if vendor else 1.0
    # the noise sizes were set on a 0.84 m rifle: on a 14 m aircraft its grime was invisible (Tonetta scales wear with
    # the asset's length, 2026-09-29), so they grow with the asset
    size_k = min(1.2, max(0.06, 0.84 / max(float(args.get("length_m") or 0.84), 1e-3)))
    for m in (mats if mats is not None else {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree}):
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        N, K = t.nodes, t.links
        geo = N.new("ShaderNodeNewGeometry")
        coord = N.new("ShaderNodeTexCoord")
        # curvature: pointiness is ~0.5 on flat areas, higher on convex edges, lower in concave recesses
        edge = N.new("ShaderNodeMapRange")
        edge.inputs["From Min"].default_value = 0.52       # a dense seed's curvature sits close to 0.5: only the
        edge.inputs["From Max"].default_value = 0.57       # sharpest edges wear (0.505 turned the whole body chalky)
        K.new(geo.outputs["Pointiness"], edge.inputs["Value"])
        cavity = N.new("ShaderNodeMapRange")
        cavity.inputs["From Min"].default_value = 0.485
        cavity.inputs["From Max"].default_value = 0.44
        K.new(geo.outputs["Pointiness"], cavity.inputs["Value"])
        # a broken-up wear mask: edges wear unevenly
        wear_noise = N.new("ShaderNodeTexNoise")
        wear_noise.inputs["Scale"].default_value = 60.0 * size_k
        wear_noise.inputs["Detail"].default_value = 8.0
        K.new(coord.outputs["Object"], wear_noise.inputs["Vector"])
        patches = N.new("ShaderNodeMapRange")           # wear in broken patches, not along every edge
        patches.inputs["From Min"].default_value = 0.48
        patches.inputs["From Max"].default_value = 0.66
        K.new(wear_noise.outputs["Fac"], patches.inputs["Value"])
        wear = N.new("ShaderNodeMath")
        wear.operation = "MULTIPLY"
        wear.use_clamp = True
        K.new(edge.outputs["Result"], wear.inputs[0])
        K.new(patches.outputs["Result"], wear.inputs[1])
        wear2 = N.new("ShaderNodeMath")
        wear2.operation = "MULTIPLY"
        wear2.use_clamp = True
        K.new(wear.outputs[0], wear2.inputs[0])
        wear2.inputs[1].default_value = 0.8 * strength * wear_k
        # base colour: lighter on the worn edges, darker in the recesses
        base = b.inputs["Base Color"]
        if base.is_linked:
            src = base.links[0].from_socket
        else:
            rgb = N.new("ShaderNodeRGB")
            rgb.outputs[0].default_value = tuple(base.default_value)
            src = rgb.outputs[0]
        lighten = N.new("ShaderNodeMix")
        lighten.data_type = "RGBA"
        lighten.blend_type = "SCREEN"
        K.new(wear2.outputs[0], lighten.inputs["Factor"])
        K.new(src, lighten.inputs["A"])
        # worn metal edges: a dull lighter steel, not silver - 0.50 over a crinkly seed's many "edges" read as white
        # flecks on the muzzle brake and rails (2026-09-28)
        lighten.inputs["B"].default_value = (0.34, 0.34, 0.32, 1.0) if metal else (0.26, 0.26, 0.25, 1.0)
        grime = N.new("ShaderNodeMix")
        grime.data_type = "RGBA"
        grime.blend_type = "MULTIPLY"
        gf = N.new("ShaderNodeMath")
        gf.operation = "MULTIPLY"
        gf.use_clamp = True
        K.new(cavity.outputs["Result"], gf.inputs[0])
        gf.inputs[1].default_value = 0.55 * strength * grime_k
        K.new(gf.outputs[0], grime.inputs["Factor"])
        K.new(lighten.outputs["Result"], grime.inputs["A"])
        grime.inputs["B"].default_value = (0.45, 0.44, 0.43, 1.0)
        K.new(grime.outputs["Result"], base)
        # fine grain in the normal (polymer texture / cast or machined metal), chained onto any normal map the seed has
        grain = N.new("ShaderNodeTexNoise")
        grain.inputs["Scale"].default_value = (1600.0 if rubber else 900.0 if not metal else 2500.0) * size_k
        grain.inputs["Detail"].default_value = 4.0
        if metal:
            # brushed: a fine grain drawn out along the part's length, 6x not 20x (20x made 14 mm stripes over a
            # pistol slide, 2026-09-28)
            stretch = N.new("ShaderNodeMapping")
            stretch.inputs["Scale"].default_value = (0.16, 1.0, 1.0)
            K.new(coord.outputs["Object"], stretch.inputs["Vector"])
            K.new(stretch.outputs["Vector"], grain.inputs["Vector"])
        else:
            K.new(coord.outputs["Object"], grain.inputs["Vector"])
        bump = N.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = (0.7 if rubber else 0.12 if metal else 0.35) * strength
        bump.inputs["Distance"].default_value = 0.001
        K.new(grain.outputs["Fac"], bump.inputs["Height"])
        nrm = b.inputs["Normal"]
        if nrm.is_linked:
            K.new(nrm.links[0].from_socket, bump.inputs["Normal"])
        K.new(bump.outputs["Normal"], nrm)
        # roughness: varied by the grain, polished where the edges are worn
        rough = b.inputs["Roughness"]
        r_src = rough.links[0].from_socket if rough.is_linked else None
        r_base = float(mat.get("roughness", rough.default_value if not rough.is_linked else 0.6))
        if rubber:
            r_base = max(r_base, 0.85)                 # rubber: dead matte
        elif metal:
            r_base = min(r_base, 0.4)                  # bare metal: a real sheen
        var = N.new("ShaderNodeMapRange")
        var.inputs["To Min"].default_value = max(0.05, r_base - 0.12)
        var.inputs["To Max"].default_value = min(1.0, r_base + 0.08)
        K.new(wear_noise.outputs["Fac"], var.inputs["Value"])
        if r_src is not None:
            avg = N.new("ShaderNodeMix")
            avg.data_type = "FLOAT"
            avg.inputs["Factor"].default_value = 0.5
            K.new(r_src, avg.inputs["A"])
            K.new(var.outputs["Result"], avg.inputs["B"])
            r_out = avg.outputs["Result"]
        else:
            r_out = var.outputs["Result"]
        polish = N.new("ShaderNodeMix")
        polish.data_type = "FLOAT"
        K.new(wear2.outputs[0], polish.inputs["Factor"])
        K.new(r_out, polish.inputs["A"])
        polish.inputs["B"].default_value = r_base if rubber else max(0.05, r_base - 0.35)   # rubber does not polish
        K.new(polish.outputs["Result"], rough)
    return True


def split_zones(o, zones):
    """A vendor part's material zones (plan: a rubber grip, bare steel, a coloured panel) as material slots of their
    own: the faces whose centre lies in a zone's box get a copy of their material. -> [(zone, set of materials)], in
    plan order; a later zone wins where two overlap. One material for a whole body read as graphite (2026-09-28)."""
    if not zones:
        return []
    me = o.data
    n = len(me.polygons)
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    idx = np.empty(n, np.int32)
    me.polygons.foreach_get("material_index", idx)
    if not o.material_slots:
        return []
    base = [sl.material for sl in o.material_slots]
    out = []
    # face adjacency (shared vertices), to smooth a zone's ragged box edge by neighbour majority. Built in numpy
    # (Blender's Python has no scipy): every pair of faces meeting at a vertex, made unique, then a vote is a
    # bincount instead of a Python loop over 150k faces (issue #6).
    loop_total = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_vert = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", loop_vert)
    face_of_loop = np.repeat(np.arange(n, dtype=np.int64), loop_total)
    order = np.argsort(loop_vert, kind="stable")
    fs = face_of_loop[order]                          # faces grouped by the vertex they meet at
    _, start, k = np.unique(loop_vert[order], return_index=True, return_counts=True)
    k_e = np.repeat(k, k)                             # each corner's group size
    start_e = np.repeat(start, k)
    rep = np.repeat(np.arange(len(fs)), k_e)          # each corner repeated once per face in its group
    within = np.arange(len(rep)) - np.repeat(np.cumsum(k_e) - k_e, k_e)
    pairs = np.unique(fs[rep] * n + fs[np.repeat(start_e, k_e) + within])
    face_a, face_b = pairs // n, pairs % n
    degree = np.bincount(face_a, minlength=n).astype(np.float32)
    seg = segment_labels(o)
    for z in zones:
        lo, hi = np.array(z["box_min"]), np.array(z["box_max"])
        inside = np.all((centres >= lo) & (centres <= hi), axis=1)
        if z.get("segment") is not None:
            # 2026-10-04: a zone named by the segmentation's labels (ms segment; the ms_segment face attribute)
            # instead of a box: exactly the labelled faces, inside the box only when the plan gave one
            want = segment_mask(seg, z["segment"], n)
            inside = (inside & want) if z.get("box_given") else want
        else:
            for _ in range(2):
                votes = np.bincount(face_a, weights=inside[face_b].astype(np.float32), minlength=n) / np.maximum(degree, 1.0)
                inside = votes > 0.5
        log("zone %s: %d faces%s" % (z.get("name"), int(inside.sum()),
                                      " by segment %s" % z["segment"] if z.get("segment") is not None else ""))
        if inside.sum() < 20:
            continue
        made = {}
        for src in sorted(set(idx[inside])):
            if src >= len(base) or base[src] is None:
                continue
            m = base[src].copy()
            m.name = "%s_zone_%s" % (base[src].name, z.get("name", "zone"))
            me.materials.append(m)
            made[src] = len(me.materials) - 1
        for src, dst in made.items():
            sel = inside & (idx == src)
            idx[sel] = dst
        out.append((z, {me.materials[d] for d in made.values()}))
    me.polygons.foreach_set("material_index", idx)
    me.update()
    return out


def glass_zone(mats):
    """A vendor body's window or canopy area as smoked glass in the baked atlas: the vendor's own colour darkened and
    desaturated, no roughness or metal, a mirror-smooth finish. The atlas cannot carry transparency, so this is the
    look of tinted glass seen from outside (the aircraft skill's rule)."""
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        base = b.inputs["Base Color"]
        if base.is_linked:
            src = base.links[0].from_socket
            hsv = t.nodes.new("ShaderNodeHueSaturation")
            hsv.inputs["Saturation"].default_value = 0.5
            hsv.inputs["Value"].default_value = 0.45
            t.links.new(src, hsv.inputs["Color"])
            t.links.new(hsv.outputs["Color"], base)
        else:
            base.default_value = (0.05, 0.07, 0.09, 1.0)
        for name, v in (("Roughness", 0.05), ("Metallic", 0.0)):
            inp = b.inputs[name]
            for l in list(inp.links):
                t.links.remove(l)
            inp.default_value = v
        if "Specular IOR Level" in b.inputs:
            b.inputs["Specular IOR Level"].default_value = 0.8


def smart_material(o, pbr, mats, length_m):
    """A CC0 surface set (issue #15) layered over whatever the material has: the set's colour supplies only its light
    and dark variation (the planned colour stays), its roughness varies ours, its displacement drives a fine bump
    chained onto any normal map, and ambient occlusion puts dirt in the cavities and at the joins. Tri-planar in
    object space at the set's real-world tile size, so it bakes into the atlas like everything else."""
    maps, tile = pbr["maps"], float(pbr["tile_m"])
    done = 0
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None or m.get("ms_glass"):
            continue
        N, K = t.nodes, t.links
        coord = N.new("ShaderNodeTexCoord")
        mapping = N.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (1.0 / tile,) * 3
        K.new(coord.outputs["Object"], mapping.inputs["Vector"])

        def tex(role, colour):
            img = bpy.data.images.load(os.path.abspath(maps[role]), check_existing=True)
            img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
            n = N.new("ShaderNodeTexImage")
            n.image = img
            n.projection = "BOX"
            n.projection_blend = 0.3
            K.new(mapping.outputs["Vector"], n.inputs["Vector"])
            return n

        def op(kind, a, c=None, clamp=False):
            n = N.new("ShaderNodeMath")
            n.operation = kind
            n.use_clamp = clamp
            for i, v in enumerate((a, c)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    n.inputs[i].default_value = float(v)
                else:
                    K.new(v, n.inputs[i])
            return n.outputs[0]
        # colour: the set's light-and-dark over the planned colour, damped
        col = tex("color", True)
        mean = image_mean_luminance(col.image) or 0.5
        bw = N.new("ShaderNodeRGBToBW")
        K.new(col.outputs["Color"], bw.inputs[0])
        var = N.new("ShaderNodeMapRange")
        var.clamp = True
        var.inputs["From Min"].default_value = 0.0
        var.inputs["From Max"].default_value = 2.0 * mean
        # a set's own highlights (brushed-steel scratches) over the wear pass's lighter edges read as white flecks on
        # the muzzle brake and rails (2026-09-28): the variation is damped, most on metal
        spread = float(pbr.get("colour_var", 0.3))
        var.inputs["To Min"].default_value = 1.0 - spread
        var.inputs["To Max"].default_value = 1.0 + spread
        K.new(bw.outputs[0], var.inputs["Value"])
        base = b.inputs["Base Color"]
        if base.is_linked:
            src = base.links[0].from_socket
        else:
            rgb = N.new("ShaderNodeRGB")
            rgb.outputs[0].default_value = tuple(base.default_value)
            src = rgb.outputs[0]
        scale = N.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        K.new(src, scale.inputs[0])
        K.new(var.outputs["Result"], scale.inputs["Scale"])
        # cavity dirt from ambient occlusion: darker and rougher in recesses and at the joins between parts
        ao = N.new("ShaderNodeAmbientOcclusion")
        ao.samples = 8
        ao.inputs["Distance"].default_value = max(0.004, 0.015 * length_m)
        dirt = N.new("ShaderNodeMapRange")
        dirt.clamp = True
        dirt.inputs["From Min"].default_value = 0.92
        dirt.inputs["From Max"].default_value = 0.5
        dirt.inputs["To Max"].default_value = float(pbr.get("dirt", 0.3))
        K.new(ao.outputs["AO"], dirt.inputs["Value"])
        grime = N.new("ShaderNodeMix")
        grime.data_type = "RGBA"
        grime.blend_type = "MULTIPLY"
        K.new(dirt.outputs["Result"], grime.inputs["Factor"])
        K.new(scale.outputs["Vector"], grime.inputs["A"])
        grime.inputs["B"].default_value = (0.42, 0.40, 0.38, 1.0)
        for l in list(base.links):
            K.remove(l)
        K.new(grime.outputs["Result"], base)
        # roughness: ours, varied by the set's, rougher in the dirt
        rough = b.inputs["Roughness"]
        r_src = rough.links[0].from_socket if rough.is_linked else None
        r_tex = tex("roughness", False)
        r_var = op("MULTIPLY", op("SUBTRACT", r_tex.outputs["Color"], 0.5), float(pbr.get("rough_var", 0.4)))
        r_in = r_src if r_src is not None else float(rough.default_value)
        r_out = op("ADD", op("ADD", r_in, r_var), op("MULTIPLY", dirt.outputs["Result"], 0.3), clamp=True)
        for l in list(rough.links):
            K.remove(l)
        K.new(r_out, rough)
        # bump from the set's displacement, chained onto whatever normal the material already has
        if maps.get("displacement"):
            d_tex = tex("displacement", False)
            bump = N.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = float(pbr.get("bump", 0.3))
            bump.inputs["Distance"].default_value = 0.0004
            K.new(d_tex.outputs["Color"], bump.inputs["Height"])
            nrm = b.inputs["Normal"]
            if nrm.is_linked:
                K.new(nrm.links[0].from_socket, bump.inputs["Normal"])
                for l in list(nrm.links):
                    if l.to_node is not bump:
                        K.remove(l)
            K.new(bump.outputs["Normal"], nrm)
        done += 1
    return done


def surface_to_plan(o, mat, mats=None):
    """A vendor part takes its planned roughness and metalness too: Tripo's maps made the bullpup's polymer body shine
    like metal (2026-09-27). The texture's roughness variation is kept, squeezed into planned +-0.1."""
    if "roughness" not in mat and "metal" not in mat:
        return False
    for m in (mats if mats is not None else {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree}):
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        if "metal" in mat:
            for l in list(b.inputs["Metallic"].links):
                t.links.remove(l)
            b.inputs["Metallic"].default_value = 1.0 if mat.get("metal") else 0.0
        if "roughness" in mat:
            r = min(1.0, max(0.05, float(mat["roughness"])))
            inp = b.inputs["Roughness"]
            if inp.is_linked:
                src = inp.links[0].from_socket
                mr = t.nodes.new("ShaderNodeMapRange")
                mr.clamp = True
                mr.inputs["To Min"].default_value = max(0.05, r - 0.1)
                mr.inputs["To Max"].default_value = min(1.0, r + 0.1)
                t.links.new(src, mr.inputs["Value"])
                t.links.new(mr.outputs["Result"], inp)
            else:
                inp.default_value = r
    return True


def edge_break(o, width):
    """A machined part's edges broken the way a real one's are: a small two-segment round on every edge sharper than
    30 degrees, the flat faces kept flat (hardened normals). A code part's razor edges and flat shading read as
    CG next to the diffused parts (owner, 2026-09-29: "too rigid ... too sharp edges"). -> width in mm, or None"""
    lo, hi = blib.dims(o)
    thin = min(v for v in (hi - lo) if v > 1e-9) if max(hi - lo) > 1e-9 else 0.0
    w = min(float(width), 0.06 * thin)
    if w <= 1e-6 or not o.data.polygons:
        return None
    o.data.polygons.foreach_set("use_smooth", [True] * len(o.data.polygons))
    m = o.modifiers.new("edge_break", "BEVEL")
    m.width = w
    m.segments = 2
    m.profile = 0.6
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(30)
    m.use_clamp_overlap = True
    m.harden_normals = True
    m.miter_outer = "MITER_ARC"
    blib.select_only([o])
    try:
        bpy.ops.object.modifier_apply(modifier=m.name)
    except RuntimeError as exc:
        o.modifiers.remove(m)
        log("%s: edge break skipped (%s)" % (o.name, str(exc)[:80]))
        return None
    return round(w * 1000, 2)


def skin_from_seed(o, p, res=1024):
    """A code part dressed in a diffusion texture: the part's own picture meshed by the vendor (parts/<Part>/
    registered.blend, `ms mesh`), fitted to the same box, and its colour baked onto the code geometry, which keeps its
    exact shape. The assembly then reads as one kind of surface instead of textured vendor parts beside flat code
    parts (owner, 2026-09-29). Texels no ray reached take the mean colour; the colour is then tinted to the plan like
    a vendor part's. -> {"coverage"} or None"""
    sp = dict(p, kind="vendor", fill_box=True, keep_depth=False, yaw=0, blend=p["skin"], centreline=False)
    s = import_part(sp)
    s.name = "Skin_" + p["name"]
    fit(s, sp)
    while o.data.uv_layers:
        o.data.uv_layers.remove(o.data.uv_layers[0])
    blib.select_only([o])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    o.data.uv_layers[0].name = "UVMap"
    img = bpy.data.images.new("T_skin_%s" % p["name"], res, res, alpha=False, float_buffer=False)
    mats = [sl.material for sl in o.material_slots if sl.material and sl.material.node_tree]
    if not mats:
        bpy.data.objects.remove(s, do_unlink=True)
        return None
    nodes = []
    for m in mats:
        n = m.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        m.node_tree.nodes.active = n
        nodes.append((m, n))
    for sl in s.material_slots:                         # the seed's base colour, emitted, is what the bake reads
        m = sl.material
        if not m or not m.node_tree:
            continue
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next((n for n in t.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if b is None or out is None:
            continue
        em = t.nodes.new("ShaderNodeEmission")
        base = b.inputs["Base Color"]
        if base.is_linked:
            t.links.new(base.links[0].from_socket, em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = base.default_value
        t.links.new(em.outputs[0], out.inputs["Surface"])
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 1
    lo, hi = blib.dims(o)
    diag = (hi - lo).length
    blib.select_only([s, o])
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, cage_extrusion=diag * 0.03, max_ray_distance=diag * 0.08,
                        margin=8, use_clear=True, target="IMAGE_TEXTURES")
    bpy.data.objects.remove(s, do_unlink=True)
    px = np.empty(res * res * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    hit = px[:, :3].max(axis=1) > 1e-4
    if hit.mean() < 0.01:
        for m, n in nodes:
            m.node_tree.nodes.remove(n)
        log("%s: skin bake reached nothing; left as built" % p["name"])
        return None
    px[~hit, :3] = px[hit, :3].mean(axis=0)
    img.pixels.foreach_set(px.ravel())
    img.pack()
    for m, n in nodes:
        b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if b is not None:
            for l in list(b.inputs["Base Color"].links):
                m.node_tree.links.remove(l)
            m.node_tree.links.new(n.outputs["Color"], b.inputs["Base Color"])
    pm = p.get("material") or {}
    tint_to_plan(o, pm.get("color"), set(mats), metal=bool(pm.get("metal")), force=True)
    return {"coverage": round(float(hit.mean()), 3)}


LENGTH_M = float(args.get("length_m") or 1.0)
EMISSIVE = {"strength": 0.0}


import muzzle as muzzlekit  # noqa: E402 - the open bores end-on (pure numpy, tested)
from glasskit import crease_bars, rim_band, segment_labels, segment_mask, smooth_rim  # noqa: E402
from glasskit import (  # noqa: E402 - the glass and cockpit passes, shared with cabin.py
    base_image, face_rgb, face_pairs, components, mesh_tree, escapes,
    exterior_faces, canopy_hull, glass_shell, pane_object, glass_paint, pick_glass,
    cut_out, line_interior, interior_material, glass_material, delete_faces, cockpit_contents)


def zone_glass_kw(z):
    """A glass zone's own pane, when its plan material sets "alpha" (materials.md's table: tinted or armoured glass
    is near-black at 0.55): the material's colour as the tint (no albedo floor: glass is darker than paint), its
    alpha and its roughness. {} means the default canopy glass. 2026-10-04: the owner asked for a canopy dark enough
    not to see inside, and the pane's tint and alpha were fixed in glass_material."""
    zm = z.get("material") or {}
    a = zm.get("alpha")
    if not isinstance(a, (int, float)) or isinstance(a, bool):
        return {}
    kw = {"alpha": float(a), "rough": float(zm.get("roughness", 0.05))}
    h = str(zm.get("color") or "").lstrip("#")
    if len(h) == 6 and h.lower() != "808080":
        from colour import srgb_to_linear
        kw["tint"] = tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))
    return kw


def zone_glass_material(zname, kw):
    """The glass material for a zone: the asset's one pane when `kw` is empty, else a pane of its own named for it."""
    return glass_material("MI_%s_Glass" % NAME) if not kw else glass_material("MI_%s_Glass_%s" % (NAME, zname), **kw)


def lift_roughness(mats, floor=0.35, trigger=0.40):
    """A kept texture's roughness brought off glaze: when its mean is under 0.40 it becomes 0.35 + 0.65 r (Tonetta's
    seed pass; Tripo seeds measured 0.17-0.27 and read as glazed plastic, 2026-09-29). -> the means it found"""
    found = []
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        inp = b.inputs["Roughness"]
        if not inp.is_linked:
            if inp.default_value < trigger:
                found.append(round(float(inp.default_value), 3))
                inp.default_value = floor + (1 - floor) * inp.default_value
            continue
        src = inp.links[0].from_socket
        node, chan = src.node, None
        if node.type in ("SEPARATE_COLOR", "SEPRGB"):
            chan = {"Red": 0, "R": 0, "Green": 1, "G": 1, "Blue": 2, "B": 2}.get(src.name, 1)
            node = node.inputs[0].links[0].from_node if node.inputs[0].is_linked else None
        if node is None or node.type != "TEX_IMAGE" or node.image is None or not node.image.size[0]:
            continue
        w, h = node.image.size
        px = np.empty(w * h * 4, np.float32)
        node.image.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[::7]
        mean = float(px[:, chan].mean() if chan is not None else px[:, :3].mean())
        found.append(round(mean, 3))
        if mean < trigger:
            mr = t.nodes.new("ShaderNodeMapRange")
            mr.inputs["To Min"].default_value = floor
            mr.inputs["To Max"].default_value = 1.0
            t.links.new(src, mr.inputs["Value"])
            t.links.new(mr.outputs["Result"], inp)
    return found


def image_mean_rgb(img):
    """(mean linear RGB, mean sRGB chroma) of an image's used texels (an atlas's black padding left out), on a
    subsample, or None."""
    w, h = img.size
    if not w or not h:
        return None
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    s = a.reshape(-1, 4)[:: max(1, (w * h) // 65536), :3]
    lin = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4) if img.colorspace_settings.name == "sRGB" else s
    keep = (lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)) > 0.004
    if keep.sum() <= 100:
        return None
    return lin[keep].mean(axis=0), float((s[keep].max(axis=1) - s[keep].min(axis=1)).mean())


def grade_to_picture(mats, picture, limit=1.33):
    """A kept texture's overall colour cast pulled towards the approved picture's: its saturation scaled to the
    picture's mean chroma (only down, to at least half), then per-channel gains that bring its mean chromaticity onto
    the picture's, its luminance kept, clamped to +-33%. With the projection only in the lettering boxes (2026-10-02)
    the M4A1's Tripo receiver came back olive where the picture is black; the per-pixel projection had been hiding
    that cast, and printing pale patches and white marks elsewhere. -> {"saturation", "gains"} or None"""
    if not picture or len(picture) < 3:
        return None
    p = np.asarray(picture[:3], np.float64)
    p_chroma = float(picture[3]) if len(picture) > 3 else None
    lumw = np.array([0.2126, 0.7152, 0.0722])
    done = None
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None or not b.inputs["Base Color"].is_linked or "_zone_" in m.name:
            continue
        src = b.inputs["Base Color"].links[0].from_socket
        img, todo, seen = None, [src.node], set()
        while todo and img is None:
            nd = todo.pop()
            if nd.name in seen:
                continue
            seen.add(nd.name)
            if nd.type == "TEX_IMAGE" and nd.image:
                img = nd.image
            todo.extend(l.from_node for i in nd.inputs for l in i.links)
        stats = image_mean_rgb(img) if img is not None else None
        if stats is None or p @ lumw <= 1e-4 or stats[0] @ lumw <= 1e-4:
            continue
        tex, t_chroma = stats
        sat = 1.0
        if p_chroma is not None and t_chroma > 1e-4:
            sat = float(np.clip(p_chroma / t_chroma, 0.5, 1.0))
        gain = (p / (p @ lumw)) / np.maximum(tex / (tex @ lumw), 1e-4)
        gain = np.clip(gain, 1.0 / limit, limit)
        gain /= ((gain * tex) @ lumw) / (tex @ lumw)          # the texture's own brightness kept
        if np.abs(gain - 1.0).max() < 0.03 and sat > 0.95:
            continue
        out = src
        if sat <= 0.95:
            hs = t.nodes.new("ShaderNodeHueSaturation")
            hs.inputs["Saturation"].default_value = sat
            t.links.new(out, hs.inputs["Color"])
            out = hs.outputs["Color"]
        if np.abs(gain - 1.0).max() >= 0.03:
            mul = t.nodes.new("ShaderNodeVectorMath")
            mul.operation = "MULTIPLY"
            mul.inputs[1].default_value = tuple(float(g) for g in gain)
            t.links.new(out, mul.inputs[0])
            out = mul.outputs[0]
        t.links.new(out, b.inputs["Base Color"])
        done = {"saturation": round(sat, 3), "gains": [round(float(g), 3) for g in gain],
                "chroma": [round(t_chroma, 4), round(p_chroma, 4) if p_chroma is not None else None]}
    return done


def glow_emission(mats, glow):
    """Emission = the material's own base colour where its hue is within hue_tol of the glow's and it is saturated and
    bright enough, black elsewhere (soft edges). The bake of T_<Name>_E then carries just the glowing texels.
    -> {"hue", "materials"}"""
    h0 = float(glow["hue"]) / 360.0
    tol = float(glow.get("hue_tol", 20.0)) / 360.0
    smin, vmin = float(glow.get("min_sat", 0.35)), float(glow.get("min_val", 0.35))
    done = 0
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None or not b.inputs["Base Color"].is_linked:
            continue
        colour = b.inputs["Base Color"].links[0].from_socket
        hsv = t.nodes.new("ShaderNodeSeparateColor")
        hsv.mode = "HSV"
        t.links.new(colour, hsv.inputs["Color"])

        def math(op, a, bval=None):
            n = t.nodes.new("ShaderNodeMath")
            n.operation = op
            for i, v in enumerate((a, bval)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    n.inputs[i].default_value = v
                else:
                    t.links.new(v, n.inputs[i])
            return n.outputs[0]

        def ramp(v, lo, hi, rising=True):
            n = t.nodes.new("ShaderNodeMapRange")
            n.clamp = True
            t.links.new(v, n.inputs["Value"])
            n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = lo, hi
            n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = (0.0, 1.0) if rising else (1.0, 0.0)
            return n.outputs[0]

        d = math("ABSOLUTE", math("SUBTRACT", hsv.outputs["Red"], h0))
        d = math("MINIMUM", d, math("SUBTRACT", 1.0, d))          # the hue circle wraps at red
        mask = math("MULTIPLY", ramp(d, tol * 0.5, tol, rising=False), ramp(hsv.outputs["Green"], smin * 0.7, smin))
        mask = math("MULTIPLY", mask, ramp(hsv.outputs["Blue"], vmin * 0.7, vmin))
        mix = t.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        t.links.new(mask, mix.inputs["Factor"])
        mix.inputs[6].default_value = (0.0, 0.0, 0.0, 1.0)
        t.links.new(colour, mix.inputs[7])
        t.links.new(mix.outputs[2], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = 1.0
        done += 1
    return {"hue": glow["hue"], "materials": done}


def paint_not_chrome(mats, finish, metal_max=0.12, rough_min=0.30):
    """A kept texture on a painted or polymer part keeps its colours but not the mesher's chrome: Tripo mapped the
    Havoc's canopy hood as roughness 0.04, metallic 0.82 (the rest of the hull 0.36 / 0.03), and it rendered as black
    mirror where the reference has grey-blue paint (2026-09-29). Metallic is squeezed to [0, metal_max] and roughness
    lifted to at least rough_min; bare metal belongs in a metal zone. -> what it changed"""
    if finish in ("metal", "glass", "emissive"):
        return None
    done = []
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        for sock, lo, hi in (("Metallic", 0.0, metal_max), ("Roughness", rough_min, 1.0)):
            inp = b.inputs[sock]
            if not inp.is_linked:
                inp.default_value = min(max(inp.default_value, lo), hi)
                continue
            src = inp.links[0].from_socket
            mr = t.nodes.new("ShaderNodeMapRange")
            mr.clamp = True
            t.links.new(src, mr.inputs["Value"])
            if sock == "Metallic":
                mr.inputs["To Max"].default_value = hi
            else:
                mr.inputs["To Min"].default_value = lo
            t.links.new(mr.outputs["Result"], inp)
            done.append(sock.lower())
    return {"metallic_max": metal_max, "roughness_min": rough_min, "maps": sorted(set(done))}


def flatten_lettering(o, boxes, lo, hi, relief=0.012, planar=0.004):
    """A painted word is paint, never geometry (materials.md): Tripo embossed the Havoc's POLICE as garbled relief
    ("TNALT") on both sides, and the projected word printed beside its ghost (2026-09-29). In each lettering box
    (percent of the side grid, the asset's `lo`..`hi`), on each side, a gently curved surface (a quadric over the
    panel's plane; the nose curves in under POLICE) is fitted to the panel (the farthest 30% dropped twice, so the
    letters do not pull it) and the vertices within `relief` of it (of the asset's diagonal) are laid onto it, the
    box's edge faded in. A box the surface does not fit (off by more than `planar`) is left alone: smoothing a
    sill left it lumpy. Seam copies of a vertex move together.
    -> {box: vertices moved, or "curved"}"""
    if not boxes:
        return {}
    me = o.data
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    nv = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("normal", nv)
    nv = nv.reshape(-1, 3)
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    diag = float(np.linalg.norm(hi - lo))
    xp = (co[:, 0] - lo[0]) / max(hi[0] - lo[0], 1e-9) * 100.0
    zp = (hi[2] - co[:, 2]) / max(hi[2] - lo[2], 1e-9) * 100.0
    weld = max(diag * 1e-5, 1e-9)
    _, gid = np.unique(np.round(co / weld).astype(np.int64), axis=0, return_inverse=True)
    gid = gid.ravel()
    out = {}
    moved = np.zeros(len(co), bool)
    for k, (x0, x1, z0, z1) in enumerate(boxes):
        inside = (xp >= x0) & (xp <= x1) & (zp >= z0) & (zp <= z1)
        for side, sign in (("near", -1.0), ("far", 1.0)):
            facing = np.nonzero(inside & (nv[:, 1] * sign > 0.5))[0]
            if len(facing) < 30:
                continue
            # the skin the word is painted on, found by the faces that look out to this side; then every vertex of it
            # whatever its normal (the letters' walls face along the length: left out, they folded), but not a
            # rocket pod further out at the same place
            skin_y = np.median(co[facing, 1])
            sel = np.nonzero(inside & (np.abs(co[:, 1] - skin_y) < 0.06 * (hi[1] - lo[1])))[0]
            if len(sel) < 30:
                continue
            pts = co[sel]
            c = pts.mean(axis=0)
            frame = np.linalg.svd(pts - c, full_matrices=False)[2]
            n = frame[2]
            a_, b_ = (pts - c) @ frame[0], (pts - c) @ frame[1]
            h = (pts - c) @ n
            basis = np.stack([np.ones_like(a_), a_, b_, a_ * a_, a_ * b_, b_ * b_], axis=1)
            keep = np.ones(len(sel), bool)
            for _ in range(3):
                coef = np.linalg.lstsq(basis[keep], h[keep], rcond=None)[0]
                d = h - basis @ coef                  # the relief above the panel's own gentle curve
                if _ < 2:
                    keep = np.abs(d) <= np.percentile(np.abs(d), 70)
            if np.percentile(np.abs(d[keep]), 70) > planar * diag:
                out["%d_%s" % (k, side)] = "curved"
                continue
            edge = np.minimum.reduce([xp[sel] - x0, x1 - xp[sel], (zp[sel] - z0) * 2, (z1 - zp[sel]) * 2]) / max(0.15 * (x1 - x0), 1e-9)
            w = np.clip(edge, 0.0, 1.0) * (np.abs(d) <= relief * diag)
            move = -(d * w)[:, None] * n[None, :]
            # the copies of a seam vertex share the move of the one inside the box
            shift = np.zeros((gid.max() + 1, 3))
            shift[gid[sel]] = move
            touched = np.isin(gid, gid[sel])
            co[touched] += shift[gid[touched]]
            out["%d_%s" % (k, side)] = int((w > 0).sum())
            moved[touched] = True
    me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    me.update()
    if moved.any():
        # the letters' walls are now slivers (their tops a few mm over their feet): welded and dissolved, or the
        # normal bake's bevel traced every letter again as dark smudges (2026-09-29)
        bm = bmesh.new()
        bm.from_mesh(me)
        tag = bm.verts.layers.int.new("ms_moved")
        bm.verts.ensure_lookup_table()
        for i in np.nonzero(moved)[0]:
            bm.verts[i][tag] = 1
        region = [v for v in bm.verts if v[tag]]
        bmesh.ops.remove_doubles(bm, verts=region, dist=0.0004 * diag)
        region_edges = list({e for v in bm.verts if v.is_valid and v[tag] for e in v.link_edges})
        bmesh.ops.dissolve_degenerate(bm, dist=0.0004 * diag, edges=region_edges)
        bm.verts.ensure_lookup_table()
        moved = np.array([bool(v[tag]) for v in bm.verts])
        bm.verts.layers.int.remove(tag)
        bm.to_mesh(me)
        bm.free()
        me.update()
        co = np.empty(len(me.vertices) * 3, np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        _, gid = np.unique(np.round(co / weld).astype(np.int64), axis=0, return_inverse=True)
        gid = gid.ravel()
        out["welded_to"] = int(len(me.vertices))
    if moved.any() and me.has_custom_normals:
        # a glTF seed carries its own normals: moved vertices keep the letters in their shading unless they take
        # the flattened surface's. Area-weighted, across seams: the letters' collapsed walls are slivers, and
        # Blender's angle-weighted vertex normals turned 50-120 degrees off the panel on them
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(-1, 3)
        cross = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
        acc = np.zeros((gid.max() + 1, 3))
        for k in range(3):
            np.add.at(acc, gid[tri[:, k]], cross)
        acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", lv)
        corner = np.empty(len(me.loops) * 3, np.float32)
        me.corner_normals.foreach_get("vector", corner)
        corner = corner.reshape(-1, 3)
        redo = moved[lv]
        corner[redo] = acc[gid[lv[redo]]]
        me.normals_split_custom_set(corner.tolist())
        me.update()
    return out


def island_report(o, drop=False):
    """Loose pieces, open edges and non-manifold edges of a seed, measured (Tonetta: vendor geometry is measured, not
    policed). With `drop`, only the far, small islands (under 0.5% of the faces and more than 2% of the length away
    from the main body) are deleted: a latch or a bar is a small island too."""
    me = o.data
    n = len(me.polygons)
    lo, hi = blib.dims(o)
    diag = (hi - lo).length
    fa, fb, counts = face_pairs(me, diag * 1e-5)
    roots = components(n, fa, fb)
    ids, sizes = np.unique(roots, return_counts=True)
    main = ids[np.argmax(sizes)]
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    mlo, mhi = centres[roots == main].min(axis=0), centres[roots == main].max(axis=0)
    far_small = []
    for i, k in zip(ids, sizes):
        if i == main or k >= 0.005 * n:
            continue
        c = centres[roots == i]
        gap = np.maximum(np.maximum(mlo - c.max(axis=0), c.min(axis=0) - mhi), 0).max()
        if gap > 0.02 * LENGTH_M:
            far_small.append(int(i))
    rep_ = {"islands": int(len(ids)), "far_small": len(far_small),
            "open_edges": round(float((counts == 1).mean()), 4), "non_manifold": round(float((counts > 2).mean()), 4)}
    if drop and far_small:
        dead = np.isin(roots, far_small)
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if dead[f.index]], context="FACES")
        bm.to_mesh(me)
        bm.free()
        me.update()
        rep_["dropped_faces"] = int(dead.sum())
    return rep_


# ---------------------------------------------------------------- parts in their boxes
bpy.ops.wm.read_factory_settings(use_empty=True)
parts, glass_parts, liner_parts, frame_parts = [], [], [], []
# the whole object's box, from the plan: the frame the side grid's percents (lettering boxes) are read in
ASSET_LO = [min(q["box_min"][i] for q in args["parts"]) for i in range(3)]
ASSET_HI = [max(q["box_max"][i] for q in args["parts"]) for i in range(3)]
for p in args["parts"]:
    o = import_part(p)
    rec = {"name": p["name"], "kind": p["kind"], "box_min": p["box_min"], "box_max": p["box_max"], **fit(o, p)}
    glass = bool((p.get("material") or {}).get("glass"))
    if p.get("lettering"):
        rec["lettering_flattened"] = flatten_lettering(o, p["lettering"], ASSET_LO, ASSET_HI)
    if p["kind"] == "code" and not glass:
        if args.get("edge_break_m") and p.get("edge_break", True):
            rec["edge_break_mm"] = edge_break(o, args["edge_break_m"])
        if p.get("skin") and os.path.exists(p["skin"]):
            rec["skin"] = skin_from_seed(o, p)
    # code parts carry the reference's fine detail; vendor parts (and skinned code parts) already have their own texture
    if p["kind"] == "code" and args.get("detail") and p.get("reference_detail", True) and not glass and not rec.get("skin"):
        rec["reference_detail"] = add_reference_detail(o, args["detail"])
    if p["kind"] == "vendor" and not (p.get("material") or {}).get("glass") and args.get("tint_vendor", True):
        pm0 = p.get("material") or {}
        zones_left = []
        glass_zones = [dict(z, pick=z.get("pick") or ("auto" if pm0.get("keep_texture") else "box")) for z in p.get("zones") or []
                       if ((z.get("material") or {}).get("glass") or (z.get("material") or {}).get("finish") == "glass")
                       and z.get("pick") != "atlas"]
        interiors = [q for q in args["parts"] if q.get("interior") and q is not p]
        carvers = [q for q in args["parts"] if q.get("carve") and q is not p]
        if p.get("body") and carvers:
            # 2026-10-04: a replacement part ("carve": true) takes the body's faces under it with it - the Kestrel's
            # seed nozzle was a soft drum with melted rings ("gooey", owner) and an exact sdf nozzle sits in its box
            # instead. Carved by the part's own solid outline (its convex hull, fitted into its box as the part will
            # be, grown by a small margin for the seed's slivers), not its box: the box took the fuselage deck above
            # the nozzle too and the hull was open from behind ("there's space I can see through thru the back").
            # The seed file is not touched (rule 10). Reported per part so a carve that ate a wing shows.
            from mathutils.bvhtree import BVHTree
            me = o.data
            nf = len(me.polygons)
            cen = np.empty(nf * 3, np.float32)
            me.polygons.foreach_get("center", cen)
            cen = cen.reshape(-1, 3)
            gone = np.zeros(nf, bool)
            rec["carved_for"] = {}
            for q in carvers:
                tmp = import_part(q)
                fit(tmp, q)
                hb = bmesh.new()
                hb.from_mesh(tmp.data)
                hull = bmesh.ops.convex_hull(hb, input=hb.verts)
                bmesh.ops.delete(hb, geom=[g for g in hull["geom_interior"] if isinstance(g, bmesh.types.BMVert)], context="VERTS")
                tree = BVHTree.FromBMesh(hb)
                ext = Vector(q["box_max"]) - Vector(q["box_min"])
                margin = 0.02 * min(ext)
                inside = np.zeros(nf, bool)
                inbox = np.all((cen >= np.array(q["box_min"]) - margin) & (cen <= np.array(q["box_max"]) + margin), axis=1)
                for i in np.nonzero(inbox)[0]:
                    c = Vector(cen[i])
                    loc, nrm, _idx, dist = tree.find_nearest(c)
                    if loc is not None and (dist <= margin or (c - loc).dot(nrm) < 0):
                        inside[i] = True
                hb.free()
                bpy.data.objects.remove(tmp, do_unlink=True)
                rec["carved_for"][q["name"]] = int(inside.sum())
                gone |= inside
            if gone.any():
                delete_faces(o, gone)
                log("%s: %d faces carved out for %s" % (p["name"], int(gone.sum()), ", ".join(q["name"] for q in carvers)))
        if p.get("body") and interiors and glass_zones:
            # an interior part replaces the seed's own cockpit: its contents go before the glass is picked
            carve, cst = cockpit_contents(o, glass_zones, [(q["box_min"], q["box_max"]) for q in interiors])
            if cst["faces"]:
                delete_faces(o, carve)
            rec["cockpit_carved"] = cst
            log("%s: the seed's own cockpit carved out for %s: %s" % (p["name"], ", ".join(q["name"] for q in interiors), cst))
        for z in p.get("zones") or []:
            zm0 = z.get("material") or {}
            mode = z.get("pick") or ("auto" if pm0.get("keep_texture") else "box")
            if (zm0.get("glass") or zm0.get("finish") == "glass") and mode != "atlas":
                # the glass is CUT OUT of the seed into a see-through part (2026-09-29, from Tonetta's forge): a
                # darkened patch of the atlas read as paint on every canopy
                mask, gstats, panes = pick_glass(o, z, mode, keep=int(z.get("keep", 8)), fill=bool(z.get("fill", True)),
                                                 rebuild=bool(z.get("shell")))
                log("%s: glass zone %s picked %s" % (p["name"], z.get("name"), gstats))
                zname = "%s_%s" % (p["name"], z.get("name", "glass"))
                made = []
                if gstats.get("preserve_frame"):
                    delete_faces(o, mask)   # explicitly fitted panes tuck under the existing frame
                elif gstats.get("rebuilt"):
                    delete_faces(o, mask)          # the seed's patchy panes go; the clean shell below is the glass
                    lo_o, hi_o = blib.dims(o)
                    panes = (smooth_rim(panes[0], panes[1]), panes[1])
                    band = rim_band(panes[0], panes[1], (hi_o - lo_o).length)
                    if band is not None:
                        frame_parts.append((pane_object(o, band, "Frame_" + zname), {"name": "%s.%s.frame" % (p["name"], z.get("name"))}))
                    bars = crease_bars(panes[0], panes[1], (hi_o - lo_o).length)
                    if bars is not None:
                        frame_parts.append((pane_object(o, bars, "Bars_" + zname), {"name": "%s.%s.bars" % (p["name"], z.get("name"))}))
                elif gstats["faces"] >= 20:
                    made.append((cut_out(o, mask, "Glass_" + zname), ""))
                if panes is not None:
                    made.append((pane_object(o, panes, "Panes_" + zname), ".panes"))
                gkw = zone_glass_kw(z)
                for g, tag in made:
                    g.data.materials.clear()
                    g.data.materials.append(zone_glass_material(zname, gkw))
                    glass_parts.append((g, {"name": "%s.%s%s" % (p["name"], z.get("name", "glass"), tag), "kind": "glass",
                                            "zone": zname, "glass_kw": gkw, **gstats}))
                if made:
                    report.setdefault("glass_zones", []).append({"part": p["name"], "zone": z.get("name"), **gstats})
                    if z.get("line", True):
                        # the cockpit under the glass: its walls are one skin thick; line their backs
                        lo_o, hi_o = blib.dims(o)
                        dg = (hi_o - lo_o).length
                        zlo = [z["box_min"][0] - 0.02 * dg, -1e9, lo_o.z]
                        zhi = [z["box_max"][0] + 0.02 * dg, 1e9, z["box_max"][2] + 0.02 * dg]
                        liner, lined = line_interior(o, [g for g, _t in made], zlo, zhi, dg, name="Liner_" + zname)
                        report["glass_zones"][-1]["lined_faces"] = lined
                        log("%s: %s lined %d faces seen through the glass from behind" % (p["name"], z.get("name"), lined))
                        if liner is not None:
                            liner_parts.append((liner, {"name": "%s.%s.lining" % (p["name"], z.get("name", "glass"))}))
                continue
            zones_left.append(z)
        if args.get("islands", True):
            rec["islands"] = island_report(o, drop=bool(args.get("drop_floaters")))
            log("%s: islands %s" % (p["name"], rec["islands"]))
        if args.get("finish_profile") == "restrained" and p.get("keep_depth"):
            from restrained_finish import depth_zones
            # 2026-09-30: a 63 mm seed in a 50 mm plan left the shotgun's blue receiver sides outside every zone.
            lo, hi = blib.dims(o)
            zones_left, rec["material_zone_depth_scale"] = depth_zones(
                zones_left, p["box_min"][1], p["box_max"][1], float(lo[1]), float(hi[1]))
        zoned = split_zones(o, zones_left)
        in_zone = set().union(*[m for _z, m in zoned]) if zoned else set()
        rest = {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree} - in_zone
        pm = p.get("material") or {}
        # a multi-coloured body (grey with an olive panel) keeps the vendor's colours; its surface is still the plan's
        # the sampled colour with the texture's own light and dark: the brightness-only path left a receiver near-white
        # twice (2026-09-28); zones carry any second colour, so nothing is lost by tinting the rest
        # a locked colour is the planned colour, whatever tone the vendor's texture has (the M4A1 receiver's green cast
        # survived because its texture was already about as dark as planned, 2026-09-29). A kept texture (a whole-object
        # seed: its camouflage, markings and its own material split) is left as the model made it; its zones still
        # take their planned materials.
        keep = bool(pm.get("keep_texture")) and not pm.get("color_lock")
        if not keep:
            rec["tinted"] = tint_to_plan(o, pm.get("color"), rest, metal=bool(pm.get("metal")), force=bool(pm.get("color_lock")))
            rec["surface_planned"] = surface_to_plan(o, pm, rest)
        else:
            rec["roughness_lift"] = lift_roughness(rest)
            rec["paint_not_chrome"] = paint_not_chrome(rest, pm.get("finish") or ("metal" if pm.get("metal") else "painted"))
        rec["kept_texture"] = keep
        if args.get("surface_detail", True):
            rec["surface_detail"] = surface_detail(o, pm, mats=rest, vendor=True)
        for z, mats in zoned:
            zm = z.get("material") or {}
            if zm.get("glass") or zm.get("finish") == "glass":
                glass_zone(mats)                   # smooth tinted glass; the wear pass turned a windshield to snow
                for m in mats:
                    m["ms_glass"] = True
                continue
            if zm.get("finish") == "emissive" and z.get("glow"):
                # 2026-09-30: only the texels in the glow's hue glow (a lens, an energy band, a lit tip); the rest of
                # the box keeps its own colour and finish, so no tint and no planned roughness here
                rec.setdefault("glow_zones", []).append(glow_emission(mats, z["glow"]))
                EMISSIVE["strength"] = max(EMISSIVE["strength"], float(z.get("strength") or zm.get("strength") or 8.0))
                continue
            tint_to_plan(o, zm.get("color"), mats, metal=bool(zm.get("metal")), force=bool(zm.get("color_lock")),
                         flat=bool(z.get("flat")))
            surface_to_plan(o, zm, mats)
            if zm.get("finish") == "emissive":
                # a lamp, a screen, an engine glow: its colour emitted, baked into T_<Name>_E; the strength (6-12, 1-2
                # only reads as a bright surface) is set on the final material (Tonetta's materials skill)
                for m in mats:
                    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                    if b is None:
                        continue
                    src = b.inputs["Base Color"]
                    if src.is_linked:
                        m.node_tree.links.new(src.links[0].from_socket, b.inputs["Emission Color"])
                    else:
                        b.inputs["Emission Color"].default_value = tuple(src.default_value)
                    b.inputs["Emission Strength"].default_value = 1.0
                EMISSIVE["strength"] = max(EMISSIVE["strength"], float(z.get("strength") or zm.get("strength") or 8.0))
                continue
            if args.get("surface_detail", True):
                surface_detail(o, zm, mats=mats, vendor=True)
        rec["zones"] = [z.get("name") for z, _m in zoned]
    lib = args.get("pbr_library") or {}
    if lib and not (p.get("material") or {}).get("glass"):
        length_m = float(args.get("length_m") or 1.0)
        sets = []
        if p["kind"] == "vendor" and args.get("tint_vendor", True):
            if not rec.get("kept_texture"):
                sets.append((p.get("pbr_set"), rest))
            for z, mats in zoned:
                sets.append((z.get("pbr_set"), mats))
        else:
            sets.append((p.get("pbr_set"), {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree}))
        rec["smart_materials"] = sum(smart_material(o, lib[key], mats, length_m) for key, mats in sets if key in lib and mats)
    if (args.get("finish_profile") == "restrained" and p["kind"] == "vendor"
            and not glass and args.get("tint_vendor", True)):
        from restrained_finish import apply as restrained_finish
        # 2026-09-30: apply after every material layer so later smart materials cannot restore the gloss.
        rec["restrained_finish"] = restrained_finish(rest, p.get("material") or {}, float(args["length_m"]))
        for zone, mats in zoned:
            rec["restrained_finish"] += restrained_finish(mats, zone.get("material") or {}, float(args["length_m"]))
    for slot in o.material_slots:
        if slot.material:
            slot.material.name = "MS_src_%s_%s" % (p["name"], slot.material.name)
    if (p.get("material") or {}).get("glass"):
        glass_parts.append((o, rec))
    else:
        parts.append((o, rec))
    report["parts"].append(rec)
if not parts:
    raise RuntimeError("no opaque parts to assemble")


def sharpen_planar(o, band=None, flat_deg=10.0, min_area_frac=0.002, crease_deg=25.0):
    """Hard-surface edges back on a vendor seed (owner, 2026-09-27: "why can't Blender sharpen edges"). An image-to-3D
    mesh rounds every edge of a faceted body. This finds its large near-flat panels (region growing on face normals),
    flattens each onto its best-fit plane, and pulls the vertices of the rounded band between two panels onto the
    line where the planes meet: the fillet becomes a crease. Curved areas (a grip, a magazine) have no large flat
    panel and are left alone; vertices only move, so the UVs and texture stay. `band` is the widest rounding pulled
    in (metres). -> {"panels", "flattened", "creased"}"""
    from mathutils import kdtree
    me = o.data
    if band is None:
        # the rounding a mesher puts on an edge grows with the object: 0.4% of its length (3 mm on the 68 cm bullpup),
        # never under 0.8 mm or over 5 mm. A fixed 3 mm tore the edges of an 18.5 cm pistol (2026-09-28).
        lo_b, hi_b = blib.dims(o)
        band = min(0.005, max(0.0008, 0.004 * max((hi_b - lo_b)[:])))
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    nf = len(bm.faces)
    if nf < 200:
        bm.free()
        return {"panels": 0, "flattened": 0, "creased": 0}
    normals = np.array([f.normal[:] for f in bm.faces], np.float64)
    centres = np.array([f.calc_center_median()[:] for f in bm.faces], np.float64)
    areas = np.array([f.calc_area() for f in bm.faces], np.float64)
    total = areas.sum()
    cos_flat = math.cos(math.radians(flat_deg))
    region = np.full(nf, -1, np.int64)
    panels = []                                   # (normal, point, face ids)
    order = np.argsort(-areas)
    for seed in order:
        if region[seed] != -1:
            continue
        n0 = normals[seed]
        stack, members = [seed], []
        region[seed] = -2
        while stack:
            i = stack.pop()
            members.append(i)
            for e in bm.faces[i].edges:
                for g in e.link_faces:
                    j = g.index
                    if region[j] == -1 and normals[j].dot(n0) > cos_flat and abs(n0.dot(centres[j] - centres[seed])) < band * 0.4:
                        region[j] = -2
                        stack.append(j)
        members = np.array(members)
        if areas[members].sum() < min_area_frac * total or len(members) < 12:
            region[members] = -3                   # too small to be a panel: left as it is
            continue
        w = areas[members][:, None]
        c = (centres[members] * w).sum(0) / w.sum()
        cov = ((centres[members] - c) * w).T @ (centres[members] - c)
        n = np.linalg.eigh(cov)[1][:, 0]
        if n.dot(n0) < 0:
            n = -n
        region[members] = len(panels)
        panels.append((n, c, members))
    if not panels:
        bm.free()
        return {"panels": 0, "flattened": 0, "creased": 0}
    # which panels each vertex touches
    vert_panels = [set() for _ in bm.verts]
    for pi, (_n, _c, members) in enumerate(panels):
        for fi in members:
            for v in bm.faces[fi].verts:
                vert_panels[v.index].add(pi)
    tree = kdtree.KDTree(sum(len(m) for _n, _c, m in panels))
    k = 0
    for pi, (_n, _c, members) in enumerate(panels):
        for fi in members:
            tree.insert(centres[fi], pi)
            k += 1
    tree.balance()
    flattened = creased = 0
    cos_crease = math.cos(math.radians(crease_deg))
    new_co = {}
    for v in bm.verts:
        p = np.array(v.co[:], np.float64)
        own = vert_panels[v.index]
        inner = len(own) == 1 and all(region[f.index] == next(iter(own)) for f in v.link_faces)
        if inner:                                  # wholly inside one panel: flattened onto it
            n, c, _m = panels[next(iter(own))]
            d = n.dot(p - c)
            if abs(d) < band:
                new_co[v.index] = p - n * d
                flattened += 1
            continue
        if own:
            continue                               # a panel's border vertex that is not in a rounding: left alone
        # a vertex of the rounded band (or a seam between panels): the two nearest panels that meet at an edge
        near = {}
        for (_co, pi, dist) in tree.find_range(v.co, band * 1.5):
            if pi not in near or dist < near[pi]:
                near[pi] = dist
        cand = sorted(near, key=near.get)
        pair = None
        for a in range(len(cand)):
            for b in range(a + 1, len(cand)):
                if panels[cand[a]][0].dot(panels[cand[b]][0]) < cos_crease:
                    pair = (cand[a], cand[b])
                    break
            if pair:
                break
        if not pair:
            continue
        (n1, c1, _), (n2, c2, _) = panels[pair[0]], panels[pair[1]]
        if abs(n1.dot(p - c1)) > band or abs(n2.dot(p - c2)) > band:
            continue                               # not in the rounding between these two panels
        dirn = np.cross(n1, n2)
        if np.linalg.norm(dirn) < 1e-6:
            continue
        dirn /= np.linalg.norm(dirn)
        # a point on the line: solve n1.x = n1.c1, n2.x = n2.c2, dirn.x = dirn.p
        A = np.array([n1, n2, dirn])
        rhs = np.array([n1.dot(c1), n2.dot(c2), dirn.dot(p)])
        try:
            q = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            continue
        if np.linalg.norm(q - p) < band:
            new_co[v.index] = q
            creased += 1
    old = {i: bm.verts[i].co.copy() for i in new_co}
    before = {f.index: f.normal.copy() for i in new_co for f in bm.verts[i].link_faces}
    for i, co in new_co.items():
        bm.verts[i].co = co
    for _ in range(3):                             # a move that flips or badly tilts a face is undone
        bm.normal_update()
        bad = set()
        for fi, n0 in before.items():
            f = bm.faces[fi]
            if f.calc_area() > 1e-14 and f.normal.dot(n0) < 0.3:
                bad.update(v.index for v in f.verts if v.index in old)
        if not bad:
            break
        for i in bad:
            bm.verts[i].co = old.pop(i)
            new_co.pop(i, None)
    flattened = sum(1 for i in new_co if len(vert_panels[i]) == 1)
    creased = len(new_co) - flattened
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    sharp_by_angle(o, degrees=crease_deg + 5)
    return {"panels": len(panels), "flattened": flattened, "creased": creased}


def find_bore(body_co, body_faces, centre, radius):
    """The body's own bore near `centre` (y, z) at its front end: rays cast straight back over a window around it; the
    bore is a round, enclosed region where they run deep (a shroud or muzzle opening), nearest the planned axis. The
    bullpup's TRELLIS body had a barrel shroud with a clean bore 20 mm from where the picture put the barrel, and the
    code barrel entered beside it (2026-09-28). -> (y, z) or None"""
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons([Vector(v) for v in body_co], body_faces)
    front = float(body_co[:, 0].max()) + radius
    half, step = 4.0 * radius, radius / 6.0
    ys = np.arange(centre[0] - half, centre[0] + half, step)
    zs = np.arange(centre[1] - half, centre[1] + half, step)
    deep = np.zeros((len(zs), len(ys)), bool)
    for i, z in enumerate(zs):
        for j, y in enumerate(ys):
            hit = bvh.ray_cast(Vector((front, y, z)), Vector((-1.0, 0.0, 0.0)), 12 * radius)
            deep[i, j] = hit[0] is None or (front - hit[0].x) > 4 * radius
    seen = np.zeros_like(deep)
    best = None
    for i0 in range(deep.shape[0]):
        for j0 in range(deep.shape[1]):
            if not deep[i0, j0] or seen[i0, j0]:
                continue
            stack, cells, edge = [(i0, j0)], [], False
            seen[i0, j0] = True
            while stack:
                i, j = stack.pop()
                cells.append((i, j))
                if i in (0, deep.shape[0] - 1) or j in (0, deep.shape[1] - 1):
                    edge = True                    # open to the window's border: not an enclosed bore
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a2, b2 = i + di, j + dj
                    if 0 <= a2 < deep.shape[0] and 0 <= b2 < deep.shape[1] and deep[a2, b2] and not seen[a2, b2]:
                        seen[a2, b2] = True
                        stack.append((a2, b2))
            if edge:
                continue
            cells = np.array(cells)
            area = len(cells) * step * step
            circle = math.pi * radius * radius
            ext = (np.ptp(cells[:, 0]) + 1, np.ptp(cells[:, 1]) + 1)
            roundness = len(cells) / (math.pi * (max(ext) / 2.0) ** 2)
            if not (0.1 * circle <= area <= 6 * circle) or roundness < 0.5:
                continue
            cy, cz = float(ys[int(round(cells[:, 1].mean()))]), float(zs[int(round(cells[:, 0].mean()))])
            dist = math.hypot(cy - centre[0], cz - centre[1])
            if dist <= 3.5 * radius and (best is None or dist < best[0]):
                best = (dist, cy, cz)
    return (best[1], best[2]) if best else None


def align_to_body(parts, specs):
    """Centreline parts (a barrel, a muzzle device) put on the vendor body's own axis where they enter it: their place
    came from the pictures, the body's from the mesher, and the two disagree by millimetres - enough that a bullet
    could not pass (owner, 2026-09-28). First the body's bore (find_bore): the parts move onto it in both directions.
    Without one, the middle of the body's front section decides the sideways place. Every centreline part moves by the
    same amount, so a barrel and its muzzle device stay on one axis."""
    line = [(o, r) for o, r in parts if (specs.get(r["name"]) or {}).get("centreline")]
    vend = [(o, r) for o, r in parts if r["kind"] == "vendor" and (o, r) not in line]
    if not vend or not line:
        return []
    # the part the barrel enters (its rear end inside that part's box: the handguard), not the largest part (the
    # receiver: its "bore" put the barrel 3 mm off the handguard's, 2026-09-28)
    lead0 = min(line, key=lambda t: blib.dims(t[0])[0].x)[0]
    l0, h0 = blib.dims(lead0)
    rear = Vector((l0.x + 0.02 * (h0.x - l0.x), (l0.y + h0.y) / 2, (l0.z + h0.z) / 2))
    entered = [(o, r) for o, r in vend if all(r["box_min"][i] - 0.005 <= rear[i] <= r["box_max"][i] + 0.005 for i in range(3))]
    body = (min(entered, key=lambda t: (t[1]["box_max"][0] - t[1]["box_min"][0])) if entered
            else max(vend, key=lambda t: (t[1]["box_max"][0] - t[1]["box_min"][0])))[0]
    co = np.empty(len(body.data.vertices) * 3, np.float32)
    body.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    # the body's faces as triangles, read in one call (issue #6)
    body.data.calc_loop_triangles()
    tri = np.empty(len(body.data.loop_triangles) * 3, np.int32)
    body.data.loop_triangles.foreach_get("vertices", tri)
    faces = tri.reshape(-1, 3).tolist()
    # the part that enters the body: the rearmost centreline part (a barrel before its muzzle device)
    lead = min(line, key=lambda t: blib.dims(t[0])[0].x)[0]
    lo, hi = blib.dims(lead)
    yc, zc = (lo.y + hi.y) / 2, (lo.z + hi.z) / 2
    radius = max(min(hi.y - lo.y, hi.z - lo.z) / 2, 1e-4)
    bore = find_bore(co, faces, (yc, zc), radius)
    if bore:
        dy, dz, how = bore[0] - yc, bore[1] - zc, "onto the body's bore"
    else:
        front = co[:, 0].max()
        near = co[(co[:, 0] > front - 6 * radius) & (np.abs(co[:, 2] - zc) < 5 * radius)]
        if len(near) < 20:
            return []
        dy, dz, how = float((near[:, 1].min() + near[:, 1].max()) / 2) - yc, 0.0, "onto the body's centreline"
    moved = []
    if abs(dy) > 1e-5 or abs(dz) > 1e-5:
        for o, r in line:
            o.data.transform(Matrix.Translation((0.0, dy, dz)))
            r["centred_on_body_m"] = [round(dy, 5), round(dz, 5)]
            moved.append((r["name"], dy, dz, how))
    return moved


for name, dy, dz, how in align_to_body(parts, {p["name"]: p for p in args["parts"]}):
    log("%s: moved %.1f mm sideways and %.1f mm up %s" % (name, dy * 1000, dz * 1000, how))


def pokes_out(o, occluders, samples=3000):
    """The share of `o`'s vertices from which a ray sideways (either way) or straight down leaves the model without
    meeting the hull or its glass: an insert showing through the outside. For a cockpit under glass the parity test
    below means nothing: the Havoc's hull is one skin with an open canopy, so its tub read 47% "in the walls" when
    only the part under the hood and the frame bars was (2026-09-29)."""
    from mathutils.bvhtree import BVHTree
    verts, polys = [], []
    for ob in occluders:
        me = ob.data
        me.calc_loop_triangles()
        mw = ob.matrix_world
        base = len(verts)
        verts += [mw @ v.co for v in me.vertices]
        polys += [[base + i for i in t.vertices] for t in me.loop_triangles]
    tree = BVHTree.FromPolygons(verts, polys)
    pts = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", pts)
    pts = pts.reshape(-1, 3)
    if len(pts) > samples:
        pts = pts[np.linspace(0, len(pts) - 1, samples).astype(int)]
    out = 0
    for p_ in pts:
        c = Vector(p_)
        out += any(tree.ray_cast(c, Vector(d))[0] is None for d in ((0, 1, 0), (0, -1, 0), (0, 0, -1)))
    return out / float(max(len(pts), 1))


def poke_fraction(o, body, samples=3000):
    """The share of `o`'s vertices that sit inside `body`'s material (odd number of crossings along a ray): an
    interior that fits its well pokes into the hull nowhere."""
    from mathutils.bvhtree import BVHTree
    bm = body.data
    bm.calc_loop_triangles()
    co = np.empty(len(bm.vertices) * 3, np.float32)
    bm.vertices.foreach_get("co", co)
    tri = np.empty(len(bm.loop_triangles) * 3, np.int32)
    bm.loop_triangles.foreach_get("vertices", tri)
    tree = BVHTree.FromPolygons([Vector(v) for v in co.reshape(-1, 3)], tri.reshape(-1, 3).tolist())
    pts = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", pts)
    pts = pts.reshape(-1, 3)
    if len(pts) > samples:
        pts = pts[np.linspace(0, len(pts) - 1, samples).astype(int)]
    d = Vector((0.31, 0.17, 0.935)).normalized()           # skewed, so no ray runs along a face
    lo, hi = blib.dims(body)
    eps = (hi - lo).length * 1e-5
    inside = 0
    for p_ in pts:
        origin, crossings = Vector(p_), 0
        for _ in range(24):
            hit = tree.ray_cast(origin, d)[0]
            if hit is None:
                break
            crossings += 1
            origin = hit + d * eps
        inside += crossings % 2
    return inside / float(max(len(pts), 1))


# an interior (a cockpit, a cabin) must sit in the body's well, not in its walls (owner, 2026-09-29: "so we know it fits")
body_obj = next((o for o, r in parts if (next((p for p in args["parts"] if p["name"] == r["name"]), {})).get("body")), None)
for o, r in parts:
    spec = next((p for p in args["parts"] if p["name"] == r["name"]), {})
    if spec.get("interior") and body_obj is not None and glass_parts:
        f = pokes_out(o, [body_obj] + [g for g, _r in glass_parts])
        r["pokes_out"] = round(f, 4)
        log("%s: %.1f%% of it shows through the hull%s" % (r["name"], f * 100, " - it does NOT fit; shrink its box" if f > 0.03 else " (fits under the glass)"))
    elif spec.get("interior") and body_obj is not None:
        f = poke_fraction(o, body_obj)
        r["pokes_into_body"] = round(f, 4)
        log("%s: %.1f%% of it pokes into the body%s" % (r["name"], f * 100, " - it does NOT fit its well; ms cabin gives the box that does" if f > 0.03 else " (fits)"))

# ---------------------------------------------------------------- the triangle budget: code parts as built, vendor parts share the rest
budget = int(args["tri_budget"])
vendor = [(o, r) for o, r in parts if r["kind"] == "vendor"]


def sharp_by_angle(o, degrees=30):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    lim = math.radians(degrees)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        e.smooth = not (e.is_manifold and e.calc_face_angle(0.0) > lim)
    bm.to_mesh(o.data)
    bm.free()


# hard-surface edges back on the vendor seeds before anything is copied, decimated or baked
if args.get("sharpen", True):
    fitted = {p["name"] for p in args["parts"] if p.get("fitted")}
    for o, r in parts:
        if r["kind"] == "vendor" and r["name"] not in fitted:      # a fitted seed's texture mottled under the flattening
            r["sharpened"] = sharpen_planar(o)
            log("%s: sharpened %s" % (r["name"], r["sharpened"]))

# ---------------------------------------------------------------- photo projection (#14)
def face_visibility(o, others, direction, eps):
    """Per face of `o`: 1 when a ray from the face centre towards `direction` (a unit vector, towards the camera) hits
    nothing, 0 when another part (or the part itself) is in the way: the front picture must not land on a receiver
    face hidden behind the handguard. -> numpy array over the polygons"""
    from mathutils.bvhtree import BVHTree
    me = o.data
    n = len(me.polygons)
    centres = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    normals = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    d = Vector(direction)
    trees = []
    for q in others:
        qm = q.data
        qm.calc_loop_triangles()
        co = np.empty(len(qm.vertices) * 3, np.float32)
        qm.vertices.foreach_get("co", co)
        tri = np.empty(len(qm.loop_triangles) * 3, np.int32)
        qm.loop_triangles.foreach_get("vertices", tri)
        trees.append(BVHTree.FromPolygons([Vector(v) for v in co.reshape(-1, 3)], tri.reshape(-1, 3).tolist()))
    vis = np.ones(n, np.float32)
    facing = (normals @ np.asarray(direction, np.float32)) > 0.05
    for i in np.nonzero(facing)[0]:
        start = Vector(centres[i]) + Vector(normals[i]) * eps + d * eps
        for t in trees:
            if t.ray_cast(start, d)[0] is not None:
                vis[i] = 0.0
                break
    # a face counts as seen only when most of its neighbours are too: the binary test checkered a noisy seed
    fa, fb, degree = face_adjacency(me)
    for _ in range(2):
        vis = (np.bincount(fa, weights=vis[fb], minlength=n) / np.maximum(degree, 1.0) > 0.6).astype(np.float32)
    return vis


def face_adjacency(me):
    """Every pair of faces sharing a vertex (each face with itself too), as (face_a, face_b, degree) arrays."""
    n = len(me.polygons)
    loop_total = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_vert = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", loop_vert)
    face_of_loop = np.repeat(np.arange(n, dtype=np.int64), loop_total)
    order = np.argsort(loop_vert, kind="stable")
    fs = face_of_loop[order]
    _, start, k = np.unique(loop_vert[order], return_index=True, return_counts=True)
    k_e = np.repeat(k, k)
    start_e = np.repeat(start, k)
    rep = np.repeat(np.arange(len(fs)), k_e)
    within = np.arange(len(rep)) - np.repeat(np.cumsum(k_e) - k_e, k_e)
    pairs = np.unique(fs[rep] * n + fs[np.repeat(start_e, k_e) + within])
    fa, fb = pairs // n, pairs % n
    return fa, fb, np.bincount(fa, minlength=n).astype(np.float32)


def facing_attributes(o, iters=4):
    """Point attributes ms_face_x / ms_face_y: the vertex normal's X and Y after a few rounds of averaging with the
    neighbours. The projection blends on these, interpolated across the face, instead of on each facet's own normal:
    a mesher's surface is bumpy, and per-facet blending checkered the receiver (2026-09-28)."""
    me = o.data
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", v)
    f = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", f)
    verts, faces = v.reshape(-1, 3).astype(np.float64), f.reshape(-1, 3).astype(np.int64)
    n = sculpt.vertex_normals(verts, faces)
    adj = sculpt.neighbours(faces, len(verts))
    for _ in range(iters):
        n = 0.5 * n + 0.5 * sculpt.neighbour_mean(n, adj, len(verts))
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    for name, col in (("ms_face_x", 0), ("ms_face_y", 1)):
        attr = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        attr.data.foreach_set("value", n[:, col].astype(np.float32))


def side_agreement(o, picture, frame, size=96):
    """How well a picture's object mask lines up with the part as it now sits, seen from the side in `frame`
    (cx, cz, L, H): (IoU, coverage = the share of the part's outline that the picture covers). A part whose picture
    does not line up with its mesh gets the wrong colours in the wrong places (the Apache's blades reach past the
    drawing, 2026-09-29), so the projection is skipped below a floor."""
    probe = o.copy()
    probe.data = o.data.copy()
    bpy.context.collection.objects.link(probe)
    if blib.tri_count(probe) > 3000:
        m = probe.modifiers.new("dec", "DECIMATE")
        m.ratio = 3000.0 / blib.tri_count(probe)
        blib.select_only([probe])
        bpy.ops.object.modifier_apply(modifier="dec")
    me = probe.data
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) @ np.array(probe.matrix_world)[:3, :3].T + np.array(probe.matrix_world)[:3, 3]
    tri = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tri)
    bpy.data.objects.remove(probe, do_unlink=True)
    cx, cz, L_, H_ = frame
    uv = np.stack([((co[:, 0] - cx) / L_ + 0.5) * size, (0.5 - (co[:, 2] - cz) / H_) * size], axis=1)
    got = sculpt.raster(uv, tri.reshape(-1, 3), size)
    img = bpy.data.images.load(os.path.abspath(picture), check_existing=True)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    alpha = px.reshape(h, w, 4)[::-1, :, 3] > 0.5
    want = alpha[(np.arange(size) * h / size).astype(int)][:, (np.arange(size) * w / size).astype(int)]
    iou = float((got & want).sum()) / max(float((got | want).sum()), 1.0)
    cover = float((got & want).sum()) / max(float(got.sum()), 1.0)
    return iou, cover


def project_pictures(o, p, proj):
    """Base colour from the pictures (issue #14): the part's own side picture (drawn alone, cropped to the part) on
    the faces that look sideways - mirrored onto the far side - and the approved front picture on the faces that look
    forward and are not hidden behind another part. Each is blended by how squarely the face looks at that picture and
    by the picture's own alpha (its object mask), over whatever colour the material had, so the mesher's texture stays
    where no picture sees. A high-pass of the picture drives a bump where the material has no normal map yet."""
    strength = float(proj.get("strength", 0.85))
    mats = {sl.material for sl in o.material_slots if sl.material and sl.material.node_tree and not sl.material.get("ms_glass")}
    if not mats:
        return {}
    # a kept texture (a whole-object seed) is the mesher's own paint: the picture printed over it left pale slot
    # patches on the bullpup, white marks round the tank's wheels and washed out the Havoc's hull, and projection was
    # switched off on most builds of 2026-09-29/30. It prints there only inside the lettering boxes now.
    letters_only = bool(p.get("letters_only"))
    views = []
    skipped = []
    letter_frame = False           # lettering boxes are percents of the whole object's side grid: its frame only
    own = p.get("projection") or {}
    if own.get("picture") and os.path.exists(own["picture"]):
        if own.get("frame") == "asset":
            fr = proj["asset_frame"]
        else:
            lo, hi = blib.dims(o)
            fr = [(lo.x + hi.x) / 2, (lo.z + hi.z) / 2, max(hi.x - lo.x, 1e-6), max(hi.z - lo.z, 1e-6)]
        iou, cover = side_agreement(o, own["picture"], fr)
        # its own picture must outline the part it is printed on; the erased body picture carries holes where the
        # other parts were, so only its coverage counts
        if (own.get("frame") == "asset" and cover >= 0.75) or (own.get("frame") != "asset" and iou >= 0.6):
            views.append(("side", own["picture"], own.get("detail"), fr, None))
            letter_frame = own.get("frame") == "asset"
        else:
            skipped.append("own side picture (IoU %.2f, covers %.2f)" % (iou, cover))
    elif proj.get("side") and os.path.exists(proj["side"]):
        iou, cover = side_agreement(o, proj["side"], proj["asset_frame"])
        if cover >= 0.8:
            views.append(("side", proj["side"], proj.get("side_detail"), proj["asset_frame"], "ms_vis_side"))
            letter_frame = True
        else:
            skipped.append("approved side view (covers %.2f)" % cover)
    if skipped:
        log("%s: projection skipped for the %s - the picture does not line up with the part" % (p.get("name"), ", ".join(skipped)))
    if proj.get("front") and os.path.exists(proj["front"]) and p.get("front_part") and not letters_only:
        views.append(("front", proj["front"], proj.get("front_detail"), proj["asset_frame_front"], "ms_vis_front"))
    if not views:
        return {"skipped": skipped} if skipped else {}
    done = []
    for m in mats:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        N, K = t.nodes, t.links

        def op(kind, a, c=None):
            n = N.new("ShaderNodeMath")
            n.operation = kind
            for i, v in enumerate((a, c)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    n.inputs[i].default_value = float(v)
                else:
                    K.new(v, n.inputs[i])
            return n.outputs[0]

        def facing(sock, lo_=0.35, hi_=0.7):
            mr = N.new("ShaderNodeMapRange")
            mr.interpolation_type = "SMOOTHSTEP"
            mr.clamp = True
            mr.inputs["From Min"].default_value = lo_
            mr.inputs["From Max"].default_value = hi_
            K.new(sock, mr.inputs["Value"])
            return mr.outputs["Result"]
        geo = N.new("ShaderNodeNewGeometry")
        pos = N.new("ShaderNodeSeparateXYZ")
        K.new(geo.outputs["Position"], pos.inputs[0])
        face_x = N.new("ShaderNodeAttribute")
        face_x.attribute_name = "ms_face_x"
        face_y = N.new("ShaderNodeAttribute")
        face_y.attribute_name = "ms_face_y"
        base = b.inputs["Base Color"]
        if base.is_linked:
            colour = base.links[0].from_socket
        else:
            rgb = N.new("ShaderNodeRGB")
            rgb.outputs[0].default_value = tuple(base.default_value)
            colour = rgb.outputs[0]
        bump_h = None
        letters_mask = None
        for view, path, detail, fr, vis_attr in views:
            img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
            img.alpha_mode = "STRAIGHT"
            det_img = None
            if detail and os.path.exists(detail):
                det_img = bpy.data.images.load(os.path.abspath(detail), check_existing=True)
                det_img.colorspace_settings.name = "Non-Color"
            if view == "side":
                cx, cz, L_, H_ = fr
                u = op("ADD", op("DIVIDE", op("SUBTRACT", pos.outputs["X"], cx), L_), 0.5)
                v = op("ADD", op("DIVIDE", op("SUBTRACT", pos.outputs["Z"], cz), H_), 0.5)
                # the far side takes the picture at the SAME place along the length (a symmetric part looks the same
                # there), with its own occlusion test towards +Y. Sampling it end to end reversed (1 - u) put the
                # sword's grip brown near its tip and whitened the tank's far wheels (2026-09-29). Words would read
                # backwards there, so inside each lettering box the far side reads the box mirrored back.
                u_far, letters = u, None
                for x0, x1, z0, z1 in (p.get("lettering") or []) if letter_frame else []:
                    a_, b_, vb, vt = x0 / 100.0, x1 / 100.0, 1.0 - z1 / 100.0, 1.0 - z0 / 100.0
                    inside = op("MULTIPLY", op("MULTIPLY", op("GREATER_THAN", u, a_), op("LESS_THAN", u, b_)),
                                op("MULTIPLY", op("GREATER_THAN", v, vb), op("LESS_THAN", v, vt)))
                    u_far = op("ADD", u_far, op("MULTIPLY", inside, op("SUBTRACT", a_ + b_, op("MULTIPLY", u, 2.0))))
                    letters = inside if letters is None else op("MAXIMUM", letters, inside)
                sides = ((u, op("MULTIPLY", face_y.outputs["Fac"], -1.0), vis_attr),                # near side, from -Y
                         (u_far, face_y.outputs["Fac"], vis_attr and vis_attr + "_far"))              # far side, from +Y
                letters_mask = letters if letters is not None else letters_mask
            else:
                cy, cz, W_, H_ = fr
                u = op("ADD", op("DIVIDE", op("SUBTRACT", pos.outputs["Y"], cy), W_), 0.5)
                v = op("ADD", op("DIVIDE", op("SUBTRACT", pos.outputs["Z"], cz), H_), 0.5)
                sides = ((u, face_x.outputs["Fac"], vis_attr),)
                letters = None
            if letters_only and letters is None:
                continue                   # nothing of this picture prints on a kept texture outside the lettering
            for uu, face_dot, side_vis in sides:
                uv = N.new("ShaderNodeCombineXYZ")
                K.new(uu, uv.inputs[0])
                K.new(v, uv.inputs[1])
                tex = N.new("ShaderNodeTexImage")
                tex.image = img
                tex.extension = "CLIP"
                K.new(uv.outputs[0], tex.inputs["Vector"])
                if view == "front":                # foreshortened and lit from the front: squarely facing faces only, gently
                    w = op("MULTIPLY", facing(face_dot, 0.6, 0.85), op("MULTIPLY", tex.outputs["Alpha"], strength * 0.7))
                elif letters_only:
                    w = op("MULTIPLY", letters, op("MULTIPLY", facing(face_dot, 0.1, 0.3), tex.outputs["Alpha"]))
                else:
                    w = op("MULTIPLY", facing(face_dot), op("MULTIPLY", tex.outputs["Alpha"], strength))
                    if letters is not None:
                        # a painted word prints whole over the mesher's own blurred copy of it: no ghost letters
                        w = op("MAXIMUM", w, op("MULTIPLY", letters, op("MULTIPLY", facing(face_dot, 0.1, 0.3), tex.outputs["Alpha"])))
                if side_vis:
                    at = N.new("ShaderNodeAttribute")
                    at.attribute_name = side_vis
                    w = op("MULTIPLY", w, at.outputs["Fac"])
                mix = N.new("ShaderNodeMix")
                mix.data_type = "RGBA"
                mix.clamp_factor = True
                K.new(w, mix.inputs["Factor"])
                K.new(colour, mix.inputs["A"])
                K.new(tex.outputs["Color"], mix.inputs["B"])
                colour = mix.outputs["Result"]
                if det_img is not None:
                    dt = N.new("ShaderNodeTexImage")
                    dt.image = det_img
                    dt.extension = "EXTEND"
                    K.new(uv.outputs[0], dt.inputs["Vector"])
                    term = op("MULTIPLY", op("SUBTRACT", dt.outputs["Color"], 0.5), w)
                    bump_h = term if bump_h is None else op("ADD", bump_h, term)
        for l in list(base.links):
            K.remove(l)
        K.new(colour, base)
        if letters_mask is not None and b.inputs["Normal"].is_linked:
            # the seed's own normal map carries its embossed letters (Tripo's "TNALT" shaded through the flattened
            # panel and the painted word, 2026-09-29): inside the lettering boxes the surface's own normal wins
            nmix = N.new("ShaderNodeMix")
            nmix.data_type = "VECTOR"
            nmix.clamp_factor = True
            K.new(letters_mask, nmix.inputs["Factor"])
            K.new(b.inputs["Normal"].links[0].from_socket, nmix.inputs[4])
            K.new(geo.outputs["Normal"], nmix.inputs[5])
            K.new(nmix.outputs[1], b.inputs["Normal"])
        if bump_h is not None and not b.inputs["Normal"].is_linked:
            bump = N.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.35
            bump.inputs["Distance"].default_value = 0.0006
            K.new(bump_h, bump.inputs["Height"])
            K.new(bump.outputs["Normal"], b.inputs["Normal"])
        done.append(m.name)
    return {"views": [v[0] for v in views], "materials": len(done), "skipped": skipped}


if args.get("projection"):
    proj = dict(args["projection"])
    lo_all = Vector((min(blib.dims(o)[0].x for o, _r in parts), min(blib.dims(o)[0].y for o, _r in parts), min(blib.dims(o)[0].z for o, _r in parts)))
    hi_all = Vector((max(blib.dims(o)[1].x for o, _r in parts), max(blib.dims(o)[1].y for o, _r in parts), max(blib.dims(o)[1].z for o, _r in parts)))
    # the plan pictures are cropped to the whole object's silhouette: its box is their frame
    proj["asset_frame"] = [(lo_all.x + hi_all.x) / 2, (lo_all.z + hi_all.z) / 2, hi_all.x - lo_all.x, hi_all.z - lo_all.z]
    proj["asset_frame_front"] = [(lo_all.y + hi_all.y) / 2, (lo_all.z + hi_all.z) / 2, hi_all.y - lo_all.y, hi_all.z - lo_all.z]
    eps = max((hi_all - lo_all).length * 0.0008, 0.0002)
    all_objs = [o for o, _r in parts]
    front_line = lo_all.x + 0.55 * (hi_all.x - lo_all.x)     # the front picture: parts that sit wholly in the front 45%
    for o, r in parts:
        spec = next((p for p in args["parts"] if p["name"] == r["name"]), {})
        if (spec.get("material") or {}).get("glass") or spec.get("interior") or spec.get("no_projection"):
            continue                 # a cockpit insert is not in the side picture's paint (it is behind the glass);
                                     # "projection": false in the plan keeps the pictures off a part (2026-10-04)
        pm_ = spec.get("material") or {}
        mode = proj.get("mode", "full")
        spec["letters_only"] = mode == "letters" or (mode == "auto" and bool(pm_.get("keep_texture")) and not pm_.get("color_lock"))
        if spec["letters_only"] and mode == "auto":
            r["colour_grade"] = grade_to_picture({sl.material for sl in o.material_slots if sl.material and sl.material.node_tree},
                                                 proj.get("side_mean_linear"))
            if r["colour_grade"]:
                log("%s: kept texture's colour cast graded to the picture, gains %s" % (r["name"], r["colour_grade"]))
        if spec["letters_only"] and not spec.get("lettering"):
            r["projection"] = {"skipped": ["kept texture: the pictures print only inside lettering boxes, and it has none"]}
            continue
        # a long part reaching into the front zone (the bullpup receiver runs to 61% of the length under the
        # handguard) got the front picture on its hidden front faces in patches (2026-09-28): its REAR end decides
        spec["front_part"] = blib.dims(o)[0].x > front_line
        facing_attributes(o)
        if proj.get("front") and spec["front_part"] and not spec["letters_only"]:
            vis = face_visibility(o, all_objs, (1.0, 0.0, 0.0), eps)
            attr = o.data.attributes.get("ms_vis_front") or o.data.attributes.new("ms_vis_front", "FLOAT", "FACE")
            attr.data.foreach_set("value", vis.astype(np.float32))
        if not spec.get("projection") and proj.get("side"):
            for name, direction in (("ms_vis_side", (0.0, -1.0, 0.0)), ("ms_vis_side_far", (0.0, 1.0, 0.0))):
                vis = face_visibility(o, all_objs, direction, eps)
                attr = o.data.attributes.get(name) or o.data.attributes.new(name, "FLOAT", "FACE")
                attr.data.foreach_set("value", vis.astype(np.float32))
        r["projection"] = project_pictures(o, spec, proj)
        if spec["letters_only"]:
            r["projection"]["letters_only"] = True
    log("pictures projected (%s): " % proj.get("mode", "full") + ", ".join(
        "%s (%s)" % (r["name"], "+".join(r["projection"].get("views", [])) or "none") for _o, r in parts if r.get("projection")))

def front_depth(objs, length, cells=200):
    """How far a ray from just ahead of the front travels back (-X) before it meets the model, over a grid across the
    front 30% of the asset (rows: z upwards, cols: y). -> (depth, cell, x_front, y0, z0)"""
    from mathutils.bvhtree import BVHTree
    verts, tris = [], []
    for ob in objs:
        me = ob.data
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        m = np.array(ob.matrix_world)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        tri = np.empty(len(me.loop_triangles) * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        tris.append(tri.reshape(-1, 3) + sum(len(v) for v in verts))
        verts.append(co)
    co, tri = np.concatenate(verts), np.concatenate(tris)
    bvh = BVHTree.FromPolygons([Vector(v) for v in co], tri.tolist())
    x_front = float(co[:, 0].max())
    near = co[co[:, 0] > x_front - 0.3 * length]
    lo_, hi_ = near.min(axis=0), near.max(axis=0)
    cell = max(float(max(hi_[1] - lo_[1], hi_[2] - lo_[2])) / cells, 1e-5)
    y0, z0 = float(lo_[1]) - 3 * cell, float(lo_[2]) - 3 * cell
    ny = int((hi_[1] - lo_[1]) / cell) + 7
    nz = int((hi_[2] - lo_[2]) / cell) + 7
    depth = np.full((nz, ny), np.inf)
    start = x_front + 0.01 * length
    back = Vector((-1.0, 0.0, 0.0))
    for i in range(nz):
        z = z0 + (i + 0.5) * cell
        for j in range(ny):
            hit = bvh.ray_cast(Vector((start, y0 + (j + 0.5) * cell, z)), back, 1.5 * length)[0]
            if hit is not None:
                depth[i, j] = x_front - hit.x
    return depth, cell, x_front, y0, z0


def named_box(*words):
    """The box of the first part, or zone of a part, whose name has one of `words` (asset frame, metres)."""
    for q in args["parts"]:
        if any(w in q["name"].lower() for w in words):
            return Vector(q["box_min"]), Vector(q["box_max"])
    for q in args["parts"]:
        for z in q.get("zones") or []:
            if any(w in str(z.get("name", "")).lower() for w in words) and z.get("box_min"):
                return Vector(z["box_min"]), Vector(z["box_max"])
    return None


def weapon_sockets(objs, lo, hi):
    """A weapon's sockets: Muzzle (or Muzzle_0..n and Muzzle between them) at its open bores, measured end-on
    (muzzle.py); Grip and Sight from a part or zone named so. -> (sockets, muzzle report or None)"""
    spec = args.get("spec") or {}
    sockets, info = [], None
    length = float(hi.x - lo.x)
    if not muzzlekit.is_melee(spec.get("description")):
        depth, cell, x_front, y0, z0 = front_depth(objs, length)
        found = muzzlekit.muzzle_openings(depth, cell, length)
        pts = [(x_front - o["rim_depth_m"], y0 + (o["col"] + 0.5) * cell, z0 + (o["row"] + 0.5) * cell) for o in found]
        info = {"found": len(found), "open": bool(found) and all(o["open"] for o in found), "grid_mm": round(cell * 1000, 2),
                "bores": [{"diameter_mm": round(o["diameter_m"] * 1000, 1), "open": o["open"],
                           "depth_mm": None if o["bore_depth_m"] == float("inf") else round(o["bore_depth_m"] * 1000, 1)}
                          for o in found]}
        tubes = int(args.get("tubes") or 0)
        if tubes > 1 and len(pts) < tubes:
            # loaded or capped tubes show no bore: their centres from the front-most vertices (assemble --tubes N)
            co = np.concatenate([np.array([o.matrix_world @ v.co for v in o.data.vertices]) for o in objs])
            front = co[co[:, 0] > co[:, 0].max() - max(0.03 * length, 0.005)]
            centres, lab = muzzlekit.cluster_tubes(front[:, 1:3], tubes)
            pts = [(float(front[lab == j][:, 0].max()) if (lab == j).any() else float(co[:, 0].max()), float(centres[j][0]),
                    float(centres[j][1])) for j in range(tubes)]
            info["tubes_from_vertices"] = tubes
        if len(pts) > 1:
            for k, i in enumerate(muzzlekit.order_muzzles(pts)):
                sockets.append({"name": "Muzzle_%d" % k, "location": [round(v, 4) for v in pts[i]]})
            sockets.append({"name": "Muzzle", "location": [round(float(np.mean([p[i] for p in pts])), 4) for i in range(3)]})
        elif pts:
            sockets.append({"name": "Muzzle", "location": [round(v, 4) for v in pts[0]]})
        else:
            # no recess at all: the middle of the front-most end, never the box centre (2026-10-01)
            co = np.concatenate([np.array([o.matrix_world @ v.co for v in o.data.vertices]) for o in objs])
            tip = co[co[:, 0] > co[:, 0].max() - max(0.004 * length, 1e-4)]
            sockets.append({"name": "Muzzle", "location": [round(float(co[:, 0].max()), 4), round(float(tip[:, 1].mean()), 4),
                                                            round(float(tip[:, 2].mean()), 4)]})
    g = named_box("grip")
    if g is not None:
        sockets.append({"name": "Grip", "location": [round(v, 4) for v in ((g[0] + g[1]) / 2)]})
    s = named_box("rail", "sight", "optic", "scope")
    if s is not None:
        sockets.append({"name": "Sight", "location": [round((s[0].x + s[1].x) / 2, 4), round((s[0].y + s[1].y) / 2, 4), round(s[1].z, 4)]})
    return sockets, info


def render_muzzle(target, sockets, lo, hi, path, hidden=()):
    """The muzzle end-on, close: where an open bore (or a lens, a cap, a glow in it) shows. -> file name or None"""
    pts = [Vector(s["location"]) for s in sockets if s["name"].startswith("Muzzle")]
    if not pts:
        return None
    r_ = max(0.05 * (hi.x - lo.x), 0.01)
    blo = Vector((max(p.x for p in pts) - 2 * r_, min(p.y for p in pts) - r_, min(p.z for p in pts) - r_))
    bhi = Vector((max(p.x for p in pts), max(p.y for p in pts) + r_, max(p.z for p in pts) + r_))
    st = blib.Stage(target, extra_hidden=list(hidden), focus_bounds=(blo, bhi))
    st.render("front", path)
    st.close()
    return os.path.basename(path)


def frame_material():
    """A rebuilt canopy's frame band and bars: the body's planned paint, a slot of its own."""
    body_spec = next((q for q in args["parts"] if q.get("body")), {})
    fm = bpy.data.materials.get("MI_%s_Frame" % NAME) or bpy.data.materials.new("MI_%s_Frame" % NAME)
    fb = next(n for n in fm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    fb.inputs["Base Color"].default_value = (*planned_linear((body_spec.get("material") or {}).get("color") or "#495058"), 1.0)
    fb.inputs["Roughness"].default_value = 0.5
    fb.inputs["Metallic"].default_value = 0.0
    return fm


IS_WEAPON = (args.get("spec") or {}).get("category") == "weapon"
SIZE_LONGEST = bool(args.get("size_longest"))

if SIZE_LONGEST and float((args.get("spec") or {}).get("size_m") or 0) > 0:
    # a natural object's brief size is its longest side, whichever axis that is (spec.size_m): the body keeps the
    # seed's depth, and a coral seeded deeper than its side picture came out 1.09 m for a 0.9 m brief (2026-10-03).
    # One uniform scale about the asset centre, so its proportions are the seed's.
    every = [o for o, _r in parts + glass_parts + liner_parts + frame_parts]
    bounds = [blib.dims(o) for o in every]
    extent = max(max(b[1][i] for b in bounds) - min(b[0][i] for b in bounds) for i in range(3))
    factor = float(args["spec"]["size_m"]) / max(extent, 1e-9)
    for o in every:
        o.data.transform(o.matrix_world.inverted() @ Matrix.Scale(factor, 4) @ o.matrix_world)
        o.data.update()
    report["size_longest"] = {"scale": round(factor, 4), "longest_m": round(float(args["spec"]["size_m"]), 4)}
    log("natural object: scaled x%.4f so its longest side is the brief's %.3f m" % (factor, float(args["spec"]["size_m"])))

if args.get("draft"):
    # `assemble --draft` (2026-10-02): the Havoc's glass and cockpit took ~18 full assembles of 5-9 min each for 1%
    # box nudges on 2026-09-29. A draft stops here - parts placed, zones, glass, lining and projection done, no
    # decimation, bake, LODs or exports - and renders the source parts with their own materials into delivery/draft/,
    # with report.json's glass_zones, pokes_out, islands and (weapons) the measured muzzle. The delivery is untouched.
    draft_dir = os.path.join(OUT, "draft")
    os.makedirs(draft_dir, exist_ok=True)
    for o, _r in liner_parts:
        o.data.materials.clear()
        o.data.materials.append(interior_material("MI_%s_Interior" % NAME))
    for o, _r in frame_parts:
        o.data.materials.clear()
        o.data.materials.append(frame_material())
    copies = []
    for o in [o for o, _r in parts + glass_parts + liner_parts + frame_parts]:
        c = o.copy()
        c.data = o.data.copy()
        bpy.context.collection.objects.link(c)
        copies.append(c)
    blib.select_only(copies)
    if len(copies) > 1:
        bpy.ops.object.join()
    draft = bpy.context.view_layer.objects.active
    draft.name = "Draft_" + NAME
    lo, hi = blib.dims(draft)
    report["draft"] = True
    report["dimensions_m"] = [round(v, 4) for v in (hi - lo)]
    if IS_WEAPON:
        report["sockets"], report["muzzle"] = weapon_sockets([draft], lo, hi)
        log("muzzle: %s; sockets %s" % (report["muzzle"], [s["name"] for s in report["sockets"]]))
    blib.setup_render(int(args.get("render_size", 768)), 32, look="preview")
    stage = blib.Stage(draft)
    report["renders"] = [stage.render(v, os.path.join(draft_dir, "draft_%s.png" % v))["file"] for v in ("iso", "side", "front")]
    stage.close()
    span = hi.x - lo.x
    for tag, x0, x1 in (("front", hi.x - span * 0.4, hi.x), ("rear", lo.x, lo.x + span * 0.4)):
        st = blib.Stage(draft, focus_bounds=(Vector((x0, lo.y, lo.z)), Vector((x1, hi.y, hi.z))))
        report["renders"].append(st.render("iso", os.path.join(draft_dir, "draft_detail_%s.png" % tag))["file"])
        st.close()
    if report.get("sockets"):
        m = render_muzzle(draft, report["sockets"], lo, hi, os.path.join(draft_dir, "draft_detail_muzzle.png"))
        if m:
            report["renders"].append(m)
    with open(os.path.join(draft_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    log("draft done: %s" % draft_dir)
    sys.exit(0)

# the bake source keeps every part at full detail: decimating first and baking from the decimated mesh threw away all
# of a seed's fine detail (the free pistol's 280k-face TRELLIS body came out melted at 40k with nothing to bake back,
# 2026-09-27). The decimated parts below become LOD0; these copies are what its maps are baked from.
full_parts = []
for o, _r in parts:
    c = o.copy()
    c.data = o.data.copy()
    bpy.context.collection.objects.link(c)
    c.name = o.name + "_full"
    full_parts.append(c)

# code parts over their share (the truck's tyre treads came to 120k triangles of a 100k budget, 2026-09-27): flat areas
# are dissolved first, which changes no shape, then the part is collapsed to its share by surface area
code = [(o, r) for o, r in parts if r["kind"] == "code"]
code_allow = int(budget * (0.6 if vendor else 0.9))
code_tris = sum(blib.tri_count(o) for o, _r in code)
if code_tris > code_allow:
    c_areas = [surface_area(o) for o, _r in code]
    for (o, r), a in zip(code, c_areas):
        share = max(300, int(code_allow * a / max(sum(c_areas), 1e-9)))
        have = blib.tri_count(o)
        if have <= share:
            continue
        m = o.modifiers.new("flat", "DECIMATE")
        m.decimate_type = "DISSOLVE"
        m.angle_limit = math.radians(0.5)
        m.delimit = {"UV", "MATERIAL", "SHARP"}
        blib.select_only([o])
        bpy.ops.object.modifier_apply(modifier="flat")
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(o.data)
        bm.free()
        decimate_to(o, share)
        sharp_by_angle(o)
        r["triangles_built"] = have
        r["triangles"] = blib.tri_count(o)
    log("code parts over their %d allowance: %d -> %d triangles" % (code_allow, code_tris, sum(blib.tri_count(o) for o, _r in code)))
    code_tris = sum(blib.tri_count(o) for o, _r in code)
# the glass, its shell and the cockpit lining join LOD0 after the bake: their triangles come out of the budget too (the
# Havoc's LOD0 ran 10% over, 2026-09-29); a lining is flat dark matte, so it is cut down first
for o, _r in liner_parts:
    decimate_to(o, max(1000, int(budget * 0.03)))
extra_tris = sum(blib.tri_count(o) for o, _r in glass_parts + liner_parts + frame_parts)
left = max(budget - code_tris - extra_tris, int(budget * 0.3))
areas = [surface_area(o) for o, _r in vendor]
for (o, r), a in zip(vendor, areas):
    share = max(2000, int(left * a / max(sum(areas), 1e-9)))
    r["triangles_seed"] = blib.tri_count(o)
    r["triangles"] = decimate_to(o, share)
for o, r in parts:
    r.setdefault("triangles", blib.tri_count(o))
log("parts: %d code (%d tris), %d vendor (%d tris after their share of %d), glass and lining %d tris" % (
    len(parts) - len(vendor), code_tris, len(vendor), sum(r["triangles"] for _o, r in vendor), left, extra_tris))

# ---------------------------------------------------------------- HIGH (parts as they are) and LOD0 (one atlas)
blib.select_only([o for o, _r in parts])
for o in [o for o, _r in parts] + full_parts:
    if not o.data.uv_layers:
        blib.select_only([o])
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
    o.data.uv_layers[0].name = "UVMap"
    while len(o.data.uv_layers) > 1:
        o.data.uv_layers.remove(o.data.uv_layers[1])


def tile_layout(sizes, gap=0.004):
    """Shelf-pack squares of relative side `sizes` into the unit square at the largest common scale that fits.
    -> [(u0, v0, side)] in input order."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i])
    lo, hi, best = 0.0, 4.0 / max(max(sizes), 1e-9), None
    for _ in range(40):
        k = (lo + hi) / 2
        x = y = row = 0.0
        pos, fits = {}, True
        for i in order:
            s = sizes[i] * k
            if x + s > 1.0 + 1e-9:
                x, y, row = 0.0, y + row + gap, 0.0
            if s > 1.0 or y + s > 1.0 + 1e-9:
                fits = False
                break
            pos[i] = (x, y, s)
            x += s + gap
            row = max(row, s)
        if fits:
            lo, best = k, pos
        else:
            hi = k
    return [best[i] for i in range(len(sizes))]


# the atlas: each part keeps its own unwrap inside a square tile sized by its surface area. Packing every island of every
# part together failed on the truck: thousands of tread islands, each with a margin, shrank to dots (7% of the atlas used)
tiles = tile_layout([math.sqrt(max(surface_area(o), 1e-12)) for o, _r in parts])
for (o, r), (u0, v0, side) in zip(parts, tiles):
    src = o.data.uv_layers["UVMap"]
    dst = o.data.uv_layers.new(name="Atlas")
    n = len(src.data)
    uv = np.empty(n * 2, np.float32)
    src.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lo_uv, hi_uv = uv.min(axis=0), uv.max(axis=0)
    span = np.maximum(hi_uv - lo_uv, 1e-9)
    pad = side * 0.01
    uv = (uv - lo_uv) / span.max() * (side - 2 * pad) + np.array([u0 + pad, v0 + pad])
    dst.data.foreach_set("uv", uv.ravel())
    r["atlas_tile"] = [round(u0, 4), round(v0, 4), round(side, 4)]
blib.select_only([o for o, _r in parts])
bpy.ops.object.join()
lod0 = bpy.context.view_layer.objects.active                  # the decimated parts, each in its atlas tile
lod0.name = "SM_" + NAME
blib.select_only(full_parts)
bpy.ops.object.join()
high = bpy.context.view_layer.objects.active                  # the same parts at full detail: the bake source
high.name = "MS_high"
high.data.uv_layers["UVMap"].active = True
high.data.uv_layers["UVMap"].active_render = True           # the source textures read their own unwrap
report["bake_source_triangles"] = blib.tri_count(high)
blib.select_only([lod0])
lod0.data.uv_layers.remove(lod0.data.uv_layers["UVMap"])
lod0.data.uv_layers["Atlas"].name = "UVMap"
lod0.data.uv_layers["UVMap"].active = True
lod0.data.uv_layers["UVMap"].active_render = True

size = int(args.get("atlas_size", 2048))


def texel_report(o, px):
    """Texel density of LOD0 in its atlas (blender/texel.py, 2026-10-04): px/cm per face in world metres, summarised
    per part by its atlas tile; a part far under the asset's mean is a gate warning."""
    me = o.data
    n = len(me.polygons)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    M = np.array(o.matrix_world)
    co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    tiles = [(r["name"], *r["atlas_tile"]) for _o, r in parts if r.get("atlas_tile")]
    return texel.summarize(texel.polygon_areas(co, lv, ls, lt), texel.uv_polygon_areas(uv, ls, lt), px, tiles,
                           texel.uv_centroids(uv, ls, lt))


try:
    report["texel_density"] = texel_report(lod0, size)
    log("texel density: %s px/cm mean, %s at the 10th percentile, %.0f%% of the %d px atlas used%s" % (
        report["texel_density"]["px_per_cm"], report["texel_density"]["p10_px_per_cm"],
        report["texel_density"]["atlas_used"] * 100, size,
        "; " + "; ".join(report["texel_density"]["warnings"]) if report["texel_density"]["warnings"] else ""))
except Exception as exc:  # noqa: BLE001 - a measurement, never a reason to stop the bake
    log("texel density not measured: %s" % exc)
lo, hi = blib.dims(high)
diag = (hi - lo).length


def new_image(tag, colour=True):
    img = bpy.data.images.new("T_%s_%s" % (NAME, tag), size, size, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    return img


final = bpy.data.materials.new("MI_" + NAME)
nt = final.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
lod0.data.materials.clear()
lod0.data.materials.append(final)
target = nt.nodes.new("ShaderNodeTexImage")
nt.nodes.active = target
scn = bpy.context.scene
scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = 1
blib.select_only([high, lod0])
bpy.context.view_layer.objects.active = lod0
# the margin grows with the atlas (a 4 px margin at 4096 let mipmaps bleed the gutter into the seams, Tonetta's bake)
bake_kw = dict(use_selected_to_active=True, cage_extrusion=diag * 0.0015, max_ray_distance=diag * 0.006,
               margin=max(4, size // 128), margin_type="ADJACENT_FACES", use_clear=True, target="IMAGE_TEXTURES")


def bake(tag, kind, colour, **extra):
    img = new_image(tag, colour)
    target.image = img
    bpy.ops.object.bake(type=kind, **bake_kw, **extra)
    return img


def route_to_emission(what):
    """Temporarily feed each HIGH material's `what` input (Base Color, Metallic) into an emission, so EMIT bakes it."""
    undo = []
    for m in {s.material for s in high.material_slots if s.material and s.material.node_tree}:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        outn = next((n for n in t.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if b is None or outn is None:
            continue
        prev = outn.inputs["Surface"].links[0].from_socket if outn.inputs["Surface"].is_linked else None
        e = t.nodes.new("ShaderNodeEmission")
        src = b.inputs[what]
        if src.is_linked:
            t.links.new(src.links[0].from_socket, e.inputs["Color"])
        else:
            v = src.default_value
            e.inputs["Color"].default_value = tuple(v)[:3] + (1,) if hasattr(v, "__len__") else (float(v),) * 3 + (1,)
        for l in list(outn.inputs["Surface"].links):
            t.links.remove(l)
        t.links.new(e.outputs["Emission"], outn.inputs["Surface"])
        undo.append((t, outn, prev, e))
    return undo


def restore(undo):
    for t, outn, prev, e in undo:
        for l in list(outn.inputs["Surface"].links):
            t.links.remove(l)
        if prev is not None:
            t.links.new(prev, outn.inputs["Surface"])
        t.nodes.remove(e)


# base colour through an emission: Cycles' diffuse colour pass is zero on metal, and every part planned as metal (the
# truck's painted body, the bullpup's steel) baked black (2026-09-27)
undo = route_to_emission("Base Color")
try:
    bc = bake("BC", "EMIT", True)
finally:
    restore(undo)
rough = bake("R", "ROUGHNESS", False)
undo = route_to_emission("Metallic")
try:
    metal = bake("M", "EMIT", False)
finally:
    restore(undo)


def bevel_normals(radius):
    """Blender's Bevel shader on every HIGH material's normal for the normal bake: every edge of the seed carries a
    small round in the baked normal map, without new geometry (Tonetta: "a perfectly sharp edge reads as fake",
    2026-09-29). -> undo list"""
    undo = []
    for m in {s.material for s in high.material_slots if s.material and s.material.node_tree}:
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None or m.get("ms_glass"):
            continue
        bev = t.nodes.new("ShaderNodeBevel")
        bev.samples = 8
        bev.inputs["Radius"].default_value = radius
        prev = b.inputs["Normal"].links[0].from_socket if b.inputs["Normal"].is_linked else None
        if prev is not None:
            t.links.new(prev, bev.inputs["Normal"])
        t.links.new(bev.outputs["Normal"], b.inputs["Normal"])
        undo.append((t, b, prev, bev))
    return undo


bev_undo = bevel_normals(float(args["bevel_m"])) if args.get("bevel_m") else []
try:
    normal = bake("N", "NORMAL", False, normal_space="TANGENT")
finally:
    for t, b, prev, bev in bev_undo:
        t.nodes.remove(bev)
        if prev is not None:
            t.links.new(prev, b.inputs["Normal"])
report["bevel_mm"] = round(float(args.get("bevel_m") or 0) * 1000, 2)
emit = bake("E", "EMIT", True) if EMISSIVE["strength"] > 0 else None
scn.cycles.samples = 16
scn.world = scn.world or bpy.data.worlds.new("World")
scn.world.light_settings.distance = max(diag * 0.015, 0.003)
ao = bake("AO", "AO", False)
nt.nodes.remove(target)


def pixels(img):
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


orm = new_image("ORM", False)
px = np.ones((size, size, 4), np.float32)
px[:, :, 0] = np.clip(0.35 + 0.65 * pixels(ao)[:, :, 0], 0, 1)          # contact shadow, never black
px[:, :, 1] = pixels(rough)[:, :, 0]
px[:, :, 2] = pixels(metal)[:, :, 0]
orm.pixels.foreach_set(px.ravel())
covered = pixels(ao)[:, :, 0] > 0.001            # texels a part landed on; the empty atlas is not the surface
report["roughness_mean"] = round(float(px[:, :, 1][covered].mean()), 3) if covered.any() else None
report["metallic_mean"] = round(float(px[:, :, 2][covered].mean()), 3) if covered.any() else None
report["atlas_coverage"] = round(float(covered.mean()), 3)
from normalfix import flip_inward  # noqa: E402 - pure numpy, tested
_npx = pixels(normal).copy()
report["normal_inward_share"] = round(flip_inward(_npx, covered), 4)
normal.pixels.foreach_set(_npx.ravel())
if report["normal_inward_share"]:
    log("normal map: %.2f%% of the texels faced into the surface (a thin sheet's back face) and were turned out"
        % (report["normal_inward_share"] * 100))


def dilate(img, covered, steps=None):
    """The gutter around each UV island filled with its neighbours' colour, so mipmaps do not darken or gloss the
    seams (Tonetta's texdetail.dilate): each step, every uncovered texel next to a covered one takes their mean."""
    a = pixels(img).copy()
    have = covered.copy()
    for _ in range(steps or max(8, img.size[0] // 128)):
        acc = np.zeros_like(a[:, :, :3])
        cnt = np.zeros(have.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            h_ = np.roll(have, (dy, dx), axis=(0, 1))
            acc += np.roll(a[:, :, :3], (dy, dx), axis=(0, 1)) * h_[:, :, None]
            cnt += h_
        grow = (~have) & (cnt > 0)
        if not grow.any():
            break
        a[:, :, :3][grow] = acc[grow] / cnt[grow][:, None]
        have |= grow
    img.pixels.foreach_set(a.ravel())


maps_out = [(bc, "BC"), (normal, "N"), (orm, "ORM")] + ([(emit, "E")] if emit is not None else [])
for img, tag in maps_out:
    dilate(img, covered)
for img, tag in maps_out:
    img.filepath_raw = os.path.join(OUT, "T_%s_%s.png" % (NAME, tag))
    img.file_format = "PNG"
    img.save()
    img.pack()
    report["maps"].append({"role": tag, "file": os.path.basename(img.filepath_raw), "size": [size, size]})
for img in (rough, metal, ao):
    bpy.data.images.remove(img)
t_bc = nt.nodes.new("ShaderNodeTexImage")
t_bc.image = bc
nt.links.new(t_bc.outputs["Color"], bsdf.inputs["Base Color"])
t_orm = nt.nodes.new("ShaderNodeTexImage")
t_orm.image = orm
sep = nt.nodes.new("ShaderNodeSeparateColor")
nt.links.new(t_orm.outputs["Color"], sep.inputs["Color"])
nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
t_n = nt.nodes.new("ShaderNodeTexImage")
t_n.image = normal
nm = nt.nodes.new("ShaderNodeNormalMap")
nt.links.new(t_n.outputs["Color"], nm.inputs["Color"])
nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
if emit is not None:
    t_e = nt.nodes.new("ShaderNodeTexImage")
    t_e.image = emit
    nt.links.new(t_e.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = EMISSIVE["strength"]
    report["emissive_strength"] = EMISSIVE["strength"]
bpy.data.objects.remove(high, do_unlink=True)

# glass parts keep a glass slot of their own, outside the atlas
for o, r in glass_parts:
    g = zone_glass_material(r.get("zone", "glass"), r.get("glass_kw") or {})
    o.data.materials.clear()
    o.data.materials.append(g)
    blib.select_only([lod0, o])
    bpy.context.view_layer.objects.active = lod0
    bpy.ops.object.join()
report["glass"] = {"parts": [r["name"] for _o, r in glass_parts]} if glass_parts else None
# the cockpit lining keeps a matte slot of its own too
for o, r in liner_parts:
    o.data.materials.clear()
    o.data.materials.append(interior_material("MI_%s_Interior" % NAME))
    blib.select_only([lod0, o])
    bpy.context.view_layer.objects.active = lod0
    bpy.ops.object.join()
report["lining"] = {"parts": [r["name"] for _o, r in liner_parts]} if liner_parts else None
# a rebuilt canopy's frame band: the body's planned paint, a slot of its own
for o, r in frame_parts:
    o.data.materials.clear()
    o.data.materials.append(frame_material())
    blib.select_only([lod0, o])
    bpy.context.view_layer.objects.active = lod0
    bpy.ops.object.join()
report["frame"] = {"parts": [r["name"] for _o, r in frame_parts]} if frame_parts else None
log("atlas %d baked: roughness %s, metallic %s, %.0f%% of the atlas used" % (size, report["roughness_mean"], report["metallic_mean"],
                                                                         report["atlas_coverage"] * 100))

# ---------------------------------------------------------------- LODs, collision, sockets
lo, hi = blib.dims(lod0)
report["dimensions_m"] = [round(v, 4) for v in (hi - lo)]


def lod_copy(src, ratio, name):
    o = src.copy()
    o.data = src.data.copy()
    o.name = name
    bpy.context.collection.objects.link(o)
    decimate_to(o, int(blib.tri_count(src) * ratio))
    return o


if args.get("wind_masks"):
    # a nature asset's wind masks in its vertex colour (2026-10-03, windmask.py): R the distance along the surface from
    # the holdfast, G blade flutter, B a phase per blade - made on LOD0 so the decimated LODs carry them
    from mathutils.bvhtree import BVHTree
    from windmask import masks as wind_masks  # noqa: E402 - pure numpy, tested
    me = lod0.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    nrm = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    ed = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    bm = bmesh.new()
    bm.from_mesh(me)
    tree = BVHTree.FromBMesh(bm)
    span = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
    eps = 1e-4 * span
    thick = np.full(n, np.inf)
    for i in range(n):
        d = Vector(nrm[i])
        hit = tree.ray_cast(Vector(co[i]) - d * eps, -d, span)
        if hit[0] is not None:
            thick[i] = hit[3] + eps
    bm.free()
    stem, flutter, phase = wind_masks(co, ed, thick)
    attr = me.color_attributes.new("WindMask", "FLOAT_COLOR", "POINT")
    attr.data.foreach_set("color", np.stack([stem, flutter, phase, np.ones(n, np.float32)], axis=1).ravel())
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = list(me.color_attributes).index(attr)
    report["wind_masks"] = {"stem_max": round(float(stem.max()), 3), "flutter_share": round(float((flutter > 0.4).mean()), 3),
                            "blades": int(len(np.unique(phase[flutter > 0.4]))) if (flutter > 0.4).any() else 0}
    log("wind masks: %s" % report["wind_masks"])

lod1 = lod_copy(lod0, 0.5, "SM_%s_LOD1" % NAME)
lod2 = lod_copy(lod1, 0.5, "SM_%s_LOD2" % NAME)
for i, o in enumerate((lod0, lod1, lod2)):
    report["lods"].append({"lod": i, "triangles": blib.tri_count(o)})
log("LODs: %s" % ", ".join(format(l["triangles"], ",") for l in report["lods"]))

co = np.empty(len(lod2.data.vertices) * 3, np.float32)
lod2.data.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
k = np.arange(48) + 0.5
phi, theta = np.arccos(1 - 2 * k / 48), math.pi * (1 + 5 ** 0.5) * k
dirs = np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)
proj = co @ dirs.T
pts = co[np.unique(np.concatenate([proj.argmax(axis=0), proj.argmin(axis=0)]))]
hull = bpy.data.objects.new("UCX_SM_%s_01" % NAME, bpy.data.meshes.new("UCX_SM_%s_01" % NAME))
bpy.context.collection.objects.link(hull)
bm = bmesh.new()
for pnt in pts:
    bm.verts.new(pnt.tolist())
bm.verts.ensure_lookup_table()
bmesh.ops.convex_hull(bm, input=bm.verts)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bmesh.ops.triangulate(bm, faces=bm.faces)
bm.to_mesh(hull.data)
bm.free()
report["collision"] = {"type": "convex", "triangles": blib.tri_count(hull)}


# ---------------------------------------------------------------- sockets and the origin
if IS_WEAPON:
    report["sockets"], report["muzzle"] = weapon_sockets([lod0], lo, hi)
    log("muzzle: %s; sockets %s" % (report["muzzle"], [s["name"] for s in report["sockets"]]))


def origin_point(mode, o):
    """Where the exported pivot goes, in the asset frame (the plan's centre is the default). "bottom" puts a vehicle on
    the ground plane; "mount" is the top centre of a pylon-mounted weapon's plate (Proteus's hardpoints, 2026-10-01: the
    plate's middle along X from its top 2% slab; a plate a degree off level put the topmost corner 5 cm off). -> Vector"""
    lo_, hi_ = blib.dims(o)
    c = (lo_ + hi_) * 0.5
    if mode == "bottom":
        return Vector((c.x, c.y, lo_.z))
    if mode == "top":
        return Vector((c.x, c.y, hi_.z))
    if mode == "rear":
        return Vector((lo_.x, c.y, c.z))
    if mode == "front":
        return Vector((hi_.x, c.y, c.z))
    if mode == "mount":
        co = np.empty(len(o.data.vertices) * 3, np.float32)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        slab = co[co[:, 2] > hi_.z - 0.02 * (hi_.z - lo_.z)]
        return Vector(((float(slab[:, 0].min()) + float(slab[:, 0].max())) / 2, c.y, hi_.z))
    if mode == "grip":
        g = next((q for q in report.get("sockets") or [] if q["name"] == "Grip"), None)
        if g is None:
            log("origin grip asked for but no part or zone is named Grip: kept at the centre")
            return Vector((0.0, 0.0, 0.0))
        return Vector(g["location"])
    return Vector((0.0, 0.0, 0.0))


ORIGIN = str(args.get("origin") or "centre")
pivot = origin_point(ORIGIN, lod0)
if pivot.length > 1e-9:
    for ob in (lod0, lod1, lod2, hull):
        ob.data.transform(Matrix.Translation(-pivot))
    for q in report.get("sockets") or []:
        q["location"] = [round(q["location"][i] - pivot[i], 4) for i in range(3)]
    lo, hi = blib.dims(lod0)
report["origin"] = {"mode": ORIGIN, "at_in_plan_frame_m": [round(v, 4) for v in pivot]}
# sockets as SOCKET_ empties under the mesh: Unreal makes them static-mesh sockets on import; they were only a list in
# report.json, and Proteus placed its muzzles by hand (2026-10-01)
socket_objs = []
for q in report.get("sockets") or []:
    e = bpy.data.objects.new("SOCKET_" + q["name"], None)
    bpy.context.collection.objects.link(e)
    e.empty_display_type = "ARROWS"
    e.empty_display_size = max(0.01, 0.03 * (hi.x - lo.x))
    e.location = q["location"]
    e.parent = lod0
    socket_objs.append(e)

# ---------------------------------------------------------------- renders: previews, detail views, the check views
blib.setup_render(int(args.get("render_size", 768)), 48, look="preview")
stage = blib.Stage(lod0, extra_hidden=[hull, lod1, lod2])
report["renders"] = [stage.render(v, os.path.join(OUT, "preview_%s.png" % v))["file"] for v in ("iso", "side", "front")]
stage.close()
span = hi.x - lo.x
detail = []
for tag, x0, x1 in (("front", hi.x - span * 0.4, hi.x), ("rear", lo.x, lo.x + span * 0.4)):
    st = blib.Stage(lod0, extra_hidden=[hull, lod1, lod2], focus_bounds=(Vector((x0, lo.y, lo.z)), Vector((x1, hi.y, hi.z))))
    name = "preview_detail_%s.png" % tag
    st.render("iso", os.path.join(OUT, name))
    st.close()
    detail.append(name)
if report.get("sockets"):
    # a weapon's muzzle end-on: where the open bore - or a lens, a cap, a glow in it - shows (owner, 2026-10-01: "the
    # laser cannon has some orange tip on it, should just be hollow")
    m = render_muzzle(lod0, report["sockets"], lo, hi, os.path.join(OUT, "preview_detail_muzzle.png"), hidden=[hull, lod1, lod2])
    if m:
        detail.append(m)
report["detail_renders"] = detail
# orthographic side and front on white, framed on the silhouette like the reference pictures, for the check step
blib.setup_render(int(args.get("check_size", 1024)), 16, look="probe")
cam = bpy.data.objects.new("CheckCam", bpy.data.cameras.new("CheckCam"))
bpy.context.collection.objects.link(cam)
scn.camera = cam
for o in (hull, lod1, lod2):
    o.hide_render = True
checks = {}
for view in ("left", "front", "top"):                   # top: parts off the centreline show only from above
    rec = blib.ortho_camera(cam, view, lo, hi, margin=1.08)
    path = os.path.join(OUT, "check_%s.png" % view)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    checks[view] = {"file": os.path.basename(path), "camera": rec}
report["check_renders"] = checks
bpy.data.objects.remove(cam, do_unlink=True)
for o in (hull, lod1, lod2):
    o.hide_render = False

# ---------------------------------------------------------------- exports
blib.select_only([lod0] + socket_objs)
p = os.path.join(OUT, "SM_%s.glb" % NAME)
try:
    # the wind masks stay out of the GLB: a glTF viewer multiplies COLOR_0 into the base colour and tinted the plants
    bpy.ops.export_scene.gltf(filepath=p, use_selection=True, export_format="GLB", export_yup=True, export_vertex_color="NONE")
except TypeError:
    bpy.ops.export_scene.gltf(filepath=p, use_selection=True, export_format="GLB", export_yup=True)
report["files"].append(os.path.basename(p))
if args.get("spec"):
    txt = bpy.data.texts.new("ms_spec.json")
    txt.write(json.dumps(args["spec"]))
if args.get("reference") and os.path.exists(args["reference"]):
    ref_img = bpy.data.images.load(os.path.abspath(args["reference"]))
    ref_img.name = "ms_reference"
    ref_img.pack()
    ref_img.use_fake_user = True
p = os.path.join(OUT, "SM_%s.blend" % NAME)
bpy.ops.wm.save_as_mainfile(filepath=p, compress=True)
report["files"].append(os.path.basename(p))
report["files"] += [m["file"] for m in report["maps"]]
report["engine"] = args.get("engine", "unreal")
report["materials"] = [m.name for m in lod0.data.materials if m]
# The FBX is written in centimetres with no scale on any node (2026-10-01, Proteus): Blender's exporter otherwise puts
# its metre -> centimetre factor of 100 on the nodes, and Unreal's Interchange made that a x100 root bone on a rigged
# weapon ("the weapons are massive"). The meshes are scaled to centimetres here and global_scale 0.01 cancels the
# exporter's own x100, so the file is raw centimetres with UnitScaleFactor 1, sockets included. The .blend and the GLB
# above stay in metres.
CM = 100.0
for ob in (lod0, lod1, lod2, hull):
    ob.data.transform(Matrix.Scale(CM, 4))
for e in socket_objs:
    e.location = e.location * CM
    e.empty_display_size *= CM
# use_tspace (2026-10-04, Mixar's Unreal preset): the tangents the normal map was baked against travel in the file, so
# Unreal's "import normals and tangents" reads the bake as Blender meant it instead of recomputing tangents at the seams
fbx_kw = dict(use_selection=True, apply_unit_scale=True, global_scale=0.01, apply_scale_options="FBX_SCALE_NONE",
              axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE", use_tspace=True, use_mesh_modifiers=True,
              path_mode="STRIP", embed_textures=False, add_leaf_bones=False, bake_anim=False)
if args.get("wind_masks"):
    fbx_kw["colors_type"] = "LINEAR"           # mask values, not colours: no sRGB curve on the way to Unreal
blib.select_only([lod0, hull] + socket_objs)
fbx_main = os.path.join(OUT, "SM_%s.fbx" % NAME)
bpy.ops.export_scene.fbx(filepath=fbx_main, **fbx_kw)
report["files"].append(os.path.basename(fbx_main))
for o in (lod1, lod2):
    blib.select_only([o])
    p = os.path.join(OUT, o.name + ".fbx")
    bpy.ops.export_scene.fbx(filepath=p, **fbx_kw)
    report["files"].append(os.path.basename(p))
report["fbx"] = {"units": "cm", "unit_scale_factor": 1.0, "sockets": ["SOCKET_" + q["name"] for q in report.get("sockets") or []],
                 "frame": "Blender +X forward, +Y left, +Z up; Unreal reads X forward, Y right, Z up"}


def fbx_check(path, want_m, sockets):
    """The exported FBX read back the way an importer reads it: its size must be the asset's size in metres and its
    sockets must all be there (a x100 file reads 100 times too long). Replaces the scene, so it runs last."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.name.startswith("UCX_")]
    if not meshes:
        return {"ok": False, "why": "no mesh read back"}
    bounds = [blib.dims(o) for o in meshes]
    got = [max(b[1][i] for b in bounds) - min(b[0][i] for b in bounds) for i in range(3)]
    ok = all(abs(g - w) <= 0.01 * max(w, 1e-3) for g, w in zip(sorted(got), sorted(want_m)))
    found = {o.name.split(".")[0] for o in bpy.context.scene.objects if o.type == "EMPTY" and o.name.startswith("SOCKET_")}
    missing = [n for n in ("SOCKET_" + q["name"] for q in sockets) if n not in found]
    # Blender's importer scales a centimetre file's root nodes by 0.01: a root read back at 0.01 had scale 1 in the
    # file; the x100 trap (a node scale of 100 that Unreal turns into a root bone) reads back at 1.0
    roots = [o for o in meshes if o.parent is None]
    node_scale = round(max(roots[0].matrix_world.to_scale()) / 0.01, 3) if roots else None
    return {"ok": ok and not missing and node_scale is not None and abs(node_scale - 1.0) < 0.01,
            "dims_m": [round(v, 4) for v in got], "node_scale": node_scale, "sockets_read": len(found), "missing": missing}


report["fbx_check"] = fbx_check(fbx_main, report["dimensions_m"], report.get("sockets") or [])
log("fbx read back: %s" % report["fbx_check"])
# the delivery gate (Tonetta's gate.py, 2026-09-29): measured, reported, never silently passed
warn = []
if report["lods"] and report["lods"][0]["triangles"] > int(args["tri_budget"]) * 1.05:
    warn.append("LOD0 %d tris over the %d budget" % (report["lods"][0]["triangles"], int(args["tri_budget"])))
roles = {m["role"] for m in report["maps"]}
warn += ["no %s map" % r for r in ("BC", "N", "ORM") if r not in roles]
want = float((args.get("spec") or {}).get("size_m") or 0)
got = max(report["dimensions_m"]) if SIZE_LONGEST and report.get("dimensions_m") else (report.get("dimensions_m") or [0])[0]
if want and report.get("dimensions_m") and abs(got - want) > 0.1 * want:
    warn.append("%s %.3f m is more than 10%% off the brief's %.3f m" % ("longest side" if SIZE_LONGEST else "length", got, want))
if ((args.get("spec") or {}).get("glass") or any((z.get("material") or {}).get("glass") for q in args["parts"] for z in q.get("zones") or [])) \
        and not report.get("glass"):
    warn.append("glass was asked for but none was made")
for z in report.get("glass_zones") or []:
    if not z.get("ok"):
        warn.append("glass zone %s is speckled or too big (%d panes hold %.0f%% of the pick, %.1f%% of the part)" % (
            z["zone"], z["islands"], z.get("coverage", 0) * 100, z.get("share_of_part", 0) * 100))
if report.get("roughness_mean") is not None and report["roughness_mean"] < 0.3:
    warn.append("mean roughness %.2f reads as glaze (under 0.3)" % report["roughness_mean"])
if (report.get("collision") or {}).get("triangles", 0) > 256:
    warn.append("collision hull %d tris (over 256)" % report["collision"]["triangles"])
warn += (report.get("texel_density") or {}).get("warnings") or []
mz = report.get("muzzle")
if mz is not None and not mz.get("open"):
    warn.append("the muzzle looks closed: %s end-on (preview_detail_muzzle.png); a shot must be able to leave the gun"
                % ("no recess" if not mz.get("found") else "only a pit %s mm deep" % ", ".join(str(b["depth_mm"]) for b in mz["bores"])))
if not (report.get("fbx_check") or {}).get("ok", True):
    warn.append("the FBX does not read back at the asset's size or with its sockets: %s" % report["fbx_check"])
report["gate"] = {"ok": not warn, "warnings": warn}
log("gate: %s" % ("ok" if not warn else "; ".join(warn)))
with open(os.path.join(OUT, "report.json"), "w") as f:
    json.dump(report, f, indent=1)
log("done")

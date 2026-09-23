"""Inside Blender: project repainted side pictures onto a textured vendor mesh and bake the result into the mesh's
own base-colour atlas.  blender -b --python repaint.py -- <args.json>
args: glb, out_glb, work_dir, name, bake_size, elevations {key: {"file", "R", "U", "S", "C"}}
For every material with a Principled BSDF, whatever feeds Base Color (the vendor's atlas) is mixed, per side, with the
side's picture mapped by u = dot(p - C, R) / S + 0.5, v = dot(p - C, U) / S + 0.5 (the render's own camera frame),
weighted by how squarely the face looks at that camera, the picture's alpha (the backdrop paints nothing) and a little
ambient occlusion (cavities take less). The mix is baked as diffuse colour into a new image on the mesh's UVs, the
material is rewired to it, roughness / metallic / normal stay as they were, and the GLB is exported."""
import json
import os
import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
WORK = args["work_dir"]
os.makedirs(WORK, exist_ok=True)
result = {"ok": False, "error": None, "notes": [], "materials": []}


def log(msg):
    print("[repaint] " + msg, flush=True)
    result["notes"].append(msg)


def done():
    json.dump(result, open(os.path.join(WORK, "repaint.json"), "w"), indent=1)
    print("[repaint] " + ("ok" if result["ok"] else "FAILED: " + str(result["error"])[-300:]), flush=True)


try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["glb"]))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    if not meshes:
        raise RuntimeError("no mesh in the seed")
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    blib.select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if not ob.data.uv_layers:
        raise RuntimeError("the seed has no UVs to bake into")
    lo, hi = blib.dims(ob)
    diag = max((hi - lo).length, 1e-4)
    ELEV = {}
    for key, rec in (args.get("elevations") or {}).items():
        if rec.get("file") and os.path.exists(rec["file"]):
            img = bpy.data.images.load(os.path.abspath(rec["file"]), check_existing=True)
            img.colorspace_settings.name = "sRGB"
            img.alpha_mode = "STRAIGHT"
            R, U = Vector(rec["R"]), Vector(rec["U"])
            ELEV[key] = {"img": img, "R": R, "U": U, "S": float(rec["S"]), "C": Vector(rec["C"]), "axis": U.cross(R).normalized() * -1.0}
    if not ELEV:
        raise RuntimeError("no side pictures")
    BAKE = int(args.get("bake_size", 2048))
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 1
    scn.render.bake.margin = 6
    scn.render.bake.use_clear = True
    targets = []
    for slot in ob.material_slots:
        m = slot.material
        if not m or not m.node_tree:
            continue
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None or not bsdf.inputs["Base Color"].is_linked:
            continue
        base_src = bsdf.inputs["Base Color"].links[0].from_socket
        # the mesh's atlas size decides the bake size (never below 2K)
        src_node = bsdf.inputs["Base Color"].links[0].from_node
        size = BAKE
        if src_node.type == "TEX_IMAGE" and src_node.image and src_node.image.size[0]:
            size = max(BAKE, min(4096, src_node.image.size[0]))
        tc = nt.nodes.new("ShaderNodeTexCoord")
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.samples = 6
        ao.inputs["Distance"].default_value = max(diag * 0.04, 0.01)

        def math_(op, a, b=None, clamp=False):
            n = nt.nodes.new("ShaderNodeMath")
            n.operation = op
            n.use_clamp = bool(clamp)
            for i, v in enumerate((a, b)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    n.inputs[i].default_value = float(v)
                else:
                    nt.links.new(v, n.inputs[i])
            return n.outputs[0]
        ao_fac = math_("MULTIPLY_ADD", ao.outputs["AO"], 0.6)
        ao_fac2 = math_("ADD", ao_fac, 0.4, clamp=True)
        cur = base_src
        for key, e in ELEV.items():
            rel = nt.nodes.new("ShaderNodeVectorMath")
            rel.operation = "SUBTRACT"
            nt.links.new(tc.outputs["Object"], rel.inputs[0])
            rel.inputs[1].default_value = tuple(e["C"])
            uv = []
            for vec in (e["R"], e["U"]):
                dn = nt.nodes.new("ShaderNodeVectorMath")
                dn.operation = "DOT_PRODUCT"
                nt.links.new(rel.outputs["Vector"], dn.inputs[0])
                dn.inputs[1].default_value = tuple(vec)
                uv.append(math_("ADD", math_("DIVIDE", dn.outputs["Value"], max(e["S"], 1e-6)), 0.5))
            comb = nt.nodes.new("ShaderNodeCombineXYZ")
            nt.links.new(uv[0], comb.inputs["X"])
            nt.links.new(uv[1], comb.inputs["Y"])
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = e["img"]
            t.extension = "CLIP"
            nt.links.new(comb.outputs["Vector"], t.inputs["Vector"])
            dot = nt.nodes.new("ShaderNodeVectorMath")
            dot.operation = "DOT_PRODUCT"
            nt.links.new(geo.outputs["Normal"], dot.inputs[0])
            dot.inputs[1].default_value = tuple(e["axis"])
            facing = math_("MULTIPLY", math_("SUBTRACT", dot.outputs["Value"], 0.72), 4.0, clamp=True)
            w = math_("MULTIPLY", math_("MULTIPLY", facing, t.outputs["Alpha"]), math_("MULTIPLY", ao_fac2, 0.8), clamp=True)
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            nt.links.new(w, mix.inputs["Factor"])
            nt.links.new(cur, mix.inputs[6])
            nt.links.new(t.outputs["Color"], mix.inputs[7])
            cur = mix.outputs[2]
        for l in list(bsdf.inputs["Base Color"].links):
            nt.links.remove(l)
        nt.links.new(cur, bsdf.inputs["Base Color"])
        img = bpy.data.images.new("T_%s_BC_repaint_%s" % (args.get("name", "Asset"), m.name), size, size, alpha=False)
        tnode = nt.nodes.new("ShaderNodeTexImage")
        tnode.image = img
        nt.nodes.active = tnode
        targets.append((m, bsdf, img, tnode))
    if not targets:
        raise RuntimeError("no material with a base colour to repaint")
    blib.select_only([ob])
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_clear=True, margin=6, target="IMAGE_TEXTURES")
    for m, bsdf, img, tnode in targets:
        nt = m.node_tree
        img.pack()
        for l in list(bsdf.inputs["Base Color"].links):
            nt.links.remove(l)
        nt.links.new(tnode.outputs["Color"], bsdf.inputs["Base Color"])
        # metallic goes to zero: the repainted colour carries the picture model's grey shading where it kept the render,
        # and the seed's speckled metallic map turned that into chrome (M4A1, 2026-09-19); the finish's material families
        # put steel back where the masks find it
        if not args.get("keep_metallic"):
            for l in list(bsdf.inputs["Metallic"].links):
                nt.links.remove(l)
            black = bpy.data.images.new("T_%s_M_zero_%s" % (args.get("name", "Asset"), m.name), 64, 64, alpha=False)
            black.colorspace_settings.name = "Non-Color"
            black.pixels.foreach_set([0.0, 0.0, 0.0, 1.0] * (64 * 64))
            black.pack()
            mnode = nt.nodes.new("ShaderNodeTexImage")
            mnode.image = black
            nt.links.new(mnode.outputs["Color"], bsdf.inputs["Metallic"])
            bsdf.inputs["Metallic"].default_value = 0.0
        # the projection chain now feeds nothing; drop it so the exporter does not pick a stray image
        for n in list(nt.nodes):
            if n.type in ("TEX_IMAGE",) and n is not tnode and not any(o.is_linked for o in n.outputs):
                nt.nodes.remove(n)
        result["materials"].append({"name": m.name, "bake": img.size[0]})
    log("baked the repaint into %d material(s)" % len(targets))
    out_glb = os.path.abspath(args["out_glb"])
    blib.select_only([ob])
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                              export_animations=False, export_skins=False)
    result["ok"] = True
    result["glb"] = out_glb
except Exception:  # noqa: BLE001
    result["error"] = traceback.format_exc()[-2000:]
done()

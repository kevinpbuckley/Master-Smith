"""A part authored in the asset frame (an SDF mesh, issue #12) -> registered.blend like a registered seed.
    blender -b -Y --python import_part.py -- <args.json>
args: {"glb", "material": {...plan material...}, "name", "out_blend", "out_render", "out_json"}
No registration: the GLB is already in the asset frame (X forward, Z up) and centred. It gets the planned material
(the same procedural one code parts got) and sharp edges by angle, so the assembler treats it like any vendor part."""
import json
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["glb"]))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
blib.select_only(meshes)
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
lo, hi = blib.dims(ob)
ob.data.transform(__import__("mathutils").Matrix.Translation(-(lo + hi) * 0.5))
ob.name = "Part"
ob.data.materials.clear()
ob.data.materials.append(blib.plan_material(args.get("name", "part"), args.get("material")))
# marching cubes tiles flat faces with tiny triangles: dissolve the planar ones (2 degrees keeps every real edge).
# A script's own triangles (kit.mesh_part) are kept: dissolved, a finely tessellated bubble turned faceted (2026-10-25)
blib.select_only([ob])
if args.get("dissolve", True):
    mod = ob.modifiers.new("planar", "DECIMATE")
    mod.decimate_type = "DISSOLVE"
    mod.angle_limit = math.radians(2.0)
    bpy.ops.object.modifier_apply(modifier="planar")
else:
    # 2026-10-26: a script's closed pieces that overlap (a faceted canopy's 40 crease bars, its sill and its arch) made
    # one piece by a self-union: apart, the report counted 39 islands, 12 of them "far" from the biggest
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    closed = all(len(e.link_faces) == 2 for e in bm.edges)
    bm.verts.ensure_lookup_table()
    seen, pieces = set(), 0
    for v0 in bm.verts:
        if v0.index in seen:
            continue
        pieces += 1
        stack = [v0]
        seen.add(v0.index)
        while stack:
            v = stack.pop()
            for e in v.link_edges:
                w = e.other_vert(v)
                if w.index not in seen:
                    seen.add(w.index)
                    stack.append(w)
    bm.free()
    if closed and pieces > 1:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.mesh.intersect_boolean(operation="UNION", use_self=True, solver="EXACT")
        except (RuntimeError, TypeError) as exc:
            print("[import_part] pieces not united: %s" % str(exc)[:120], flush=True)
        bpy.ops.object.mode_set(mode="OBJECT")
        print("[import_part] %d closed pieces united by a self-union" % pieces, flush=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.quads_convert_to_tris()
bpy.ops.object.mode_set(mode="OBJECT")
# crease what is really an edge. 2026-10-26: a script's own triangles at 6 degrees: at 30 the Mk II's faceted canopy
# (panes 8-26 degrees apart) shaded as one soft dome; a rim strip sampled every 2 cm turns under 4 degrees a step
# 2026-10-26 (hard r17): a script may set its own angle (kit.mesh_part(..., smooth=30): a curved glass bubble)
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(args.get("smooth_deg") or (30 if args.get("dissolve", True) else 6)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["out_blend"]), compress=True)
if args.get("out_render"):
    blib.setup_render(512, 24, look="preview")
    st = blib.Stage(ob, look="preview")
    st.render("iso", os.path.abspath(args["out_render"]))
    st.close()
lo, hi = blib.dims(ob)
json.dump({"triangles": blib.tri_count(ob), "size_m": [round(float(v), 5) for v in (hi - lo)]}, open(args["out_json"], "w"), indent=1)
print("[import_part] %d tris, %s mm" % (blib.tri_count(ob), [round(float(v) * 1000, 1) for v in (hi - lo)]), flush=True)

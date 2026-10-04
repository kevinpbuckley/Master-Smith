"""Measure the MetaHuman template meshes once and write what the offline tools need (inside Blender).
    blender -b --factory-startup -Y --python mh_template.py -- <args.json>
args: {"templates": dir with SKM_Body.fbx, SKM_Face.fbx, SM_MH_Head.fbx, "out": dir}
Writes template.json (bounds, counts, material slots, UV tiles, the neck seam), MH_Template.glb (body + face, metres,
Z up, facing -Y as Blender's FBX importer leaves an Unreal export) and template_<front|side>.png silhouettes.

Why: the templates were exported from UE 5.8.3 on 2026-10-04 while the editor was connected; the editor is not part of a
Master Smith build, so everything a conform needs to know about them is measured here and kept beside them."""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
tdir, out = args["templates"], args["out"]
os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)

report = {"units": "metres, Blender frame (Z up; the Unreal export faces -Y after import)", "meshes": {}}


def import_fbx(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(tdir, name + ".fbx"), use_anim=False, ignore_leaf_bones=True,
                             automatic_bone_orientation=False)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    arms = [o for o in new if o.type == "ARMATURE"]
    for o in meshes:
        o.name = name + "_" + o.name
    return meshes, arms


def measure(o, tag):
    lo, hi = blib.dims(o)
    me = o.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) @ np.array(o.matrix_world)[:3, :3].T + np.array(o.matrix_world)[:3, 3]
    slots = [s.material.name if s.material else "" for s in o.material_slots]
    mat_index = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("material_index", mat_index)
    tiles = {}
    if me.uv_layers:
        uv = np.empty(len(me.loops) * 2, np.float32)
        me.uv_layers[0].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        loop_start = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_start", loop_start)
        first = uv[loop_start]
        for i, s in enumerate(slots):
            sel = first[mat_index == i]
            if len(sel):
                u, v = np.floor(sel[:, 0]).astype(int), np.floor(sel[:, 1]).astype(int)
                tile = 1001 + int(np.median(u)) + 10 * int(np.median(v))
                tiles[s or ("slot%d" % i)] = {"udim": tile, "faces": int(len(sel)),
                                             "u": [round(float(sel[:, 0].min()), 3), round(float(sel[:, 0].max()), 3)],
                                             "v": [round(float(sel[:, 1].min()), 3), round(float(sel[:, 1].max()), 3)]}
    per_slot_z = {}
    for i, s in enumerate(slots):
        faces = np.where(mat_index == i)[0]
        if len(faces):
            vs = set()
            for f in faces[:: max(1, len(faces) // 4000)]:
                vs.update(me.polygons[int(f)].vertices)
            z = co[list(vs), 2]
            per_slot_z[s or ("slot%d" % i)] = [round(float(z.min()), 4), round(float(z.max()), 4)]
    report["meshes"][tag] = {
        "object": o.name, "vertices": n, "triangles": blib.tri_count(o), "polygons": len(me.polygons),
        "bounds_min": [round(v, 4) for v in lo], "bounds_max": [round(v, 4) for v in hi],
        "height_m": round(hi.z - lo.z, 4), "material_slots": slots, "uv_tiles": tiles, "slot_z_range": per_slot_z,
        "uv_layers": [l.name for l in me.uv_layers],
    }
    return co


body, body_arm = import_fbx("SKM_Body")
face, face_arm = import_fbx("SKM_Face")
head, _ = import_fbx("SM_MH_Head")
# the importer leaves the centimetre -> metre scale on the objects (0.01); bake it into the data so the GLB carries
# identity nodes (the conform overlay read the template 100x too big off the node scale, 2026-10-04)
bpy.context.view_layer.update()
for o in body + face + head:
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
    for mod in list(o.modifiers):
        o.modifiers.remove(mod)
# after import the template faces -Y (its toes and hands point to -Y): the frame every ms character uses
for o in body:
    co = measure(o, "body")
    # the neck seam: the body's top ring
    report["body_neck_seam_z_m"] = round(float(co[:, 2].max()), 4)
    # the A-pose read off the mesh: the armpit is the lowest point of the torso-arm fork; the hands are the furthest
    # points sideways
    x = co[:, 0]
    report["body_half_span_m"] = round(float(np.abs(x).max()), 4)
for o in face:
    measure(o, "face")
for o in head:
    measure(o, "head_static")

# silhouettes for the overlay: body + face together, front and side, white on black (the conform tool compares a
# seed's silhouette with these)
for o in head:
    o.hide_render = True
for a in body_arm + face_arm:
    a.hide_render = True
targets = body + face
lo = np.min([np.array(blib.dims(o)[0]) for o in targets], axis=0)
hi = np.max([np.array(blib.dims(o)[1]) for o in targets], axis=0)
lo, hi = Vector(lo.tolist()), Vector(hi.tolist())
report["template_bounds_min"] = [round(v, 4) for v in lo]
report["template_bounds_max"] = [round(v, 4) for v in hi]
report["template_height_m"] = round(hi.z - lo.z, 4)
scn = bpy.context.scene
scn.render.engine = "BLENDER_WORKBENCH"
scn.display.shading.light = "FLAT"
scn.display.shading.color_type = "SINGLE"
scn.display.shading.single_color = (1, 1, 1)
scn.render.film_transparent = False
w = bpy.data.worlds.new("W")
scn.world = w
w.color = (0, 0, 0)
scn.view_settings.view_transform = "Standard"
scn.render.resolution_x = scn.render.resolution_y = int(args.get("size", 1024))
scn.render.image_settings.color_mode = "RGB"
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
bpy.context.collection.objects.link(cam)
scn.camera = cam
for view in ("front", "side", "back"):
    # the template faces -Y: blib's "left" camera (at -Y) sees the face, "front" (at +X) the profile, "right" the back
    v = {"front": "left", "side": "front", "back": "right"}[view]
    blib.ortho_camera(cam, v, lo, hi, margin=1.05)
    scn.render.filepath = os.path.join(out, "template_%s.png" % view)
    bpy.ops.render.render(write_still=True)
    report["silhouette_%s" % view] = os.path.basename(scn.render.filepath)
report["silhouette_frame"] = "orthographic, the template's bounds with a 5% margin; 'front' is the camera at -Y looking at the face"
report["facing"] = "-Y (Blender), feet toward -Y; the Unreal export imports this way and every ms character uses the same frame"

# one GLB of body + face in metres for the tools (no armature: the skeleton JSONs carry the bones)
blib.select_only(targets)
bpy.ops.export_scene.gltf(filepath=os.path.join(out, "MH_Template.glb"), use_selection=True, export_format="GLB",
                          export_apply=True, export_skins=False, export_animations=False, export_materials="NONE")
report["glb"] = "MH_Template.glb"
json.dump(report, open(os.path.join(out, "template.json"), "w", encoding="utf-8"), indent=1)
print("[mh_template] height %.3f m, neck seam %.3f m, body %d tris, face %d tris" % (
    report["template_height_m"], report["body_neck_seam_z_m"], report["meshes"]["body"]["triangles"],
    report["meshes"]["face"]["triangles"]), flush=True)

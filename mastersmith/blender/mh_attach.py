"""An accessory (hair, horns, ears, armour, a mohawk) rigged onto a built MetaHuman's skeleton (inside Blender):
    blender -b --factory-startup -Y --python mh_attach.py -- <args.json>
args: {"built_fbx": the built MetaHuman's body or face skeletal mesh exported from Unreal (Asset Actions > Export; it
                    carries the skeleton), "accessory": the accessory mesh (.glb/.fbx/.obj/.blend) already in the
                    MetaHuman's frame (metres, Z up, facing -Y: the conform's frame), "name", "part": "Hair",
       "out_dir", "bone": "head" | "<bone name>" | "transfer", "offset_m": [x, y, z], "decimate_to": triangles (0 = keep)}
Writes SK_<Name>_<Part>.fbx (centimetres, the MetaHuman skeleton named root, no leaf bones, no textures), the maps the
accessory carried beside it, attach_report.json (bounds, the bone or the transfer, the read-back) and
attach_<front|side>.png (the accessory on the MetaHuman).

Why (the video, 2026-10-04): anything that is not skin - hair, ears that are not human, branches, armour - is removed
before the conform and comes back as its own skeletal mesh weighted to the MetaHuman's bones, dropped onto the
MetaHuman Blueprint's Body component; a rigid piece is 100% on one bone (head), a piece over the face or the body
takes the MetaHuman mesh's own weights. Export without leaf bones or the skeleton will not match."""
import json
import os
import shutil
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402


def plain(o):
    """numpy scalars as JSON values (a numpy bool is not JSON serializable)."""
    return o.item() if hasattr(o, "item") else str(o)

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME, PART = args["name"], args.get("part") or "Accessory"
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
CM = 100.0
report = {"name": NAME, "part": PART, "notes": []}


def log(msg):
    print("[mh_attach] " + msg, flush=True)
    report["notes"].append(msg)


def load_any(path):
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        with bpy.data.libraries.load(os.path.abspath(path)) as (src, dst):
            dst.objects = [n for n in src.objects]
        for o in dst.objects:
            if o is not None:
                bpy.context.collection.objects.link(o)
        return [o for o in dst.objects if o is not None and o.type == "MESH"]
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=os.path.abspath(path))
    objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    # whatever transform the importer left on the objects or their parents (a 0.01 unit scale on an FBX root)
    # goes into the mesh data: every tool here works on data in metres with identity objects
    bpy.context.view_layer.update()
    for o in objs:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    return objs


bpy.ops.wm.read_factory_settings(use_empty=True)
# the MetaHuman: its armature and its LOD0 mesh. Every bone is kept: "head" and the finger tips are leaf bones of the
# body skeleton and the importer's leaf-bone filter dropped them (322 of 342 bones, 2026-10-04)
bpy.ops.import_scene.fbx(filepath=os.path.abspath(args["built_fbx"]), use_anim=False, ignore_leaf_bones=False)
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if not arms:
    raise RuntimeError("%s has no skeleton: export the built MetaHuman's skeletal mesh, not a static one" % args["built_fbx"])
arm = arms[0]
mh_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
mh = max(mh_meshes, key=lambda o: len(o.data.polygons))
for o in mh_meshes:
    if o is not mh:
        bpy.data.objects.remove(o, do_unlink=True)
# into metres with identity transforms: the importer leaves the centimetre scale on the armature object (0.01) and the
# mesh under it; bake both into the data so the accessory, the weights and the export all work in one frame
bpy.context.view_layer.update()
mh.data.transform(mh.matrix_world)
mh.parent = None
mh.matrix_world = Matrix.Identity(4)
for mod in list(mh.modifiers):
    mh.modifiers.remove(mod)
# the importer may hang the armature under an empty that carries the 0.01: keep the world transform, drop the parent,
# then apply it into the bones (applying the armature alone left the 0.01 on the parent, 2026-10-04)
mw = arm.matrix_world.copy()
arm.parent = None
arm.matrix_world = mw
blib.select_only([arm])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()
log("armature in metres: scale %s, bounds %s" % ([round(v, 3) for v in arm.matrix_world.to_scale()], [round(v, 3) for v in blib.dims(mh)[1]]))
bone_names = [b.name for b in arm.data.bones]
report["skeleton_bones"] = len(bone_names)
log("MetaHuman %s: %d bones, mesh %s with %d faces" % (os.path.basename(args["built_fbx"]), len(bone_names), mh.name, len(mh.data.polygons)))

acc = load_any(args["accessory"])
if not acc:
    raise RuntimeError("no mesh in %s" % args["accessory"])
blib.select_only(acc)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if len(acc) > 1:
    bpy.ops.object.join()
acc = bpy.context.view_layer.objects.active
acc.name = acc.data.name = "SK_%s_%s" % (NAME, PART)
acc.parent = None
off = args.get("offset_m") or [0, 0, 0]
if any(off):
    acc.data.transform(Matrix.Translation(Vector(off)))
    log("moved by %s m" % off)
acc.matrix_world = Matrix.Identity(4)
if int(args.get("decimate_to") or 0) and blib.tri_count(acc) > int(args["decimate_to"]):
    before = blib.tri_count(acc)
    mod = acc.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = int(args["decimate_to"]) / before
    bpy.ops.object.modifier_apply(modifier=mod.name)
    log("decimated %d -> %d triangles" % (before, blib.tri_count(acc)))
alo, ahi = blib.dims(acc)
mlo, mhi = blib.dims(mh)
report["accessory_bounds_m"] = [[round(v, 3) for v in alo], [round(v, 3) for v in ahi]]
report["metahuman_bounds_m"] = [[round(v, 3) for v in mlo], [round(v, 3) for v in mhi]]
report["triangles"] = blib.tri_count(acc)
if ahi.z < mlo.z or alo.z > mhi.z + 0.3:
    log("WARNING the accessory does not overlap the MetaHuman in height: is it in the conform's frame (metres, feet at z=0)?")

# --- weights
mode = (args.get("bone") or "head").strip()
for vg in list(acc.vertex_groups):
    acc.vertex_groups.remove(vg)
if mode.lower() == "transfer":
    for b in bone_names:
        acc.vertex_groups.new(name=b)
    mod = acc.modifiers.new("Weights", "DATA_TRANSFER")
    mod.object = mh
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    blib.select_only([acc])
    bpy.ops.object.modifier_apply(modifier=mod.name)
    used = {g.group for v in acc.data.vertices for g in v.groups if g.weight > 0.001}
    for vg in list(acc.vertex_groups):
        if vg.index not in used:
            acc.vertex_groups.remove(vg)
    report["weights"] = {"mode": "transfer", "from": mh.name, "groups": len(acc.vertex_groups)}
    log("weights transferred from %s (%d bone groups)" % (mh.name, len(acc.vertex_groups)))
else:
    bone = mode if mode in bone_names else ("head" if "head" in bone_names else None)
    if bone is None:
        raise RuntimeError("bone %s is not in the skeleton (%s...)" % (mode, ", ".join(bone_names[:12])))
    if bone != mode:
        log("bone %s not found: weighted to head" % mode)
    vg = acc.vertex_groups.new(name=bone)
    vg.add(list(range(len(acc.data.vertices))), 1.0, "REPLACE")
    report["weights"] = {"mode": "bone", "bone": bone}
    log("100%% on %s" % bone)
arm.name = "root"            # Unreal matches the skeleton by its root; a Blender armature named otherwise adds a bone

# --- renders: the accessory (tinted orange) on the MetaHuman (grey), the face view and the profile
blib.setup_render(int(args.get("size", 768)), 32, look="preview")
grey = bpy.data.materials.new("MetaHumanGrey")
grey.use_nodes = True
grey.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1)
mh.data.materials.clear()
mh.data.materials.append(grey)
acc_mat = bpy.data.materials.new("AccessoryTint")
acc_mat.use_nodes = True
acc_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.85, 0.35, 0.2, 1)
kept_materials = [m for m in acc.data.materials]
acc.data.materials.clear()
acc.data.materials.append(acc_mat)
blib.select_only([mh, acc])
stage = blib.Stage(mh, look="preview")
acc.hide_render = False          # the Stage hides every mesh but its target; the accessory is the point of the picture
cam = bpy.data.objects.new("ViewCam", bpy.data.cameras.new("ViewCam"))
bpy.context.collection.objects.link(cam)
lo = Vector((min(alo.x, mlo.x), min(alo.y, mlo.y), min(alo.z, mlo.z)))
hi = Vector((max(ahi.x, mhi.x), max(ahi.y, mhi.y), max(ahi.z, mhi.z)))
scn = bpy.context.scene
renders = {}
# a character faces -Y in this frame: blib's "left" camera (at -Y) sees the face, its "front" camera (at +X) the profile
for view, cv in (("front", "left"), ("side", "front")):
    blib.ortho_camera(cam, cv, lo, hi, margin=1.06)
    scn.camera = cam
    path = os.path.join(OUT, "attach_%s.png" % view)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[view] = os.path.basename(path)
stage.close()
report["renders"] = renders
acc.data.materials.clear()
for m in kept_materials:
    acc.data.materials.append(m)

# --- export: centimetres with no node scale (rig_weapon.py's recipe, 2026-10-01), the armature and the accessory only.
# Scale both to centimetres FIRST, then parent: the data in cm, every object at identity (setting the imported
# armature's 0.01 scale to 100 and applying it made the file 100x too big, 2026-10-04)
bpy.data.objects.remove(mh, do_unlink=True)
acc.data.transform(Matrix.Scale(CM, 4))
arm.scale = (CM, CM, CM)
blib.select_only([arm])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.context.view_layer.update()
log("before export: armature scale %s, %d bones, accessory %s cm" % (
    [round(v, 3) for v in arm.matrix_world.to_scale()], len(arm.data.bones), [round(v, 1) for v in (blib.dims(acc)[1] - blib.dims(acc)[0])]))
acc.parent = arm
acc.matrix_parent_inverse = Matrix.Identity(4)
mod = acc.modifiers.new("Armature", "ARMATURE")
mod.object = arm
blib.select_only([arm, acc])
maps = []
for m in acc.data.materials:
    if m and m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and n.image.has_data:
                p = os.path.join(OUT, "T_%s_%s_%s.png" % (NAME, PART, "BC" if "Base Color" in [l.to_socket.name for l in n.outputs["Color"].links] else n.image.name[:12]))
                n.image.filepath_raw = p
                n.image.file_format = "PNG"
                n.image.save()
                maps.append(os.path.basename(p))
sk = os.path.join(OUT, "SK_%s_%s.fbx" % (NAME, PART))
bpy.ops.export_scene.fbx(filepath=sk, use_selection=True, object_types={"ARMATURE", "MESH"}, apply_unit_scale=True,
                         global_scale=0.01, apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y",
                         add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X", use_armature_deform_only=False,
                         mesh_smooth_type="FACE", use_mesh_modifiers=False, path_mode="STRIP", embed_textures=False, bake_anim=False,
                         use_tspace=True)
report["fbx"] = os.path.basename(sk)
report["maps"] = maps

# --- read back: the file's own size and root scale
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sk, use_anim=False, ignore_leaf_bones=False)
rarm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
rmesh = next((o for o in bpy.data.objects if o.type == "MESH"), None)
if rarm is None or rmesh is None:
    report["fbx_check"] = {"ok": False, "why": "no armature or mesh read back"}
else:
    bpy.context.view_layer.update()
    rlo, rhi = blib.dims(rmesh)
    sz = [round(v, 3) for v in (rhi - rlo)]
    want = [round(v, 3) for v in (ahi - alo)]
    # Blender's importer scales a centimetre file's root by 0.01; the x100 trap reads back at 1.0 (rig_weapon.py)
    node = round(max(rarm.matrix_world.to_scale()) / 0.01, 3)
    report["fbx_check"] = {"ok": all(abs(a - b) < 0.02 * max(1e-3, b) + 0.002 for a, b in zip(sz, want)) and abs(node - 1.0) < 0.01,
                           "size_m": sz, "wanted_m": want, "bones": len(rarm.data.bones), "root": rarm.name, "root_node_scale": node,
                           "mesh_node_scale": [round(v, 4) for v in rmesh.matrix_world.to_scale()], "mesh_parent": rmesh.parent.name if rmesh.parent else None}
log("read back: %s" % report["fbx_check"])
json.dump(report, open(os.path.join(OUT, "attach_report.json"), "w", encoding="utf-8"), indent=1, default=plain)
log("%s -> %s" % (PART, sk))

"""A fitted garment skinned onto the built MetaHuman's skeleton and written as a drop-in skeletal mesh FBX (in Blender):
    blender -b --factory-startup -Y --python-exit-code 1 --python garment_attach.py -- <args.json>
args: {"built_fbx": the built body skeletal mesh FBX from Unreal, "garment": fitted.blend (garment_fit.py: the mesh with
       the body's weights as vertex groups) or a mesh file in the conform's frame (then the weights are transferred),
       "name", "part", "out_dir", "maps": [texture PNGs to copy beside the FBX]}
Writes SK_<Name>_<Part>.fbx, attach_report.json (the read-back and the raw bone-by-bone bind check against the body FBX).

Why (2026-10-06): mh_attach.py exports with Blender's Y-up axis conversion, which lands on the armature null as a
-90 degree X rotation that Unreal must convert back, and Blender's head/tail/roll bones lose up to 0.14 degrees on the
MetaHuman's right thigh twists; the AINavigator's skinned headset came back 90 degrees off through that route. Here the
FBX is written in Unreal's own axis system (Z up, front -Y, the one its FBX export declares) so Unreal converts nothing,
the skeleton's top node is "root" (Unreal takes it as the root bone, as the body has), and every bone's local transform,
bind pose and cluster link is then copied from the body FBX itself (fbx_patch_bones.py): the garment's bind pose is the
body's to the last digit, a drop-in for the MetaHuman skeleton under leader pose."""
import json
import os
import shutil
import sys

import bpy
import numpy as np
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "mastersmith", "blender"))
sys.path.insert(0, os.path.join(ROOT, "mastersmith"))   # fbx_patch_bones.py / fbx_bind_check.py live beside ms.py
import blib  # noqa: E402
import fbx_bind_check  # noqa: E402
import fbx_patch_bones  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
NAME, PART = args["name"], args.get("part", "Outfit")
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
CM = 100.0
report = {"name": NAME, "part": PART, "notes": []}


def log(msg):
    print("[garment_attach] " + msg, flush=True)
    report["notes"].append(msg)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.abspath(args["built_fbx"]), use_anim=False, ignore_leaf_bones=False)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
body = max(meshes, key=lambda o: len(o.data.polygons))
bpy.context.view_layer.update()
body.data.transform(body.matrix_world)
body.parent = None
body.matrix_world = Matrix.Identity(4)
for o in meshes:
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
mw = arm.matrix_world.copy()
arm.parent = None
arm.matrix_world = mw
blib.select_only([arm])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o, do_unlink=True)
for pb in arm.pose.bones:
    pb.matrix_basis = Matrix.Identity(4)
bpy.context.view_layer.update()
bone_names = [b.name for b in arm.data.bones]
log("body %s: %d bones (Blender keeps the FBX's Root node 'root' as the armature object)" % (os.path.basename(args["built_fbx"]), len(bone_names)))

# the garment
src = os.path.abspath(args["garment"])
before = set(bpy.data.objects)
if src.lower().endswith(".blend"):
    with bpy.data.libraries.load(src) as (dfrom, dto):
        dto.objects = [n for n in dfrom.objects]
    for o in dto.objects:
        if o is not None and o.type == "MESH":
            bpy.context.collection.objects.link(o)
    gar = next(o for o in bpy.data.objects if o not in before and o.type == "MESH")
    weights = "the fit's (garment_fit.py v6: rays into the posed body, labels and bands, armpit and crotch zones, the collar on spine_05/neck_01/neck_02; 8 influences)"
else:
    bpy.ops.import_scene.gltf(filepath=src)
    gar = next(o for o in bpy.data.objects if o not in before and o.type == "MESH")
    bpy.context.view_layer.update()
    gar.data.transform(gar.matrix_world)
    gar.parent = None
    gar.matrix_world = Matrix.Identity(4)
    for b in bone_names:
        gar.vertex_groups.new(name=b)
    mod = gar.modifiers.new("Weights", "DATA_TRANSFER")
    mod.object = body
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    blib.select_only([gar])
    bpy.ops.object.modifier_apply(modifier=mod.name)
    weights = "transferred from the body (nearest face, interpolated)"
gar.name = gar.data.name = "SK_%s_%s" % (NAME, PART)
missing = [vg.name for vg in gar.vertex_groups if vg.name not in bone_names]
if missing:
    raise RuntimeError("the garment's weights name bones the body skeleton lacks: %s" % missing[:8])
blib.select_only([gar])
bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=8)
bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
used = {g.group for v in gar.data.vertices for g in v.groups if g.weight > 0}
for vg in list(gar.vertex_groups):
    if vg.index not in used:
        gar.vertex_groups.remove(vg)
infl = max(len([g for g in v.groups if g.weight > 0]) for v in gar.data.vertices)
report["weights"] = {"source": weights, "groups": len(gar.vertex_groups), "max_influences": infl}
lo, hi = blib.dims(gar)
report["garment_bounds_m"] = [[round(v, 4) for v in lo], [round(v, 4) for v in hi]]
report["triangles"] = blib.tri_count(gar)
log("garment %s: %d triangles, %d bone groups, at most %d influences" % (gar.name, report["triangles"], len(gar.vertex_groups), infl))

# --- export in Unreal's own axis system, centimetres in the data, no node scale
bpy.data.objects.remove(body, do_unlink=True)
gar.data.transform(Matrix.Scale(CM, 4))
arm.scale = (CM, CM, CM)
blib.select_only([arm])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
arm.name = "root"            # the skeleton's top node: Unreal takes this null as the root bone, the body's "root"
gar.parent = arm
gar.matrix_parent_inverse = Matrix.Identity(4)
for m in list(gar.modifiers):
    gar.modifiers.remove(m)
mod = gar.modifiers.new("Armature", "ARMATURE")
mod.object = arm
for m in gar.data.materials:
    if m:
        # one slot per region (garment_fit v6: Jacket, Shirt, Trousers, Boots), named MI_<Name>_<Part>_<Region>
        if not m.name.startswith("MI_%s_%s" % (NAME, PART)):
            m.name = "MI_%s_%s" % (NAME, PART)
        m.use_backface_culling = False
blib.select_only([arm, gar])
raw = os.path.join(OUT, "SK_%s_%s.blender.fbx" % (NAME, PART))
sk = os.path.join(OUT, "SK_%s_%s.fbx" % (NAME, PART))
bpy.ops.export_scene.fbx(filepath=raw, use_selection=True, object_types={"ARMATURE", "MESH"}, apply_unit_scale=True,
                         global_scale=0.01, apply_scale_options="FBX_SCALE_NONE", axis_forward="Y", axis_up="Z",
                         add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X", use_armature_deform_only=False,
                         mesh_smooth_type="FACE", use_mesh_modifiers=False, path_mode="STRIP", embed_textures=False,
                         bake_anim=False, use_tspace=True)
patch = fbx_patch_bones.patch(os.path.abspath(args["built_fbx"]), raw, sk)
report["bone_patch"] = patch
log("bones copied from the body FBX: %s" % patch)
os.remove(raw)
maps = []
for mp in args.get("maps") or []:
    if os.path.exists(mp):
        dst = os.path.join(OUT, os.path.basename(mp))
        if os.path.abspath(mp) != dst:
            shutil.copy2(mp, dst)
        maps.append(os.path.basename(mp))
report["fbx"] = os.path.basename(sk)
report["maps"] = maps

# --- read back: Blender's view (size, node scale) and the raw bind pose against the body, bone by bone
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sk, use_anim=False, ignore_leaf_bones=False)
rarm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
rmesh = next((o for o in bpy.data.objects if o.type == "MESH"), None)
bpy.context.view_layer.update()
rlo, rhi = blib.dims(rmesh)
sz = [round(v, 3) for v in (rhi - rlo)]
want = [round(v, 3) for v in (hi - lo)]
node = round(max(rarm.matrix_world.to_scale()) / 0.01, 3)
report["fbx_check"] = {"ok": all(abs(a - b) < 0.02 * max(1e-3, b) + 0.002 for a, b in zip(sz, want)) and abs(node - 1.0) < 0.01,
                       "size_m": sz, "wanted_m": want, "bones": len(rarm.data.bones), "root": rarm.name, "root_node_scale": node,
                       "materials": [m.name for m in rmesh.data.materials if m]}
ref, cand = fbx_bind_check.read(os.path.abspath(args["built_fbx"])), fbx_bind_check.read(sk)
cmp_ = {s: fbx_bind_check.compare(ref, cand, s) for s in ("bind", "link", "nodes")}
summ = fbx_bind_check.summary(cand)
report["bind_check"] = {
    "axes_same_as_body": fbx_bind_check.summary(ref)["axes"] == summ["axes"],
    "unit_cm_per_unit": summ["unit_cm_per_unit"], "skeleton_chain": summ["skeleton_chains"], "nodes_above_first_bone": summ["nodes_above_first_bone"],
    "meshes": summ["meshes"],
    **{s: {k: v for k, v in c.items() if k in ("max_rot_deg", "max_off_cm", "max_scale_ratio", "common", "only_in_a", "only_in_b", "parent_mismatch")}
       for s, c in cmp_.items()}}
b = cmp_["bind"]
report["drop_in"] = bool(report["bind_check"]["axes_same_as_body"] and b["max_rot_deg"] < 1e-3 and b["max_off_cm"] < 1e-3
                         and not b["only_in_b"] and not b["parent_mismatch"]
                         and all(n["name"] == "root" and n["lcl_r"] == [0.0, 0.0, 0.0] and n["lcl_s"] == [1.0, 1.0, 1.0]
                                 and n["lcl_t"] == [0.0, 0.0, 0.0] for n in summ["nodes_above_first_bone"]))
log("read back: %s" % report["fbx_check"])
log("bind pose against the body: max %.6f deg, %.6f cm over %d bones; axes same: %s; drop-in: %s" % (
    b["max_rot_deg"], b["max_off_cm"], b["common"], report["bind_check"]["axes_same_as_body"], report["drop_in"]))
json.dump(report, open(os.path.join(OUT, "attach_%s_report.json" % PART), "w", encoding="utf-8", newline="\n"), indent=1,
          default=lambda o: o.item() if hasattr(o, "item") else str(o))
log("%s -> %s" % (PART, sk))

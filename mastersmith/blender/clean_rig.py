"""Inside Blender: make a vendor's rigged character ours.
    -- <args.json> with {"glb", "name", "out_dir", "skeleton": "ue5"|"vendor", "animations": [glb paths]}
- drop stray meshes that are not skinned (Meshy ships a 42-vertex icosphere)
- normalise to metres (Meshy delivers centimetres) so the GLB matches the static mesh and UE gets 1 m = 100 cm
- add a `root` bone at the origin above the hips
- for Unreal, rename bones to UE5 Mannequin names so IK Rig / IK Retargeter maps them by name
- re-export SK_<Name>.glb/.fbx, and each animation clip as A_<Name>_<clip>.fbx through the same renaming, so
  skeleton and clips agree."""
import json
import os
import sys

import bpy

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME, OUT = args["name"], args["out_dir"]
SKELETON = args.get("skeleton", "vendor")

# Meshy / Mixamo naming -> UE5 Mannequin naming. Hierarchy is left as the vendor made it (the clips
# depend on it); names are what the retargeter maps by.
UE5 = {"Hips": "pelvis", "Spine02": "spine_01", "Spine": "spine_02", "Spine1": "spine_03", "Spine2": "spine_04",
       "neck": "neck_01", "Neck": "neck_01", "Head": "head",
       "LeftShoulder": "clavicle_l", "LeftArm": "upperarm_l", "LeftForeArm": "lowerarm_l", "LeftHand": "hand_l",
       "RightShoulder": "clavicle_r", "RightArm": "upperarm_r", "RightForeArm": "lowerarm_r", "RightHand": "hand_r",
       "LeftUpLeg": "thigh_l", "LeftLeg": "calf_l", "LeftFoot": "foot_l", "LeftToeBase": "ball_l",
       "RightUpLeg": "thigh_r", "RightLeg": "calf_r", "RightFoot": "foot_r", "RightToeBase": "ball_r"}


def log(msg):
    print("[clean_rig] " + msg, flush=True)


def load(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(glb))
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms:
        raise RuntimeError("no armature in %s" % glb)
    return arms[0], meshes


def tidy(arm, meshes):
    """Drop unskinned scraps, normalise scale, add root, rename. Returns the kept meshes."""
    kept = []
    for o in meshes:
        skinned = any(m.type == "ARMATURE" for m in o.modifiers) or (o.parent is arm and o.vertex_groups)
        if not skinned or len(o.data.vertices) < 100:
            log("dropped %s (%d verts)" % (o.name, len(o.data.vertices)))
            bpy.data.objects.remove(o, do_unlink=True)
        else:
            kept.append(o)
    # centimetres -> metres when the rig is taller than any human could be in metres
    height = max((b.head_local.z for b in arm.data.bones), default=0) if arm.data.bones else 0
    if height > 20:
        arm.scale = (0.01, 0.01, 0.01)
        for o in kept:
            if o.parent is not arm:
                o.scale = (0.01, 0.01, 0.01)
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        for o in kept:
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        log("scaled the rig from centimetres to metres")
    # root bone at the origin, parent of the (former) root bone(s)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    if "root" not in eb:
        root = eb.new("root")
        root.head = (0, 0, 0)
        root.tail = (0, 0.1, 0)
        for b in list(eb):
            if b.parent is None and b is not root:
                b.parent = root
    if SKELETON == "ue5":
        for b in eb:
            if b.name in UE5:
                b.name = UE5[b.name]
    bpy.ops.object.mode_set(mode="OBJECT")
    # vertex groups follow bone renames automatically in Blender; nothing else to do for skinning
    return kept


def export(arm, kept, glb=None, fbx=None, anim=False):
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for o in kept:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    if glb:
        bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB", export_yup=True,
                                  export_skins=True, export_animations=anim)
    if fbx:
        bpy.ops.export_scene.fbx(filepath=fbx, use_selection=True, object_types={"ARMATURE", "MESH"}, apply_unit_scale=True,
                                 apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE",
                                 use_mesh_modifiers=False, path_mode="STRIP", embed_textures=False, add_leaf_bones=False,
                                 bake_anim=anim, bake_anim_use_all_actions=anim, bake_anim_use_nla_strips=False,
                                 bake_anim_force_startend_keying=True, use_armature_deform_only=True)


# --- the character
arm, meshes = load(args["glb"])
kept = tidy(arm, meshes)
if not kept:
    raise RuntimeError("cleanup would drop every mesh; refusing")
arm.name = "SK_%s" % NAME
for i, o in enumerate(kept):
    o.name = "SK_%s_Mesh%s" % (NAME, "" if i == 0 else i)
export(arm, kept, glb=os.path.join(OUT, "SK_%s.glb" % NAME), fbx=os.path.join(OUT, "SK_%s.fbx" % NAME))
bones = [b.name for b in arm.data.bones]
result = {"bones": bones, "skeleton": SKELETON, "meshes": len(kept), "clips": []}

# --- the clips, through the same tidy so names match the skeleton
for path in args.get("animations") or []:
    clip = os.path.splitext(os.path.basename(path))[0]
    clip = clip[len("A_%s_" % NAME):] if clip.startswith("A_%s_" % NAME) else clip
    clip = clip.replace("_glb", "").replace("_fbx", "").replace("_armature", "")
    try:
        a_arm, a_meshes = load(path)
        a_kept = tidy(a_arm, a_meshes)
        a_arm.name = "SK_%s" % NAME
        frames = 0
        for act in bpy.data.actions:
            frames = max(frames, int(act.frame_range[1] - act.frame_range[0]))
        fbx = os.path.join(OUT, "A_%s_%s.fbx" % (NAME, clip))
        export(a_arm, a_kept, fbx=fbx, anim=True)
        result["clips"].append({"name": clip, "file": os.path.basename(fbx), "frames": frames, "seconds": round(frames / 30.0, 2)})
    except Exception as e:  # noqa: BLE001
        log("clip %s skipped: %s" % (clip, str(e)[:160]))
json.dump(result, open(os.path.join(OUT, "rig.json"), "w"), indent=1)
log("kept %d mesh(es), %d bones (%s), %d clip(s)" % (len(kept), len(bones), SKELETON, len(result["clips"])))

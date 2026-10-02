"""Rig and animate a delivered weapon for an engine (inside Blender):
    blender -b --factory-startup -Y --python rig_weapon.py -- <args.json>
args: {"blend", "name", "out_dir", "maps_dir", "sockets": [{"name", "location"}] (metres, the delivery's frame),
       "origin": "keep"|"mount"|"centre"|"bottom"|"rear"|"grip", "barrel": [from, to] or null, "recoil", "kick",
       "equip", "loop": null|"jet"|"coil", "idle": null|"coil", "glow": true}
Writes SK_<Name>.fbx (mesh and skeleton), A_<Name>_<Clip>.fbx (Idle, Fire, Equip, FiringLoop), the T_ maps beside
them, rig.json and rig_*.png. Ported from Proteus's bl_rig_weapon.py (2026-10-01), which the eight hardpoint weapons
were rigged with: the skinning is rigid and never cuts the mesh (a fused seed keeps its normals and UVs); Body carries
everything and slides; Barrel (the slender front past its narrowest section, when asked) kicks on its own; a Muzzle
bone sits at every measured muzzle (bones double as sockets). Everything is built and exported in centimetres: an FBX
that still needed its metre -> centimetre factor came into Unreal 5.8 with a x100 root bone ("the weapons are massive
and not attached to the ship")."""
import json
import math
import os
import shutil
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME = args["name"]
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
FPS = 30
CM = 100.0
report = {"name": NAME, "notes": []}


def log(msg):
    print("[rig] " + msg, flush=True)
    report["notes"].append(msg)


bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args["blend"]))
body = bpy.data.objects.get("SM_" + NAME) or max((o for o in bpy.data.objects if o.type == "MESH"),
                                                  key=lambda o: len(o.data.polygons))
for o in list(bpy.data.objects):
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
body.name = body.data.name = "SK_" + NAME
body.data.transform(body.matrix_world)
body.matrix_world = Matrix.Identity(4)
body.data.transform(Matrix.Scale(CM, 4))
me = body.data
n = len(me.vertices)
co = np.empty(n * 3, np.float64)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
lo, hi = co.min(0), co.max(0)
L = float(hi[0] - lo[0])
muzzles = {s["name"]: np.array(s["location"], float) * CM for s in args.get("sockets") or [] if s["name"].startswith("Muzzle")}
grip = next((np.array(s["location"], float) * CM for s in args.get("sockets") or [] if s["name"] == "Grip"), None)
log("loaded %s: %d verts, %.1f x %.1f x %.1f cm, muzzles %s" % (body.name, n, *(hi - lo), sorted(muzzles)))

# ------------------------------------------------------------------ the pivot
mode = args.get("origin") or "keep"
c = (lo + hi) / 2
if mode == "mount":
    # the plate's middle along X (the box of its top 2%; a plate a degree off level put the topmost verts on one
    # corner and the origin 5 cm off, 2026-09-30) and the weapon's own symmetry plane across Y
    slab = co[co[:, 2] > hi[2] - 0.02 * (hi[2] - lo[2])]
    pivot = np.array([(slab[:, 0].min() + slab[:, 0].max()) / 2, c[1], hi[2]])
elif mode == "centre":
    pivot = c
elif mode == "bottom":
    pivot = np.array([c[0], c[1], lo[2]])
elif mode == "rear":
    pivot = np.array([lo[0], c[1], c[2]])
elif mode == "grip" and grip is not None:
    pivot = grip
else:
    pivot = np.zeros(3)                                  # keep: the delivery's own origin
co -= pivot
me.vertices.foreach_set("co", co.ravel())
me.update()
muzzles = {k: v - pivot for k, v in muzzles.items()}
lo, hi = co.min(0), co.max(0)
log("origin %s (moved %s cm)" % (mode, np.round(pivot, 2).tolist()))
if not muzzles:
    front = co[co[:, 0] > hi[0] - 0.006 * L]
    muzzles["Muzzle"] = np.array([hi[0], front[:, 1].mean(), front[:, 2].mean()])
    log("no measured muzzle in the report: the middle of the front-most end")
main = muzzles.get("Muzzle", next(iter(muzzles.values())))
axis = (float(main[1]), float(main[2]))

# ------------------------------------------------------------------ the barrel: the narrowest section in a window
barrel_x = None
if args.get("barrel"):
    a, b = args["barrel"]
    xs = np.linspace(lo[0] + a * L, lo[0] + b * L, 60)
    w = (xs[-1] - xs[0]) / 60
    r = np.hypot(co[:, 1] - axis[0], co[:, 2] - axis[1])
    rs = np.array([r[np.abs(co[:, 0] - x) < w].max() if (np.abs(co[:, 0] - x) < w).any() else 1e9 for x in xs])
    barrel_x = float(xs[int(np.argmin(rs))])
    log("barrel splits at x=%.1f cm (radius %.1f cm)" % (barrel_x, rs.min()))

# ------------------------------------------------------------------ armature
arm_data = bpy.data.armatures.new("Armature")
arm = bpy.data.objects.new("Armature", arm_data)
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm_data.edit_bones
bl = 0.05 * L


def bone(name, head, parent=None):
    b_ = eb.new(name)
    b_.head = Vector(head)
    b_.tail = Vector(head) + Vector((bl, 0, 0))        # every bone points out of the muzzle (+X)
    b_.roll = 0.0
    if parent:
        b_.parent = eb[parent]
    return b_


bone("Root", (0, 0, 0))
bone("Body", (float(lo[0] + hi[0]) / 2, axis[0], axis[1]), "Root")
mparent = "Body"
if barrel_x is not None:
    bone("Barrel", (barrel_x, axis[0], axis[1]), "Body")
    mparent = "Barrel"
for m, p in muzzles.items():
    bone(m, p.tolist(), mparent)
bpy.ops.object.mode_set(mode="OBJECT")

# ------------------------------------------------------------------ rigid skin
for vg in list(body.vertex_groups):
    body.vertex_groups.remove(vg)
in_barrel = (co[:, 0] > barrel_x) if barrel_x is not None else np.zeros(n, bool)
body.vertex_groups.new(name="Body").add([int(i) for i in np.nonzero(~in_barrel)[0]], 1.0, "REPLACE")
if barrel_x is not None:
    body.vertex_groups.new(name="Barrel").add([int(i) for i in np.nonzero(in_barrel)[0]], 1.0, "REPLACE")
body.parent = arm
body.modifiers.new("Armature", "ARMATURE").object = arm

# ------------------------------------------------------------------ clips
scene = bpy.context.scene
scene.render.fps = FPS
arm.animation_data_create()


def clip(name, frames, keys):
    """keys: {bone: [(frame, (dx, dy, dz) in the weapon frame, (rx, ry, rz) degrees, scale_x)]}"""
    act = bpy.data.actions.new("A_%s_%s" % (NAME, name))
    act.use_fake_user = True
    arm.animation_data.action = act
    for pb in arm.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
        for f in (0, frames):
            for prop in ("location", "rotation_euler", "scale"):
                pb.keyframe_insert(prop, frame=f)
    for bname, ks in keys.items():
        pb = arm.pose.bones[bname]
        for f, d, r, sx in ks:
            # bones point along +X with roll 0: bone-local Y = weapon +X, bone-local X = weapon -Y, Z = weapon +Z
            pb.location = (-d[1], d[0], d[2])
            pb.rotation_euler = (math.radians(-r[1]), math.radians(r[0]), math.radians(r[2]))
            pb.scale = (1.0, sx, 1.0)
            for prop in ("location", "rotation_euler", "scale"):
                pb.keyframe_insert(prop, frame=f)
    act["frames"] = frames
    return act


Z0 = ((0, 0, 0), (0, 0, 0), 1.0)
rec, kick = float(args.get("recoil", 0.05)) * L, float(args.get("kick", 0.0)) * L
clips = {}
idle = {"Body": [(0, *Z0), (60, *Z0)]}
if args.get("idle") == "coil" and barrel_x is not None:
    idle["Barrel"] = [(0, *Z0), (15, (0.3, 0, 0), (0, 0, 0), 1.0), (30, *Z0), (45, (0.3, 0, 0), (0, 0, 0), 1.0), (60, *Z0)]
clips["Idle"] = clip("Idle", 60, idle)
fire = {"Body": [(0, *Z0), (2, (-rec, 0, 0), (0, 0, 0), 1.0), (5, (-rec * 0.8, 0, 0), (0, 0, 0), 1.0), (9, *Z0)]}
if kick and barrel_x is not None:
    fire["Barrel"] = [(0, *Z0), (1, (-kick, 0, 0), (0, 0, 0), 1.0), (4, (-kick * 0.6, 0, 0), (0, 0, 0), 1.0), (8, *Z0)]
clips["Fire"] = clip("Fire", 9, fire)
if args.get("loop"):
    j = 0.3 if args["loop"] == "jet" else 0.15
    pattern = [(0, 0, 0), (-j, 0, j * 0.5), (j * 0.4, 0, -j * 0.4), (-j * 0.7, 0, 0), (j * 0.2, 0, j * 0.6), (-j, 0, -j * 0.3)]
    loop = {"Body": [(i * 3, p, (0, 0, 0), 1.0) for i, p in enumerate(pattern)] + [(18, *Z0)]}
    if barrel_x is not None:
        a_ = 0.8 if args["loop"] == "coil" else 0.3
        loop["Barrel"] = [(0, *Z0), (3, (-a_, 0, 0), (0, 0, 0), 1.0), (6, (a_ * 0.4, 0, 0), (0, 0, 0), 1.0), (9, (-a_, 0, 0), (0, 0, 0), 1.0),
                          (12, (a_ * 0.4, 0, 0), (0, 0, 0), 1.0), (15, (-a_ * 0.6, 0, 0), (0, 0, 0), 1.0), (18, *Z0)]
    clips["FiringLoop"] = clip("FiringLoop", 18, loop)
eq = float(args.get("equip", 0.12)) * L
equip = {"Body": [(0, (-eq, 0, 0), (0, 0, 0), 1.0), (10, (0.12 * eq, 0, 0), (0, 0, 0), 1.0), (14, (-0.05 * eq, 0, 0), (0, 0, 0), 1.0), (18, *Z0)]}
if barrel_x is not None:
    equip["Barrel"] = [(0, (-0.8 * eq, 0, 0), (0, 0, 0), 1.0), (8, (-0.8 * eq, 0, 0), (0, 0, 0), 1.0), (15, (0.07 * eq, 0, 0), (0, 0, 0), 1.0), (18, *Z0)]
clips["Equip"] = clip("Equip", 18, equip)
arm.animation_data.action = None
log("clips: %s" % {k: v["frames"] for k, v in clips.items()})

# ------------------------------------------------------------------ export, centimetres, no node scale
for pb in arm.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.scale = (1, 1, 1)
common = dict(use_selection=True, apply_unit_scale=True, global_scale=0.01, apply_scale_options="FBX_SCALE_NONE",
              axis_forward="-Z", axis_up="Y", add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X",
              use_armature_deform_only=False)
blib.select_only([arm, body])
sk = os.path.join(OUT, "SK_%s.fbx" % NAME)
bpy.ops.export_scene.fbx(filepath=sk, object_types={"ARMATURE", "MESH"}, mesh_smooth_type="FACE", use_mesh_modifiers=False,
                         path_mode="STRIP", embed_textures=False, bake_anim=False, **common)
files = [os.path.basename(sk)]
for cname, act in clips.items():
    arm.animation_data.action = act
    scene.frame_start, scene.frame_end = 0, int(act["frames"])
    blib.select_only([arm])
    path = os.path.join(OUT, "A_%s_%s.fbx" % (NAME, cname))
    bpy.ops.export_scene.fbx(filepath=path, object_types={"ARMATURE"}, bake_anim=True, bake_anim_use_all_bones=True,
                             bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
                             bake_anim_force_startend_keying=True, bake_anim_step=1.0, bake_anim_simplify_factor=0.0, **common)
    files.append(os.path.basename(path))
arm.animation_data.action = None
maps = []
for f in sorted(os.listdir(args["maps_dir"])):
    if f.startswith("T_%s_" % NAME) and f.endswith(".png"):
        if args.get("glow") is False and f.endswith("_E.png"):
            continue
        shutil.copy2(os.path.join(args["maps_dir"], f), os.path.join(OUT, f))
        maps.append(f)
idx = np.random.default_rng(1).choice(n, size=min(n, 4000), replace=False)
report.update({"length_m": L / CM, "origin": mode, "pivot_moved_m": (pivot / CM).round(4).tolist(),
               "bounds_min_m": (lo / CM).round(4).tolist(), "bounds_max_m": (hi / CM).round(4).tolist(),
               "barrel_x_m": barrel_x / CM if barrel_x is not None else None,
               "muzzles_m": {k: (v / CM).round(4).tolist() for k, v in muzzles.items()},
               "bones": [b_.name for b_ in arm_data.bones], "clips": {k: int(v["frames"]) for k, v in clips.items()},
               "recoil_m": rec / CM, "equip_back_m": eq / CM, "files": files, "maps": maps,
               "envelope_m": np.round(co[idx] / CM, 4).tolist()})
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "SK_%s.blend" % NAME))

# ------------------------------------------------------------------ renders: rest, fire peak, equip start
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x, scene.render.resolution_y = 900, 600
sh = scene.display.shading
sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
sh.background_type, sh.background_color = "VIEWPORT", (0.82, 0.84, 0.86)
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scene.collection.objects.link(cam)
scene.camera = cam
centre = Vector(((lo[0] + hi[0]) / 2, 0, (lo[2] + hi[2]) / 2))
eye = centre + Vector((0.55 * L, -1.4 * L, 0.45 * L))
cam.location = eye
cam.rotation_euler = (centre - eye).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 50
cam.data.clip_end = 20 * L
renders = []
for label, cname, frame in (("rest", "Idle", 0), ("fire_peak", "Fire", 2), ("equip_start", "Equip", 0)):
    arm.animation_data.action = clips[cname]
    scene.frame_set(frame)
    scene.render.filepath = os.path.join(OUT, "rig_%s.png" % label)
    bpy.ops.render.render(write_still=True)
    renders.append(os.path.basename(scene.render.filepath))
report["renders"] = renders


# ------------------------------------------------------------------ read the skeletal FBX back
def read_back(path):
    """The SK FBX as an importer reads it: the mesh the weapon's size in metres, the armature's root node at scale 1
    in the file (Blender's importer scales a centimetre file's roots by 0.01; the x100 trap reads back at 1.0)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not arms or not meshes:
        return {"ok": False, "why": "no armature or mesh read back"}
    bpy.context.view_layer.update()
    lo_, hi_ = blib.dims(meshes[0])
    length = float(hi_.x - lo_.x)
    node = round(max(arms[0].matrix_world.to_scale()) / 0.01, 3)
    return {"ok": abs(length - L / CM) <= 0.01 * L / CM and abs(node - 1.0) < 0.01, "length_m": round(length, 4),
            "root_node_scale": node, "bones": len(arms[0].data.bones)}


report["fbx_check"] = read_back(sk)
log("SK read back: %s" % report["fbx_check"])
json.dump(report, open(os.path.join(OUT, "rig.json"), "w"), indent=1)
print("RIG_DONE", NAME, flush=True)

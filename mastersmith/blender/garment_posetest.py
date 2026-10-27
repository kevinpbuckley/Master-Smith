"""Prove a skinned garment follows the MetaHuman: the SK FBX and the built body and face FBX imported as they are, the
garment (and the face) driven by LEADER POSE (every follower bone takes the body bone's component-space transform, as
Unreal's SetLeaderPoseComponent does), poses measured and rendered with the delivered maps (in Blender):
    blender -b --factory-startup -Y --python-exit-code 1 --python garment_posetest.py -- <args.json>
args: {"body_fbx", "face_fbx", "sk_fbx", "body_proxy" (garment_fit.py's body_proxy.blend: the body with the torso the
       build hid), "maps": {"BC", "RM", "N"} (the delivered PNGs), "out_dir", "render_size", "samples"}
Writes pose_<name>_<front|side>.png, close-ups pose_<name>_collar.png and posetest_report.json with "pass" and every
failure: per pose the garment's edge stretch (all edges and edges of 2 mm or more), the skin vertices that come
through it (the completed body AND the face mesh's neck and jaw), how far the collar moves, and at rest how far the
garment moves when the BODY's skeleton drives it (zero when the garment's bind pose is the body's).

Why (2026-10-06): v5's test ray-tested only the built body, which is arms, lower legs and feet - blind exactly where
the garment failed (the collar against the neck and jaw, the torso under the jacket), and it rendered with a flat
roughness, not the delivered maps. The review's acceptance: no skin through the garment in any pose beyond rest (rest
none), no edge stretched past 2.5x, the collar still (< 3 mm) under a 15 and a 30 degree arm raise and a 10 degree
shrug, head turns of +-40 degrees and nods of +-15 degrees clear of the jaw."""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "mastersmith", "blender"))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
report = {"poses": {}, "notes": [], "failures": []}


def log(msg):
    print("[posetest] " + msg, flush=True)
    report["notes"].append(msg)


def imp(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=False)
    new = [o for o in bpy.data.objects if o not in before]
    a = next(o for o in new if o.type == "ARMATURE")
    ms = [o for o in new if o.type == "MESH"]
    for pb in a.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    return a, ms


bpy.ops.wm.read_factory_settings(use_empty=True)
barm, bmeshes = imp(args["body_fbx"])
body = max(bmeshes, key=lambda o: len(o.data.polygons))
farm, face = None, None
if args.get("face_fbx") and os.path.exists(args["face_fbx"]):
    farm, fmeshes = imp(args["face_fbx"])
    face = max(fmeshes, key=lambda o: len(o.data.polygons))
    for o in fmeshes:
        if o is not face:
            o.hide_render = True
garm, gmeshes = imp(args["sk_fbx"])
gar = gmeshes[0]
bpy.context.view_layer.update()
log("body armature %s (%d bones), garment armature %s (%d bones), garment %s (%d material slots)" % (
    barm.name, len(barm.data.bones), garm.name, len(garm.data.bones), gar.name, len(gar.data.materials)))
proxy = None
if args.get("body_proxy") and os.path.exists(args["body_proxy"]):
    with bpy.data.libraries.load(args["body_proxy"]) as (dfrom, dto):
        dto.objects = list(dfrom.objects)
    proxy = next(o for o in dto.objects if o is not None and o.type == "MESH")
    bpy.context.collection.objects.link(proxy)
    proxy.data.transform(barm.matrix_world.inverted())
    proxy.matrix_world = barm.matrix_world.copy()
    m_ = proxy.modifiers.new("Armature", "ARMATURE")
    m_.object = barm
    proxy.hide_render = True
    bpy.context.view_layer.update()


def ordered(arm):
    return sorted(arm.pose.bones, key=lambda pb: len(pb.bone.parent_recursive))


def leader_pose(follower, leader):
    """Every follower bone takes the leader bone's transform in world space (component space up to the actors' shared
    transform), parents first: what a leader pose component does."""
    lw = leader.matrix_world
    fwi = follower.matrix_world.inverted()
    for pb in ordered(follower):
        lp = leader.pose.bones.get(pb.name)
        if lp is not None:
            pb.matrix = fwi @ lw @ lp.matrix
            bpy.context.view_layer.update()


def evaluated(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    mw = np.array(o.matrix_world)
    co = np.array([v.co[:] for v in m.vertices]) @ mw[:3, :3].T + mw[:3, 3]
    m.calc_loop_triangles()
    tris = np.array([tuple(t.vertices) for t in m.loop_triangles])
    edges = np.array([tuple(ed.vertices) for ed in m.edges])
    e.to_mesh_clear()
    return co, tris, edges


def normals(co, tris):
    fn = np.cross(co[tris[:, 1]] - co[tris[:, 0]], co[tris[:, 2]] - co[tris[:, 0]])
    vn = np.zeros_like(co)
    for i in range(3):
        np.add.at(vn, tris[:, i], fn)
    return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)


# --- 1. the bind pose: the garment driven by the BODY's skeleton at rest must not move
g_rest, g_tris, g_edges = evaluated(gar)
leader_pose(garm, barm)
g_led, _, _ = evaluated(gar)
drift = np.linalg.norm(g_led - g_rest, axis=1)
report["rest_under_body_skeleton_mm"] = {"max": round(float(drift.max()) * 1000, 4), "median": round(float(np.median(drift)) * 1000, 4)}
log("at rest, driven by the body's skeleton the garment moves at most %.4f mm" % (drift.max() * 1000))
if drift.max() > 1e-5:
    report["failures"].append("rest drift %.4f mm under the body's skeleton" % (drift.max() * 1000))
bw, gw = barm.matrix_world, garm.matrix_world
worst = (0.0, 0.0)
for b in garm.data.bones:
    bb = barm.data.bones.get(b.name)
    if bb is None:
        continue
    mb, mg = bw @ bb.matrix_local, gw @ b.matrix_local
    ang = math.degrees(mb.to_quaternion().rotation_difference(mg.to_quaternion()).angle)
    worst = (max(worst[0], min(ang, 360 - ang)), max(worst[1], (mb.translation - mg.translation).length * 100))
report["rest_bones_in_blender"] = {"max_rot_deg": round(worst[0], 4), "max_off_cm": round(worst[1], 4)}
if proxy is not None:
    p_co, p_tris, _ = evaluated(proxy)
    b_co, _, _ = evaluated(body)
    tree = BVHTree.FromPolygons([tuple(p) for p in p_co], [tuple(t) for t in p_tris], all_triangles=True)
    dd = [tree.find_nearest(Vector(p))[3] for p in b_co[::7]]
    report["proxy_vs_built_body_mm"] = round(float(np.max(dd)) * 1000, 3)
    log("the completed body lies on the built one within %.3f mm" % report["proxy_vs_built_body_mm"])


# --- 2. poses
def rot_world(arm, bone, axis, deg):
    """Turn a bone about a world axis through its head."""
    pb = arm.pose.bones[bone]
    mw = arm.matrix_world
    h = pb.head.copy()
    ax_local = (mw.to_3x3().inverted() @ Vector(axis)).normalized()
    R = Matrix.Rotation(math.radians(deg), 4, ax_local)
    pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.matrix
    bpy.context.view_layer.update()


def lift_sign(arm, bone, axis, tip):
    """+1 or -1: the turn about axis that lifts the tip bone's head."""
    z0 = (arm.matrix_world @ arm.pose.bones[tip].head).z
    rot_world(arm, bone, axis, 5)
    z1 = (arm.matrix_world @ arm.pose.bones[tip].head).z
    rot_world(arm, bone, axis, -5)
    return 1 if z1 > z0 else -1


HEAD = {"yaw_l40": [("neck_01", (0, 0, 1), 13), ("neck_02", (0, 0, 1), 12), ("head", (0, 0, 1), 15)],
        "yaw_r40": [("neck_01", (0, 0, 1), -13), ("neck_02", (0, 0, 1), -12), ("head", (0, 0, 1), -15)],
        "nod_down15": [("neck_01", (1, 0, 0), 4), ("neck_02", (1, 0, 0), 5), ("head", (1, 0, 0), 6)],
        "nod_up15": [("neck_01", (1, 0, 0), -4), ("neck_02", (1, 0, 0), -5), ("head", (1, 0, 0), -6)]}
POSES = {"rest": []}
POSES.update({"head_" + k: v for k, v in HEAD.items()})
POSES.update({
    "arm_raise15": [("upperarm_l", (0, 1, 0), ("lift", 15, "hand_l"))],
    "arm_raise30": [("upperarm_l", (0, 1, 0), ("lift", 30, "hand_l")), ("upperarm_r", (0, 1, 0), ("lift", 30, "hand_r"))],
    "shrug": [("clavicle_l", (0, 1, 0), ("lift", 10, "upperarm_l")), ("clavicle_r", (0, 1, 0), ("lift", 10, "upperarm_r"))],
    "arms_down": [("upperarm_l", (0, 1, 0), ("lift", -20, "hand_l")), ("upperarm_r", (0, 1, 0), ("lift", -20, "hand_r"))],
    "spine_bend": [("spine_02", (1, 0, 0), -8), ("spine_03", (1, 0, 0), -8), ("spine_04", (1, 0, 0), -6), ("spine_03", (0, 0, 1), 12)],
    "walk": [("thigh_l", (1, 0, 0), -28), ("calf_l", (1, 0, 0), 35), ("thigh_r", (1, 0, 0), 14), ("upperarm_r", (1, 0, 0), -20),
             ("upperarm_l", (1, 0, 0), 15)],
})
COLLAR_STILL = ("arm_raise15", "arm_raise30", "shrug")
CLOSEUP = ("rest", "head_yaw_l40", "head_yaw_r40", "head_nod_down15", "head_nod_up15", "arm_raise30", "shrug")

# --- 3. materials: the delivered maps on the garment, a skin colour on the body and face
skin = bpy.data.materials.new("Skin")
skin.use_nodes = True
skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.40, 0.33, 1)
skin.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
for o in [body] + ([face] if face else []):
    o.data.materials.clear()
    o.data.materials.append(skin)
maps = args.get("maps") or {}
if maps.get("BC") and os.path.exists(maps["BC"]):
    gm = bpy.data.materials.new("Garment")
    gm.use_nodes = True
    gm.use_backface_culling = False
    nt = gm.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    t1 = nt.nodes.new("ShaderNodeTexImage")
    t1.image = bpy.data.images.load(os.path.abspath(maps["BC"]))
    nt.links.new(t1.outputs["Color"], bsdf.inputs["Base Color"])
    if maps.get("RM") and os.path.exists(maps["RM"]):
        t2 = nt.nodes.new("ShaderNodeTexImage")
        t2.image = bpy.data.images.load(os.path.abspath(maps["RM"]))
        t2.image.colorspace_settings.name = "Non-Color"
        sp = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(t2.outputs["Color"], sp.inputs["Color"])
        nt.links.new(sp.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sp.outputs["Blue"], bsdf.inputs["Metallic"])
    if maps.get("N") and os.path.exists(maps["N"]):
        t3 = nt.nodes.new("ShaderNodeTexImage")
        t3.image = bpy.data.images.load(os.path.abspath(maps["N"]))
        t3.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = gar.data.uv_layers[0].name
        nt.links.new(t3.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    n_slots = len(gar.data.materials)
    for i in range(max(1, n_slots)):
        if i < n_slots:
            gar.data.materials[i] = gm
        else:
            gar.data.materials.append(gm)
for o in bmeshes + gmeshes:
    if o not in (body, gar):
        o.hide_render = True
size = int(args.get("render_size", 768))
blib.setup_render(size, int(args.get("samples", 16)), look="preview")
scn = bpy.context.scene
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
bpy.context.collection.objects.link(cam)
scn.camera = cam
for nm_, dvec, e in (("Key", (-0.6, -1.0, 0.8), 600), ("Fill", (1.0, -0.4, 0.3), 250), ("Back", (0.3, 1.0, 0.9), 350)):
    L = bpy.data.lights.new(nm_, "AREA")
    L.energy, L.size = e, 2.0
    lo_ = bpy.data.objects.new(nm_, L)
    bpy.context.collection.objects.link(lo_)
    lo_.location = Vector(dvec).normalized() * 4 + Vector((0, 0, 1.0))
    lo_.rotation_euler = (Vector((0, 0, 1.0)) - lo_.location).to_track_quat("-Z", "Y").to_euler()
lo, hi = blib.dims(body)
if face:
    flo, fhi = blib.dims(face)
    lo = Vector(np.minimum(np.array(lo), np.array(flo)))
    hi = Vector(np.maximum(np.array(hi), np.array(fhi)))
lo -= Vector((0.15, 0.15, 0.0))
hi += Vector((0.15, 0.15, 0.15))
rest_len = np.linalg.norm(g_rest[g_edges[:, 0]] - g_rest[g_edges[:, 1]], axis=1)
big = rest_len >= 0.002
collar_v = g_rest[:, 2] > 1.55
neck_c = (barm.matrix_world @ barm.pose.bones["neck_01"].head) if "neck_01" in barm.pose.bones else Vector((0, 0, 1.5))


POKE_AT = []


def skin_pokes(co, tris, step, zmin=0.006):
    """Skin vertices outside the garment where it should cover them: outward ray misses it (12 cm), inward ray meets
    it within 2 cm AND inside the skin's own thickness (a ray from a thin ear lobe leaves the lobe and may then meet
    the collar below: not a poke). Under z 6 mm the bare soles are under the floor and the boots' soles stand on it."""
    vn = normals(co, tris)
    sbvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t) for t in tris], all_triangles=True)
    n_p = n_c = 0
    where = []
    for i in range(0, len(co), step):
        if co[i, 2] < zmin:
            continue
        p, n = Vector(co[i]), Vector(vn[i])
        if gbvh.ray_cast(p + n * 1e-4, n, 0.12)[0] is not None:
            n_c += 1
            continue
        hit = gbvh.ray_cast(p - n * 1e-4, -n, 0.02)
        if hit[0] is None:
            continue
        sh = sbvh.ray_cast(p - n * 2e-4, -n, 0.02)
        if sh[0] is not None and sh[3] < hit[3]:
            continue
        n_p += 1
        where.append([round(float(x), 3) for x in co[i]])
    POKE_AT.append(where[:12])
    return n_p, n_c


def measure():
    global gbvh
    gco, gt, _ = evaluated(gar)
    gbvh = BVHTree.FromPolygons([tuple(p) for p in gco], [tuple(t) for t in gt], all_triangles=True)
    ln = np.linalg.norm(gco[g_edges[:, 0]] - gco[g_edges[:, 1]], axis=1)
    ratio = ln / np.maximum(rest_len, 1e-6)
    out = {"stretch_max": round(float(ratio.max()), 3), "stretch_max_2mm": round(float(ratio[big].max()), 3),
           "stretch_p999": round(float(np.percentile(ratio, 99.9)), 3), "compress_min_2mm": round(float(ratio[big].min()), 3),
           "edges_over_1_5x_2mm": int((ratio[big] > 1.5).sum()), "edges_over_2_5x": int((ratio > 2.5).sum()),
           "collar_move_mm": round(float(np.linalg.norm(gco[collar_v] - g_rest[collar_v], axis=1).max()) * 1000, 2) if collar_v.any() else 0}
    k = int(np.argmax(np.where(big, ratio, 0)))
    out["worst_edge_at_m"] = [round(float(x), 3) for x in g_rest[g_edges[k, 0]]]
    POKE_AT.clear()
    if proxy is not None:
        pco, pt, _ = evaluated(proxy)
        out["body_pokes"], out["body_covered"] = skin_pokes(pco, pt, 2)
    else:
        bco_, bt, _ = evaluated(body)
        out["body_pokes"], out["body_covered"] = skin_pokes(bco_, bt, 2)
    if face is not None:
        fco_, ft, _ = evaluated(face)
        out["face_pokes"], out["face_covered"] = skin_pokes(fco_, ft, 1)
    out["pokes_at"] = [w for w in POKE_AT if w]
    return out


def shoot(tag, closeup):
    out = {}
    for name, view in (("front", "left"), ("side", "front")):
        blib.ortho_camera(cam, view, lo, hi, margin=1.04)
        p = os.path.join(OUT, "pose_%s_%s.png" % (tag, name))
        scn.render.filepath = p
        bpy.ops.render.render(write_still=True)
        out[name] = os.path.basename(p)
    if closeup:
        for name, d in (("collar", (-0.35, -1.0, 0.12)), ("collar_back", (0.45, 1.0, 0.3))):
            dv = Vector(d).normalized()
            cam.data.type = "ORTHO"
            cam.location = neck_c + Vector((0, 0, 0.05)) + dv * 3.0
            cam.rotation_euler = (-dv).to_track_quat("-Z", "Y").to_euler()
            cam.data.ortho_scale = 0.5
            p = os.path.join(OUT, "pose_%s_%s.png" % (tag, name))
            scn.render.filepath = p
            bpy.ops.render.render(write_still=True)
            out[name] = os.path.basename(p)
    return out


def reset():
    for a in [barm, garm] + ([farm] if farm else []):
        for pb in a.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


for tag, steps in POSES.items():
    reset()
    done = []
    for bone, axis, deg in steps:
        if bone not in barm.pose.bones:
            continue
        if isinstance(deg, tuple):
            deg = deg[1] * lift_sign(barm, bone, axis, deg[2])
        rot_world(barm, bone, axis, deg)
        done.append([bone, list(axis), round(deg, 2)])
    leader_pose(garm, barm)
    if farm:
        leader_pose(farm, barm)
    m = measure()
    report["poses"][tag] = {"steps": done, "metrics": m, "renders": shoot(tag, tag in CLOSEUP)}
    log("%s: %s" % (tag, m))
reset()

# --- 4. the verdict
r0 = report["poses"]["rest"]["metrics"]
if r0.get("body_pokes", 0) or r0.get("face_pokes", 0):
    report["failures"].append("at rest: %d body and %d face vertices through the garment" % (r0.get("body_pokes", 0), r0.get("face_pokes", 0)))
for tag, rec in report["poses"].items():
    m = rec["metrics"]
    for k in ("body_pokes", "face_pokes"):
        if m.get(k, 0) > r0.get(k, 0):
            report["failures"].append("%s: %s %d (rest %d)" % (tag, k, m[k], r0.get(k, 0)))
    if m["stretch_max_2mm"] > 2.5:
        report["failures"].append("%s: an edge of 2 mm or more stretched %.2fx (at %s)" % (tag, m["stretch_max_2mm"], m["worst_edge_at_m"]))
    if tag in COLLAR_STILL and m["collar_move_mm"] > 3.0:
        report["failures"].append("%s: the collar moved %.1f mm" % (tag, m["collar_move_mm"]))
report["pass"] = not report["failures"]
report["criteria"] = ("rest: no body or face vertex through the garment; every pose: no more than rest; every edge of 2 mm or more "
                      "under 2.5x stretch (all-edge maximum reported beside it); the collar (rest z > 1.55 m) under 3 mm in "
                      "%s; the garment still at rest under the body's skeleton" % ", ".join(COLLAR_STILL))
log("pass: %s; failures: %s" % (report["pass"], report["failures"]))
json.dump(report, open(os.path.join(OUT, "posetest_report.json"), "w", encoding="utf-8", newline="\n"), indent=1)
log("done -> %s" % OUT)

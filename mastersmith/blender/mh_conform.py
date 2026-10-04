"""A character seed prepared for Unreal 5.8's "custom mesh to MetaHuman" conform (inside Blender):
    blender -b --factory-startup -Y --python mh_conform.py -- <args.json>
args: {"source": seed.glb | registered.blend | any .glb/.fbx/.obj, "extra": [more meshes to join: a separate head], "name",
       "height_m": the brief's height (0 = keep the source's), "out_dir", "template_glb", "template_json",
       "strip": [object-name substrings to drop: hair, lashes, a weapon]}
Writes <Name>_conform.glb (one static mesh, metres, Z up, facing -Y, feet on the floor, transforms applied),
conform_report.json (height, the A-pose measured: arm angles, armpit and knee gaps, finger tips per hand, a hair
suspicion) and conform_<front|side>.png: the seed white over the MetaHuman template's outline in red.

Why (owner, 2026-10-04, "Turn ANY Character into an Animated Metahuman"): the conform solver takes one combined mesh in
an A-pose with the arms clear of the body, the legs apart, the fingers separated, bald, no lashes, at the real height
with transforms applied. The report says, before the editor is involved, what the solver will get wrong."""
import json
import math
import os
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
NAME = args["name"]
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
report = {"name": NAME, "notes": []}


def log(msg):
    print("[mh_conform] " + msg, flush=True)
    report["notes"].append(msg)


def load_any(path):
    """Imports a mesh file (or opens a .blend) and returns its new mesh objects."""
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(path))
        return [o for o in bpy.data.objects if o.type == "MESH"]
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=os.path.abspath(path))
    else:
        raise ValueError("cannot import %s" % path)
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
meshes = load_any(args["source"])
for extra in args.get("extra") or []:
    meshes += load_any(extra)
strip = [s.lower() for s in (args.get("strip") or [])]
dropped = [o.name for o in meshes if any(s in o.name.lower() for s in strip)]
meshes = [o for o in meshes if o.name not in dropped]
if dropped:
    log("dropped %s" % ", ".join(dropped))
if not meshes:
    raise RuntimeError("no mesh in %s" % args["source"])
for o in list(bpy.data.objects):
    if o.type != "MESH" or o not in meshes:
        bpy.data.objects.remove(o, do_unlink=True)
blib.select_only(meshes)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if len(meshes) > 1:
    bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
body.name = body.data.name = "SM_%s_Conform" % NAME
me = body.data
me.validate()


def coords():
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


# --- orient: the tallest axis is up (a seed registered as a hard-surface part may lie along X); the feet point forward
co = coords()
ext = co.max(0) - co.min(0)
up = int(np.argmax(ext))
if up != 2:
    rot = Matrix.Rotation(-math.pi / 2, 4, "Y") if up == 0 else Matrix.Rotation(math.pi / 2, 4, "X")
    me.transform(rot)
    co = coords()
    log("turned the %s axis up" % "XYZ"[up])
lo, hi = co.min(0), co.max(0)
H = hi[2] - lo[2]
# forward: the toes stand ahead of the ankles (lowest 4% of the height vs the band at 8-12%)
feet = co[co[:, 2] < lo[2] + 0.04 * H]
ankles = co[(co[:, 2] > lo[2] + 0.08 * H) & (co[:, 2] < lo[2] + 0.12 * H)]
fwd = (feet[:, :2].mean(0) - ankles[:, :2].mean(0)) if len(feet) and len(ankles) else np.array([0.0, -1.0])
if np.linalg.norm(fwd) < 0.01 * H:
    # no toes to read (boots, a robe): the hands hang ahead of the hips in an A-pose - the points outside the torso at
    # hip height against the torso's own centre (the back of the skull fooled a nose-based reading, 2026-10-04)
    band = co[(co[:, 2] > lo[2] + 0.40 * H) & (co[:, 2] < lo[2] + 0.55 * H)]
    cx = band[:, 0].mean()
    half = np.percentile(np.abs(band[:, 0] - cx), 60)
    hands = band[np.abs(band[:, 0] - cx) > 1.5 * half]
    torso = band[np.abs(band[:, 0] - cx) <= half]
    fwd = hands[:, :2].mean(0) - torso[:, :2].mean(0) if len(hands) > 10 else np.array([0.0, -1.0])
    log("forward read off the hands (no toes found)")
yaw = math.atan2(-fwd[0], -fwd[1])          # turn fwd onto -Y
if abs(yaw) > math.radians(2):
    me.transform(Matrix.Rotation(yaw, 4, "Z"))
    co = coords()
    log("yawed %.0f degrees so the character faces -Y" % math.degrees(yaw))
lo, hi = co.min(0), co.max(0)

# --- size and place: the brief's height, feet on z=0, centred in x and y
target_h = float(args.get("height_m") or 0)
if target_h > 0:
    s = target_h / (hi[2] - lo[2])
    me.transform(Matrix.Scale(s, 4))
    if abs(s - 1) > 0.02:
        log("scaled x%.3f to %.2f m" % (s, target_h))
co = coords()
lo, hi = co.min(0), co.max(0)
me.transform(Matrix.Translation(Vector((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))))
co = coords()
lo, hi = co.min(0), co.max(0)
H = float(hi[2] - lo[2])
body.matrix_world = Matrix.Identity(4)
report.update({"height_m": round(H, 4), "width_m": round(float(hi[0] - lo[0]), 4), "depth_m": round(float(hi[1] - lo[1]), 4),
               "vertices": len(me.vertices), "triangles": blib.tri_count(body)})

# --- the A-pose read off the silhouette (front view: x across, z up)
GRID = 0.005                                                   # 5 mm cells
W = int(math.ceil((hi[0] - lo[0]) / GRID)) + 2
Hc = int(math.ceil(H / GRID)) + 2
occ = np.zeros((Hc, W), bool)
ix = np.clip(((co[:, 0] - lo[0]) / GRID).astype(int), 0, W - 1)
iz = np.clip(((co[:, 2] - lo[2]) / GRID).astype(int), 0, Hc - 1)
occ[iz, ix] = True


def shifted(a, dr, dc):
    out = np.zeros_like(a)
    r0, r1 = max(dr, 0), a.shape[0] + min(dr, 0)
    c0, c1 = max(dc, 0), a.shape[1] + min(dc, 0)
    out[r0:r1, c0:c1] = a[r0 - dr:r1 - dr, c0 - dc:c1 - dc]
    return out


def closing(a, iterations=1):
    """Binary closing with a 3x3 cross (Blender ships no scipy): dilate, then erode."""
    for _ in range(iterations):
        a = a | shifted(a, 1, 0) | shifted(a, -1, 0) | shifted(a, 0, 1) | shifted(a, 0, -1)
    for _ in range(iterations):
        a = a & shifted(a, 1, 0) & shifted(a, -1, 0) & shifted(a, 0, 1) & shifted(a, 0, -1)
    return a


# close small gaps between sampled vertices (a sparse low-poly seed); the cell is 5 mm, so a 2-cell closing shuts
# anything under 2 cm - a real armpit or knee gap stays open
occ = closing(occ, iterations=2)


def runs(row):
    """[(start, end)] of the filled runs in a boolean row."""
    out, start = [], None
    for i, v in enumerate(row):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(row)))
    return out


centre_col = int((0 - lo[0]) / GRID)
# the torso column span at mid height (40-60%): the widest run containing the centre
torso = []
for r in range(int(0.40 * Hc), int(0.60 * Hc)):
    for a, b in runs(occ[r]):
        if a <= centre_col < b:
            torso.append((a, b))
torso_w = np.median([b - a for a, b in torso]) * GRID if torso else 0
report["torso_width_m"] = round(float(torso_w), 3)

# arms: the rows where three runs exist (arm, torso, arm) give the armpit; the arm's run centre per row gives its angle
arm_rows = [r for r in range(int(0.35 * Hc), int(0.95 * Hc)) if len(runs(occ[r])) >= 3]
if arm_rows:
    armpit_row = max(arm_rows)
    report["armpit_height_m"] = round(armpit_row * GRID, 3)
    # the gap between the arm and the torso a hand's width under the armpit (right under the fork it is always tiny;
    # the template itself measured 5 mm there, 2026-10-04)
    gaps = []
    for r in range(max(0, armpit_row - int(0.15 * H / GRID)), max(0, armpit_row - int(0.06 * H / GRID))):
        rs = runs(occ[r])
        if len(rs) >= 3:
            gaps.append(min(rs[1][0] - rs[0][1], rs[-1][0] - rs[-2][1]) * GRID)
    report["armpit_gap_m"] = round(float(np.median(gaps)), 3) if gaps else 0.0
    for side, pick in (("l", lambda rs: rs[-1]), ("r", lambda rs: rs[0])):      # the character's left is +X when it faces -Y
        pts = []
        for r in range(int(0.30 * Hc), armpit_row):
            rs = runs(occ[r])
            if len(rs) >= 3:
                a, b = pick(rs)
                pts.append((((a + b) / 2 - centre_col) * GRID, r * GRID))
        if len(pts) > 10:
            pts = np.array(pts)
            # the line through the arm's run centres: angle from vertical
            dx = pts[:, 0] - pts[:, 0].mean()
            dz = pts[:, 1] - pts[:, 1].mean()
            ang = math.degrees(math.atan2(abs(np.dot(dx, dz)), np.dot(dz, dz))) if np.dot(dz, dz) else 0
            report["arm_angle_deg_%s" % side] = round(ang, 1)
            report["hand_bottom_m_%s" % side] = round(float(pts[:, 1].min()), 3)
else:
    report["armpit_gap_m"] = 0.0
    report["arm_angle_deg_l"] = report["arm_angle_deg_r"] = 0.0
    log("the arms do not separate from the torso in the front silhouette")
# legs: the gap between the two runs at knee height (25-30%)
leg_gaps = []
for r in range(int(0.25 * Hc), int(0.30 * Hc)):
    rs = runs(occ[r])
    if len(rs) >= 2:
        leg_gaps.append((rs[1][0] - rs[0][1]) * GRID)
report["leg_gap_m"] = round(float(np.median(leg_gaps)), 3) if leg_gaps else 0.0
# head: a run above the shoulders narrower than the torso
shoulder_row = max(arm_rows) if arm_rows else int(0.8 * Hc)
head_rows = [r for r in range(shoulder_row, Hc) if runs(occ[r])]
head_w = [max(b - a for a, b in runs(occ[r])) * GRID for r in head_rows]
report["head_present"] = bool(head_rows) and (hi[2] - shoulder_row * GRID) > 0.12 * H
report["head_width_m"] = round(float(max(head_w)), 3) if head_w else 0.0
# a hair suspicion: the head's widest point sits in its top half and the head is taller than 0.16 of the height
if head_rows:
    head_h = (Hc - shoulder_row) * GRID
    widest = head_rows[int(np.argmax(head_w))] * GRID
    report["hair_suspected"] = bool(head_h > 0.17 * H and widest > shoulder_row * GRID + 0.5 * head_h)
# finger tips: the lowest rows of each hand, counted as separate runs in a fine grid of the hand's box
report["finger_tips"] = None
for side in ("l", "r"):
    hb = report.get("hand_bottom_m_%s" % side)
    if hb is None:
        continue
    sel = co[(co[:, 2] < hb + 0.06) & ((co[:, 0] > torso_w / 2) if side == "l" else (co[:, 0] < -torso_w / 2))]
    if len(sel) < 20:
        continue
    fine = 0.002
    g = np.zeros((int(0.06 / fine) + 1, int((sel[:, 0].max() - sel[:, 0].min()) / fine) + 2), bool)
    g[np.clip(((sel[:, 2] - hb) / fine).astype(int), 0, g.shape[0] - 1), ((sel[:, 0] - sel[:, 0].min()) / fine).astype(int)] = True
    g = closing(g, iterations=1)
    # the most separate runs in any row of the lowest 5 cm: the finger tips end at different heights (the middle finger
    # lowest), so the very bottom rows alone counted 3 on a hand with five fingers spread (2026-10-04)
    tips = max(len(runs(g[r])) for r in range(min(int(0.05 / fine), g.shape[0])))
    report["finger_tips_%s" % side] = int(tips)
    report["finger_tips"] = int(tips) if report["finger_tips"] is None else min(report["finger_tips"], int(tips))

# --- the overlay renders: the seed white, the template's outline red, same frame (the template's bounds scaled to H)
tmpl = json.load(open(args["template_json"], encoding="utf-8"))
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["template_glb"]))
tobjs = [o for o in bpy.data.objects if o.type == "MESH" and o is not body]
blib.select_only(tobjs)
if len(tobjs) > 1:
    bpy.ops.object.join()
tmpl_obj = bpy.context.view_layer.objects.active
tmpl_obj.name = "MH_Template"
bpy.context.view_layer.update()
tmpl_obj.data.transform(tmpl_obj.matrix_world)          # whatever node scale the GLB carries goes into the data
tmpl_obj.matrix_world = Matrix.Identity(4)
ts = H / tmpl["template_height_m"]
# the template placed like the seed: feet on z=0, centred in x and y on its bounds (it stood 7 cm off in y and
# rendered in front of the seed, 2026-10-04)
tb0, tb1 = tmpl["template_bounds_min"], tmpl["template_bounds_max"]
tmpl_obj.data.transform(Matrix.Scale(ts, 4) @ Matrix.Translation(Vector((-(tb0[0] + tb1[0]) / 2, -(tb0[1] + tb1[1]) / 2, -tb0[2]))))
report["template_scaled_to_m"] = round(H, 3)
scn = bpy.context.scene
scn.render.engine = "BLENDER_WORKBENCH"
scn.display.shading.light = "FLAT"
scn.display.shading.color_type = "MATERIAL"
scn.display.shading.show_object_outline = False
scn.render.film_transparent = False
w = bpy.data.worlds.new("W")
scn.world = w
w.color = (0, 0, 0)
scn.view_settings.view_transform = "Standard"
scn.render.resolution_x = scn.render.resolution_y = int(args.get("size", 1024))
scn.render.image_settings.color_mode = "RGB"


def flat(name, rgb):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    return m


body.data.materials.clear()
body.data.materials.append(flat("SeedWhite", (1, 1, 1)))
tmpl_obj.data.materials.clear()
tmpl_obj.data.materials.append(flat("TemplateRed", (1, 0.1, 0.1)))
# the template as a wire of its outline: render it alone behind the seed by drawing it slightly behind (y+) and letting
# the seed cover it; what sticks out red is where the seed differs from the MetaHuman A-pose
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
bpy.context.collection.objects.link(cam)
scn.camera = cam
both_lo = Vector((min(lo[0], -tmpl["body_half_span_m"] * ts), -0.3 * H, 0))
both_hi = Vector((max(hi[0], tmpl["body_half_span_m"] * ts), 0.3 * H, H))
renders = {}
# the character faces -Y: blib's "left" camera (at -Y) sees the face, its "front" camera (at +X) the profile
for view, cv, push in (("front", "left", Vector((0, 0.02 * H, 0))), ("side", "front", Vector((-0.02 * H, 0, 0)))):
    tmpl_obj.location = push                         # the template a little behind the seed in that view
    blib.ortho_camera(cam, cv, both_lo, both_hi, margin=1.06)
    path = os.path.join(OUT, "conform_%s.png" % view)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[view] = os.path.basename(path)
tmpl_obj.location = (0, 0, 0)
report["renders"] = renders
report["render_key"] = "white: the seed as it will be exported; red: the MetaHuman template at the same height, where the seed does not cover it"

# --- export: one static mesh, metres, transforms applied, no materials needed (the solver reads geometry)
bpy.data.objects.remove(tmpl_obj, do_unlink=True)
blib.select_only([body])
glb = os.path.join(OUT, "%s_conform.glb" % NAME)
bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB", export_apply=True,
                          export_animations=False, export_skins=False, export_materials="EXPORT", export_yup=True)
report["glb"] = os.path.basename(glb)
report["glb_bytes"] = os.path.getsize(glb)
json.dump(report, open(os.path.join(OUT, "conform_report.json"), "w", encoding="utf-8"), indent=1, default=plain)
log("%s: %.2f m, arms %s/%s deg, armpit gap %.0f mm, knee gap %.0f mm, finger tips %s, head %s" % (
    os.path.basename(glb), H, report.get("arm_angle_deg_l"), report.get("arm_angle_deg_r"),
    report.get("armpit_gap_m", 0) * 1000, report.get("leg_gap_m", 0) * 1000, report.get("finger_tips"), report.get("head_present")))

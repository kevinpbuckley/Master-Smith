"""Pass C (inside Blender): vehicle wheel rig.
    blender -b --python rig_vehicle.py -- <args.json>
Inputs: the delivered SM_<Name>.blend (LOD0 + hull) and the part GLBs a splitter returned for the same
mesh. Parts are untextured and re-meshed, so they are used only as LABELS: every LOD0 face takes the
label of the nearest part vertex. Wheel-shaped parts (round in XZ, thin in Y, sitting low) become separate
wheel objects, each bound to its own bone whose axis is the axle; everything else binds to the root.
Exports SK_<Name>.fbx / .glb and writes rig.json."""
import glob
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME, OUT, PARTS = args["name"], args["out_dir"], args["parts_dir"]
result = {"wheels": [], "notes": []}


def log(msg):
    print("[rig] " + msg, flush=True)
    result["notes"].append(msg)


bpy.ops.wm.open_mainfile(filepath=os.path.join(OUT, "SM_%s.blend" % NAME))
body = bpy.data.objects["SM_" + NAME]
for o in list(bpy.data.objects):
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)       # LOD1/2 and the hull are not part of the skeletal mesh
blib.select_only([body])
lo, hi = blib.dims(body)
ext = hi - lo
length, height = ext.x, ext.z

# ---------------------------------------------------------------- parts -> labelled point cloud
parts = []
for path in sorted(glob.glob(os.path.join(PARTS, "part_*.glb")), key=lambda s: int(os.path.basename(s)[5:-4])):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    pts = []
    for o in new:
        n = len(o.data.vertices)
        co = np.empty(n * 3, np.float32)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        m = np.array(o.matrix_world)
        pts.append(co @ m[:3, :3].T + m[:3, 3])
    for o in [o for o in bpy.data.objects if o not in before]:
        bpy.data.objects.remove(o, do_unlink=True)
    if not pts:
        continue
    p = np.concatenate(pts)
    step = max(1, len(p) // 6000)
    parts.append({"file": os.path.basename(path), "points": p[::step], "lo": p.min(axis=0), "hi": p.max(axis=0)})
log("%d parts loaded" % len(parts))

# ---------------------------------------------------------------- which parts are wheels
def is_wheel(part):
    e = part["hi"] - part["lo"]
    c = (part["hi"] + part["lo"]) * 0.5
    round_xz = abs(e[0] - e[2]) < 0.25 * max(e[0], e[2])
    thin_y = e[1] < 0.7 * max(e[0], e[2])
    r = max(e[0], e[2]) * 0.5
    on_ground = abs((c[2] - lo.z) - r) < 0.35 * r        # a wheel's centre is one radius above the ground
    sized = 0.08 * length < e[0] < 0.45 * length
    return round_xz and thin_y and on_ground and sized


wheel_ids = [i for i, p in enumerate(parts) if is_wheel(p)]
log("wheel-shaped parts: %s" % [parts[i]["file"] for i in wheel_ids])
# A splitter often hands a wheel back as two or three parts (tyre, rim, hub). Parts whose centres sit within
# a wheel radius of each other are one wheel: merge their labels and their point clouds.
groups = []
for i in wheel_ids:
    c = (parts[i]["hi"] + parts[i]["lo"]) * 0.5
    r = max(parts[i]["hi"][0] - parts[i]["lo"][0], parts[i]["hi"][2] - parts[i]["lo"][2]) * 0.5
    for g in groups:
        if np.linalg.norm(g["centre"] - c) < 0.6 * max(r, g["radius"]):
            g["ids"].append(i)
            g["centre"] = (g["centre"] * (len(g["ids"]) - 1) + c) / len(g["ids"])
            g["radius"] = max(g["radius"], r)
            break
    else:
        groups.append({"ids": [i], "centre": c, "radius": r})
if len(groups) < len(wheel_ids):
    log("merged %d wheel parts into %d wheels" % (len(wheel_ids), len(groups)))
    for g in groups:
        keep = g["ids"][0]
        for other in g["ids"][1:]:
            parts[keep]["points"] = np.concatenate([parts[keep]["points"], parts[other]["points"]])
            parts[keep]["lo"] = np.minimum(parts[keep]["lo"], parts[other]["lo"])
            parts[keep]["hi"] = np.maximum(parts[keep]["hi"], parts[other]["hi"])
            parts[other]["points"] = parts[other]["points"][:0]
    wheel_ids = [g["ids"][0] for g in groups]
    # labels of the merged parts point at the kept one
    merged_into = {other: g["ids"][0] for g in groups for other in g["ids"][1:]}

if len(wheel_ids) < 2:
    result["status"] = "no_wheels"
    log("fewer than two wheel parts; the vehicle stays a static mesh")
    json.dump(result, open(os.path.join(OUT, "rig.json"), "w"), indent=1)
    sys.exit(0)

# ---------------------------------------------------------------- label LOD0 faces by nearest part point
merged_into = locals().get("merged_into", {})
all_pts = np.concatenate([p["points"] for p in parts if len(p["points"])])
labels = np.concatenate([np.full(len(p["points"]), merged_into.get(i, i), np.int32) for i, p in enumerate(parts) if len(p["points"])])
tree = kdtree.KDTree(len(all_pts))
for i, q in enumerate(all_pts):
    tree.insert(Vector(q.tolist()), i)
tree.balance()
mesh = body.data
nf = len(mesh.polygons)
centres = np.empty(nf * 3, np.float32)
mesh.polygons.foreach_get("center", centres)
centres = centres.reshape(-1, 3)
face_label = np.empty(nf, np.int32)
for i in range(nf):
    _co, idx, _d = tree.find(Vector(centres[i].tolist()))
    face_label[i] = labels[idx]

# ---------------------------------------------------------------- separate each wheel (bmesh: no edit-mode selection needed)
import bmesh  # noqa: E402


def faces_subset(src, keep_mask, name):
    """A new object holding only the faces where keep_mask is True, with the same materials and UVs."""
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.faces.ensure_lookup_table()
    doomed = [f for f in bm.faces if not keep_mask[f.index]]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in src.data.materials:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


wheels = []
wheel_mask_all = np.zeros(nf, bool)
for wid in wheel_ids:
    sel = face_label == wid
    if sel.sum() < 30:
        continue
    c = (parts[wid]["hi"] + parts[wid]["lo"]) * 0.5
    e = parts[wid]["hi"] - parts[wid]["lo"]
    side = "L" if c[1] > 0 else "R"
    end = "F" if c[0] > 0 else "B"
    w = faces_subset(body, sel, "Wheel_%s%s" % (end, side))
    wheel_mask_all |= sel
    wheels.append({"object": w, "centre": c.tolist(), "radius": float(max(e[0], e[2]) * 0.5), "faces": int(sel.sum())})
# the body keeps everything that is not a wheel
rest = faces_subset(body, ~wheel_mask_all, "SK_%s_Body" % NAME)
bpy.data.objects.remove(body, do_unlink=True)
body = rest
# disambiguate duplicate names (six-wheelers)
seen = {}
for w in wheels:
    n = w["object"].name.split(".")[0]
    seen[n] = seen.get(n, 0) + 1
    if seen[n] > 1:
        w["object"].name = "%s%d" % (n, seen[n])
log("wheels separated: %s" % ", ".join("%s (%d faces, r=%.2f)" % (w["object"].name, w["faces"], w["radius"]) for w in wheels))

# ---------------------------------------------------------------- armature
arm_data = bpy.data.armatures.new("SK_%s_Skeleton" % NAME)
arm = bpy.data.objects.new("SK_" + NAME, arm_data)
bpy.context.collection.objects.link(arm)
blib.select_only([arm])
bpy.ops.object.mode_set(mode="EDIT")
root = arm_data.edit_bones.new("root")
root.head = (0, 0, 0)
root.tail = (0, 0, max(0.1, height * 0.2))
for w in wheels:
    b = arm_data.edit_bones.new(w["object"].name)
    c = Vector(w["centre"])
    b.head = c
    b.tail = c + Vector((0, w["radius"] * 0.5, 0))         # bone Y along the axle: spin the wheel about its own Y
    b.parent = root
bpy.ops.object.mode_set(mode="OBJECT")


def bind(ob, bone):
    ob.parent = arm
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    vg = ob.vertex_groups.new(name=bone)
    vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True


bind(body, "root")
for w in wheels:
    bind(w["object"], w["object"].name)

# ---------------------------------------------------------------- export
objs = [arm, body] + [w["object"] for w in wheels]
blib.select_only(objs)
fbx = os.path.join(OUT, "SK_%s.fbx" % NAME)
bpy.ops.export_scene.fbx(filepath=fbx, use_selection=True, object_types={"ARMATURE", "MESH"}, apply_unit_scale=True,
                         apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE",
                         use_mesh_modifiers=False, path_mode="STRIP", embed_textures=False, add_leaf_bones=False,
                         bake_anim=False, use_armature_deform_only=True)
glb = os.path.join(OUT, "SK_%s.glb" % NAME)
bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB", export_yup=True)
blend = os.path.join(OUT, "SK_%s.blend" % NAME)
bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
result.update({"status": "rigged", "bones": ["root"] + [w["object"].name for w in wheels],
               "wheels": [{"bone": w["object"].name, "centre": w["centre"], "radius": w["radius"], "faces": w["faces"]} for w in wheels],
               "files": [os.path.basename(p) for p in (fbx, glb, blend)]})
json.dump(result, open(os.path.join(OUT, "rig.json"), "w"), indent=1)
log("done: %d wheel bones" % len(wheels))

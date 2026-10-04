"""The segmenter's parts mapped back onto the registered seed (2026-10-04): every face of the seed takes the label of
the nearest part face, written as the ms_segment face attribute (the geometry is not touched; `ms segment` keeps
no copy because nothing else changes), a JSON of every label's size and percent box in the part's own frame, and
a render with each label in its own colour for the agent to Read and name.
    blender -b --factory-startup -Y --python segment_apply.py -- <args.json>
args: {"blend", "parts": [fbx, ...], "out_json", "out_render", "out_side_render"}"""
import colorsys
import json
import os
import sys

import bpy
import numpy as np
from mathutils import kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args["blend"]))
ob = next(o for o in bpy.data.objects if o.type == "MESH")
lo, hi = blib.dims(ob)


def centres(o):
    me = o.data
    c = np.empty(len(me.polygons) * 3, np.float32)
    me.polygons.foreach_get("center", c)
    M = np.array(o.matrix_world)
    return c.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


pts, labels = [], []
for i, path in enumerate(args["parts"]):
    before = set(bpy.data.objects)
    with open(path, "rb") as f:
        head = f.read(4)
    if head == b"glTF":
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))     # Hunyuan3D-Part names its GLB parts .fbx (2026-10-04)
    else:
        bpy.ops.import_scene.fbx(filepath=os.path.abspath(path))
    for o in [o for o in bpy.data.objects if o not in before]:
        if o.type == "MESH" and len(o.data.polygons):
            c = centres(o)
            pts.append(c)
            labels.append(np.full(len(c), i, np.int32))
        bpy.data.objects.remove(o, do_unlink=True)
if not pts:
    sys.exit("[segment_apply] the parts hold no faces")
pts, labels = np.concatenate(pts), np.concatenate(labels)
# the service may hand the parts back re-centred or re-scaled: the union of the parts is fitted onto the seed's box
plo, phi = pts.min(axis=0), pts.max(axis=0)
seed_lo, seed_hi = np.array(lo), np.array(hi)
scale = float(np.linalg.norm(seed_hi - seed_lo) / max(np.linalg.norm(phi - plo), 1e-9))
fitted = abs(scale - 1) > 0.02 or np.abs((plo + phi) / 2 - (seed_lo + seed_hi) / 2).max() > 0.02 * np.linalg.norm(seed_hi - seed_lo)
if fitted:
    pts = (pts - (plo + phi) / 2) * scale + (seed_lo + seed_hi) / 2
kd = kdtree.KDTree(len(pts))
for i, p in enumerate(pts):
    kd.insert(p, i)
kd.balance()
seed_c = centres(ob)
face_label = np.empty(len(seed_c), np.int32)
dist = np.empty(len(seed_c), np.float32)
for i, c in enumerate(seed_c):
    _co, idx, d = kd.find(c)
    face_label[i], dist[i] = labels[idx], d
att = ob.data.attributes.get("ms_segment") or ob.data.attributes.new("ms_segment", "INT", "FACE")
att.data.foreach_set("value", face_label)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["blend"]), compress=True)

# the labels' sizes and percent boxes in the part's frame (forward right, 0 = left/top; front_span 0 = the right side)
area = np.empty(len(ob.data.polygons), np.float32)
ob.data.polygons.foreach_get("area", area)
size = np.maximum(seed_hi - seed_lo, 1e-9)
diag = float(np.linalg.norm(seed_hi - seed_lo))
n_labels = int(face_label.max()) + 1
out = {"part": ob.name, "labels": [], "faces": int(len(face_label)), "parts_received": len(args["parts"]),
       "parts_refitted": bool(fitted), "median_match_m": round(float(np.median(dist)), 5)}
palette = {}
for k in range(n_labels):
    sel = face_label == k
    if not sel.any():
        continue
    c = seed_c[sel]
    x0, x1 = (c[:, 0].min() - seed_lo[0]) / size[0] * 100, (c[:, 0].max() - seed_lo[0]) / size[0] * 100
    zt, zb = (seed_hi[2] - c[:, 2].max()) / size[2] * 100, (seed_hi[2] - c[:, 2].min()) / size[2] * 100
    y0, y1 = (c[:, 1].min() - seed_lo[1]) / size[1] * 100, (c[:, 1].max() - seed_lo[1]) / size[1] * 100
    rgb = colorsys.hsv_to_rgb((k * 0.618034) % 1.0, 0.75, 0.95)
    palette[k] = rgb
    out["labels"].append({"label": k, "faces": int(sel.sum()), "share": round(float(area[sel].sum() / max(area.sum(), 1e-12)), 4),
                          "side_box": [round(float(v), 1) for v in (x0, x1, zt, zb)],
                          "front_span": [round(float(v), 1) for v in (y0, y1)],
                          "colour": "#%02x%02x%02x" % tuple(int(v * 255) for v in rgb)})
json.dump(out, open(os.path.abspath(args["out_json"]), "w"), indent=1)

# the render: one flat colour per label, no texture, so the agent can tell the labels apart
ob.data.materials.clear()
for k in range(n_labels):
    m = bpy.data.materials.new("Seg_%d" % k)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    rgb = palette.get(k, (0.5, 0.5, 0.5))
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Roughness"].default_value = 0.7
    ob.data.materials.append(m)
ob.data.polygons.foreach_set("material_index", face_label)
ob.data.update()
blib.setup_render(768, 24, look="preview")
st = blib.Stage(ob, look="preview")
st.render("iso", os.path.abspath(args["out_render"]))
if args.get("out_side_render"):
    st.render("side", os.path.abspath(args["out_side_render"]))
st.close()
print("[segment_apply] %d labels on %d faces (median match %.1f mm%s) -> %s" % (
    len(out["labels"]), len(face_label), float(np.median(dist)) * 1000, ", parts refitted to the seed's box" if fitted else "",
    args["out_json"]), flush=True)

"""One close-up of a delivered asset, the way a reviewer looks (inside Blender):
    blender -b --factory-startup -Y --python closeup.py -- <args.json>
args: {"blend", "name", "out", "view", "focus_min", "focus_max", "unlit", "clay", "hide": [...], "highlight": [...],
       "boxes": {name: [lo, hi]}, "section": [axis, value], "size"}
2026-09-29: the Havoc's glass and cockpit review took ~17 throwaway probe scripts (picked faces in red, glass hidden,
the lining bright, lettering lit and unlit, sections through the cockpit). This is all of them, on the delivery."""
import json
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME = args["name"]
bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args["blend"]))
target = bpy.data.objects.get("SM_" + NAME) or max((o for o in bpy.data.objects if o.type == "MESH"),
                                                    key=lambda o: len(o.data.polygons))
for o in list(bpy.data.objects):
    if o is not target and o.type in ("MESH", "CAMERA", "LIGHT"):
        bpy.data.objects.remove(o, do_unlink=True)
me = target.data
done = []

# extra view directions beside blib's: the back, the far (right, +Y) side and from below
blib.VIEW_DIRS.update({"left": (0, -1, 0.05), "right": (0, 1, 0.05), "back": (-1, 0, 0.05), "bottom": (0.001, 0.001, -1),
                       "iso_rear": (-1, 1, 0.7), "iso_low": (1, -1, -0.5)})


def slot_kind(m):
    """Which delivered material a slot is: glass, lining (interior), frame, or the atlas body."""
    n = (m.name if m else "").lower()
    return "glass" if n.endswith("_glass") else "lining" if n.endswith("_interior") else "frame" if n.endswith("_frame") else "body"


def flat(name, rgba, emit=0.0):
    m = bpy.data.materials.new(name)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = 0.6
    b.inputs["Metallic"].default_value = 0.0
    if emit:
        b.inputs["Emission Color"].default_value = rgba
        b.inputs["Emission Strength"].default_value = emit
    return m


def faces_where(test):
    """Indices of faces whose centre passes `test(centres) -> bool array`."""
    n = len(me.polygons)
    c = np.empty(n * 3, np.float32)
    me.polygons.foreach_get("center", c)
    return np.nonzero(test(c.reshape(-1, 3)))[0]


def delete_faces(idx):
    if not len(idx):
        return
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[int(i)] for i in idx], context="FACES")
    bm.to_mesh(me)
    bm.free()
    me.update()


kinds = [slot_kind(sl.material) for sl in target.material_slots]
# --hide glass|lining|frame: those faces go (what is behind the glass, the cockpit under it)
for what in args.get("hide") or []:
    slots = [i for i, k in enumerate(kinds) if k == what]
    if slots:
        idx = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("material_index", idx)
        delete_faces(np.nonzero(np.isin(idx, slots))[0])
        done.append("hid %s" % what)
# --section y=0.1: the model cut open, the near side (towards the camera) taken away
if args.get("section"):
    axis, value = args["section"]
    k = "xyz".index(axis)
    sign = {"x": 1, "y": -1, "z": 1}[axis]               # front (+x) / left (-y) / top (+z) halves go
    delete_faces(faces_where(lambda c: (c[:, k] - value) * sign > 0))
    done.append("section %s=%.3f" % (axis, value))
# --clay: one grey material everywhere but the glass (shape only, no paint)
if args.get("clay"):
    clay = flat("ms_clay", (0.62, 0.62, 0.6, 1.0))
    for sl, kind in zip(target.material_slots, kinds):
        if kind != "glass":
            sl.material = clay
    done.append("clay")
# --unlit: the body's base colour emitted as it is (the paint without its shading: lettering ghosts from the normal
# map or slivers show up as what they are)
if args.get("unlit"):
    for sl in target.material_slots:
        m = sl.material
        if not m or not m.node_tree or slot_kind(m) == "glass":
            continue
        t = m.node_tree
        b = next((n for n in t.nodes if n.type == "BSDF_PRINCIPLED"), None)
        outn = next((n for n in t.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if b is None or outn is None:
            continue
        e = t.nodes.new("ShaderNodeEmission")
        src = b.inputs["Base Color"]
        if src.is_linked:
            t.links.new(src.links[0].from_socket, e.inputs["Color"])
        else:
            e.inputs["Color"].default_value = src.default_value
        t.links.new(e.outputs[0], outn.inputs["Surface"])
    done.append("unlit")
# --highlight glass|lining|frame|<box name>: bright red over those faces
for what in args.get("highlight") or []:
    red = flat("ms_highlight_%s" % what, (0.95, 0.05, 0.03, 1.0), emit=2.0)
    if what in ("glass", "lining", "frame"):
        for sl, kind in zip(target.material_slots, kinds):
            if kind == what:
                sl.material = red
        done.append("highlight %s" % what)
        continue
    box = (args.get("boxes") or {}).get(what)
    if not box:
        done.append("highlight %s: no such zone or part box" % what)
        continue
    lo, hi = np.array(box[0]), np.array(box[1])
    idx = faces_where(lambda c: np.all((c >= lo) & (c <= hi), axis=1))
    me.materials.append(red)
    mi = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("material_index", mi)
    mi[idx] = len(me.materials) - 1
    me.polygons.foreach_set("material_index", mi)
    me.update()
    done.append("highlight %s (%d faces)" % (what, len(idx)))

look = "probe" if args.get("clay") else "preview"
blib.setup_render(int(args.get("size", 1024)), 32, look=look)
if args.get("unlit"):
    bpy.context.scene.view_settings.view_transform = "Standard"
focus = None
if args.get("focus_min") and args.get("focus_max"):
    focus = (Vector(args["focus_min"]), Vector(args["focus_max"]))
st = blib.Stage(target, look=look, focus_bounds=focus)
st.render(args.get("view", "iso"), os.path.abspath(args["out"]))
st.close()
json.dump({"out": args["out"], "done": done}, open(os.path.splitext(args["out"])[0] + ".json", "w"), indent=1)
print("[closeup] %s: %s" % (args["out"], "; ".join(done) or "as delivered"), flush=True)

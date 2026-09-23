"""Inside Blender: orthographic renders of a mesh from cameras whose frame is known exactly.
    blender -b --python ortho_views.py -- <args.json>
      {"glb", "out_dir", "size", "views": ["front", ...], "frames": [{"name", "view", "lo": [x,y,z], "hi": [x,y,z]}]}
`views` frame the whole object; `frames` are close-ups of a box (a part's bounds) from a view. views.json records,
per render, the world-space RIGHT and UP vectors of the image, the frame size S (metres across the image) and the
centre C, so that a point p maps to u = dot(p - C, R) / S + 0.5, v = dot(p - C, U) / S + 0.5. The picture model
repaints these renders photoreal (keeping the framing) and the surface pass projects them back with that formula."""
import json
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
OUT = args["out_dir"]
os.makedirs(OUT, exist_ok=True)
SIZE = int(args.get("size", 1024))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["glb"]))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
blib.select_only(meshes)
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
lo, hi = blib.dims(ob)
blib.setup_render(SIZE, 16, look="probe")
scn = bpy.context.scene
st = blib.Stage(ob)
cam = st.cam
records = {}
for view in args.get("views") or ["front", "left", "back", "right", "top"]:
    rec = blib.ortho_camera(cam, view, lo, hi)
    path = os.path.join(OUT, "ortho_%s.png" % view)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    records[view] = {**rec, "file": path}
for fr in args.get("frames") or []:
    flo, fhi = Vector(fr["lo"]), Vector(fr["hi"])
    rec = blib.ortho_camera(cam, fr["view"], flo, fhi, margin=1.15)
    path = os.path.join(OUT, "ortho_%s.png" % fr["name"])
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    records[fr["name"]] = {**rec, "file": path, "frame": True, "lo": list(flo), "hi": list(fhi)}
st.close()
json.dump(records, open(os.path.join(OUT, "views.json"), "w"), indent=1)
print("[ortho] %d render(s)" % len(records), flush=True)

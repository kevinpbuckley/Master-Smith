"""A registered seed exported for the part segmenter (2026-10-04): welded, decimated under the service's face limit
(Hunyuan3D-Part takes an FBX of at most 30k faces) and written as FBX, the seed itself untouched.
    blender -b --factory-startup -Y --python segment_export.py -- <args.json>
args: {"blend", "out", "max_faces"}"""
import json
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args["blend"]))
ob = next(o for o in bpy.data.objects if o.type == "MESH")
probe = ob.copy()
probe.data = ob.data.copy()
probe.name = "SegmentProbe"
bpy.context.collection.objects.link(probe)
lo, hi = blib.dims(probe)
bm = bmesh.new()
bm.from_mesh(probe.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=max((hi - lo).length * 1e-6, 1e-9))   # a Tripo seed is split on every seam
bm.to_mesh(probe.data)
bm.free()
tris = blib.tri_count(probe)
limit = int(args.get("max_faces", 28000))
if tris > limit:
    m = probe.modifiers.new("dec", "DECIMATE")
    m.ratio = limit / float(tris)
    m.use_collapse_triangulate = True
    blib.select_only([probe])
    bpy.ops.object.modifier_apply(modifier="dec")
blib.select_only([probe])
out = os.path.abspath(args["out"])
os.makedirs(os.path.dirname(out), exist_ok=True)
bpy.ops.export_scene.fbx(filepath=out, use_selection=True, path_mode="STRIP", embed_textures=False, bake_anim=False,
                         add_leaf_bones=False, mesh_smooth_type="FACE")
faces = len(probe.data.polygons)
json.dump({"faces": faces, "triangles_before": tris, "bytes": os.path.getsize(out), "bounds_m": [list(lo), list(hi)]},
          open(os.path.splitext(out)[0] + ".json", "w"), indent=1)
print("[segment_export] %d faces (from %d triangles) -> %s" % (faces, tris, out), flush=True)

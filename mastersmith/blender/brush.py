"""Headless brush strokes on a registered part (issue #13).
    blender -b -Y --python brush.py -- <args.json>
args: {"blend", "strokes": [{"op", "at", "radius", "strength", ...}], "out_blend", "out_render", "out_json"}
The strokes are mastersmith.sculpt.stroke() records in the part's own frame (metres, the part centred at the origin
as register_part.py left it). The mesh is edited in place and saved; the render shows the result."""
import json
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import blib  # noqa: E402
from mastersmith import sculpt  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args["blend"]))
ob = next(o for o in bpy.data.objects if o.type == "MESH")
me = ob.data


def read_mesh():
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", v)
    f = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", f)
    return v.reshape(-1, 3).astype(np.float64), f.reshape(-1, 3).astype(np.int64)


def symmetrize(verts, mid_y, keep):
    """The kept half (keep "-y" or "+y") mirrored onto the other across y = mid_y: cut at the plane, the far half
    deleted, the kept half duplicated with scale -1 (UVs, materials and segment labels come along), the seam welded.
    A seed lopsided on one side is repaired about its own centre plane (AGENTS.md; the Proteus P2's port wing and
    stern were narrower than its starboard ones, 2026-10-23). -> (verts, faces) of the new mesh"""
    import bmesh
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    sign = -1.0 if keep == "-y" else 1.0
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    # clear_outer removes the side the normal points to: the far half
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0.0, mid_y, 0.0), plane_no=(0.0, -sign, 0.0), clear_outer=True)
    span = float(np.ptp(verts, axis=0).max())
    eps = span * 1e-5
    dup = bmesh.ops.duplicate(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:])
    new_v = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in new_v:
        v.co.y = 2 * mid_y - v.co.y
    bmesh.ops.reverse_faces(bm, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    seam = [v for v in bm.verts if abs(v.co.y - mid_y) <= 2 * eps]
    bmesh.ops.remove_doubles(bm, verts=seam, dist=4 * eps)
    bm.to_mesh(me)
    bm.free()
    me.validate()
    me.update()
    return read_mesh()


verts, faces = read_mesh()
# the seed is in the mesher's units and only reaches its box's metres at assembly: strokes are given in metres of
# the finished part, so scale them into the mesh (per axis for positions, the mean for radii and strengths)
ext = verts.max(axis=0) - verts.min(axis=0)
box = np.asarray(args.get("box_size") or ext, dtype=np.float64)
sc = ext / np.maximum(box, 1e-9)
k = float(sc.mean())
centre = (verts.max(axis=0) + verts.min(axis=0)) / 2
before = verts.copy()
resized = False
for op in args["strokes"]:
    op = dict(op)
    if op["op"] == "symmetrize":
        verts, faces = symmetrize(verts, float(centre[1] + float(op.get("mid_y", 0.0)) * sc[1]), op.get("keep", "-y"))
        resized = True
        continue
    op["at"] = list(centre + np.asarray(op.get("at", (0, 0, 0))) * sc)
    if "to" in op:
        op["to"] = list(centre + np.asarray(op["to"]) * sc)
    if "delta" in op:
        op["delta"] = list(np.asarray(op["delta"]) * sc)
    op["radius"] = float(op.get("radius", 0.01)) * k
    if op["op"] == "taper":
        # the profile's X and the core's half-width in the mesh's own units, about its centre plane
        op["profile"] = [[centre[0] + x * sc[0], s] for x, s in op["profile"]]
        op["core"] = float(op["core"]) * sc[1]
        if op.get("band") is not None:
            op["band"] = float(op["band"]) * sc[1]
        op["mid_y"] = float(centre[1])
    if op["op"] == "inflate":
        op["strength"] = float(op.get("strength", 0.0)) * k
    if op.get("segment") is not None:
        # a rigid move of the faces `ms segment` labelled so (the Proteus P2's pods, slid inboard, 2026-10-23)
        att = me.attributes.get("ms_segment")
        if att is None:
            raise SystemExit("brush --segment: the mesh has no ms_segment labels (run ms segment first)")
        lab = np.empty(len(me.polygons), np.int32)
        att.data.foreach_get("value", lab)
        want = set(int(v) for v in op["segment"])
        mask = np.zeros(len(verts), bool)
        for poly in me.polygons:
            if int(lab[poly.index]) in want:
                mask[list(poly.vertices)] = True
        op["mask"] = mask
    verts = sculpt.stroke(verts, faces, op)
moved = np.linalg.norm(verts - before, axis=1) / k if not resized else np.zeros(len(verts))
me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
me.update()
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["out_blend"]), compress=True)
if args.get("out_render"):
    blib.setup_render(512, 24, look="preview")
    st = blib.Stage(ob, look="preview")
    st.render("iso", os.path.abspath(args["out_render"]))
    st.close()
json.dump({"strokes": len(args["strokes"]), "vertices_moved": int((moved > 1e-6).sum()), "vertices": len(verts),
           "max_move_mm": round(float(moved.max()) * 1000, 3)}, open(args["out_json"], "w"), indent=1)
print("[brush] %d strokes moved %d of %d vertices, up to %.2f mm" % (len(args["strokes"]), (moved > 1e-6).sum(), len(verts), moved.max() * 1000), flush=True)

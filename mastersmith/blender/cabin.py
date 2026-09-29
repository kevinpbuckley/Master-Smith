"""Measure the cockpit well of a body, so an interior part's box is the space it has (inside Blender).
    blender -b -Y --python cabin.py -- <args.json>
args: {"hull_blend", "box_min", "box_max", "keep_depth", "x_range": [x0, x1] metres, "out_json"}

The body's registered seed is placed in its planned box the way assemble.py places it, then rays find, at stations
along x_range, the floor of the open well (straight down the centreline from above), its side walls (sideways from just
above the floor) and the sill on each side (down just outside each wall). 2026-09-29: the owner asked for the cabin's
dimensions "so we know it fits" instead of a cockpit coded into a box read off the picture."""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(os.path.abspath(args["hull_blend"]), link=False) as (src, dst):
    dst.objects = [n for n in src.objects]
meshes = [o for o in dst.objects if o is not None and o.type == "MESH"]
for o in meshes:
    bpy.context.collection.objects.link(o)
blib.select_only(meshes)
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# placed like assemble.py's fit() places the largest vendor part
bmin, bmax = Vector(args["box_min"]), Vector(args["box_max"])
centre, size = (bmin + bmax) * 0.5, bmax - bmin
lo, hi = blib.dims(ob)
ext = hi - lo
ratios = [size[i] / max(ext[i], 1e-9) for i in range(3)]
s = sorted(ratios)[1]
scale = [r if r / s <= 1.8 and s / r <= 1.8 else s for r in ratios]
if args.get("keep_depth"):
    scale[1] = math.sqrt(scale[0] * scale[2])
ob.data.transform(Matrix.Translation(-(lo + hi) * 0.5))
ob.data.transform(Matrix.Diagonal(Vector(scale).to_4d()))
ob.data.transform(Matrix.Translation(centre))
me = ob.data
me.calc_loop_triangles()
co = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", co)
tri = np.empty(len(me.loop_triangles) * 3, np.int32)
me.loop_triangles.foreach_get("vertices", tri)
tree = BVHTree.FromPolygons([Vector(v) for v in co.reshape(-1, 3)], tri.reshape(-1, 3).tolist())
lo, hi = blib.dims(ob)
H = hi.z - lo.z


def first_hit(origin, direction, far):
    loc, _n, _i, dist = tree.ray_cast(Vector(origin), Vector(direction), far)
    return (loc, dist) if loc is not None else (None, None)


stations = []
x0, x1 = (float(v) for v in args["x_range"])
for x in np.linspace(x0, x1, 11):
    top = hi.z + 0.05 * H
    floor, _d = first_hit((x, 0.0, top), (0, 0, -1), 2 * H + 1)
    if floor is None:
        continue
    probe_z = floor.z + 0.06 * H
    left, dl = first_hit((x, 0.0, probe_z), (0, 1, 0), 10 * H)
    right, dr = first_hit((x, 0.0, probe_z), (0, -1, 0), 10 * H)
    sills = []
    for y in ((dl or 0.0) + 0.02 * H, -((dr or 0.0) + 0.02 * H)):
        rim, _ = first_hit((x, y, top), (0, 0, -1), 2 * H + 1)
        sills.append(rim.z if rim is not None else None)
    well = all(v is not None for v in sills) and floor.z < min(sills) - 0.08 * H and dl and dr
    stations.append({"x": round(float(x), 4), "floor_z": round(floor.z, 4), "wall_left_y": round(dl, 4) if dl else None,
                     "wall_right_y": round(-dr, 4) if dr else None, "sill_z": [round(v, 4) if v is not None else None for v in sills],
                     "well": bool(well)})
inside = [st for st in stations if st["well"]]
res = {"stations": stations, "hull_bounds": [[round(v, 4) for v in lo], [round(v, 4) for v in hi]]}
if inside:
    step = (x1 - x0) / 10.0
    half = min(min(st["wall_left_y"], -st["wall_right_y"]) for st in inside)
    floor = float(np.median([st["floor_z"] for st in inside]))
    sill = min(min(st["sill_z"]) for st in inside)
    res["well"] = {"x": [round(inside[0]["x"] - step / 2, 4), round(inside[-1]["x"] + step / 2, 4)],
                   "half_width": round(half, 4), "floor_z": round(floor, 4), "sill_z": round(sill, 4)}
json.dump(res, open(args["out_json"], "w"), indent=1)
print("[cabin] %d stations, %d in the well" % (len(stations), len(inside)), flush=True)

"""Export a registered seed's geometry for a mesh-to-texture vendor, or take the vendor's retextured mesh back in its place.
    blender -b -Y --python swap_seed.py -- <args.json>
args: {"mode": "export", "blend", "out_glb"}  - the registered mesh with ONE UV layer and no textures (Tonetta's
      retexture export: a second UV layer or the old maps confuse the vendor), in the registered frame.
      {"mode": "import", "blend", "glb", "out_blend", "out_render", "out_json"} - the retextured GLB fitted back onto the
      registered mesh's own bounds (a vendor may re-centre or rescale what it returns) and saved as the new
      registered.blend."""
import json
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))


def mesh_of_blend(path):
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(path))
    return next(o for o in bpy.data.objects if o.type == "MESH")


def export_glb(ob, path):
    blib.select_only([ob])
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(path), export_format="GLB", use_selection=True,
                              export_materials="NONE", export_apply=True)          # UVs and normals go by default
    return os.path.getsize(path)


if args["mode"] == "export":
    ob = mesh_of_blend(args["blend"])
    while len(ob.data.uv_layers) > 1:
        ob.data.uv_layers.remove(ob.data.uv_layers[-1])
    ob.data.materials.clear()
    size = export_glb(ob, args["out_glb"])
    # 2026-10-23: the vendor takes 18 MB; a 107k-face Hi3D seed exported at 21 MB. Collapse-decimate the COPY that
    # goes out until it fits (the registered mesh itself is untouched; the texture comes back on the decimated
    # mesh's UVs, so that mesh replaces the seed on import, still well inside the triangle budget)
    limit = args.get("max_bytes")
    if limit and size > limit:
        bpy.context.view_layer.objects.active = ob
        mod = ob.modifiers.new("fit", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.use_collapse_triangulate = True
        ratio = 1.0
        for _ in range(6):
            ratio *= 0.9 * limit / size
            mod.ratio = ratio
            size = export_glb(ob, args["out_glb"])      # export_apply writes the modified mesh
            if size <= limit:
                break
        print("[swap] decimated the export to ratio %.2f (%.1f MB)" % (ratio, size / 1e6), flush=True)
    print("[swap] exported %d faces -> %s" % (len(ob.data.polygons), args["out_glb"]), flush=True)
else:
    old = mesh_of_blend(args["blend"])
    lo, hi = blib.dims(old)
    old_me = old.data                    # kept (no users) for the segment labels below
    bpy.data.objects.remove(old, do_unlink=True)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["glb"]))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in [o for o in new if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    blib.select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    nlo, nhi = blib.dims(ob)
    ext, next_ = hi - lo, nhi - nlo
    scale = [ext[i] / max(next_[i], 1e-9) for i in range(3)]
    ob.data.transform(Matrix.Translation(-(nlo + nhi) * 0.5))
    ob.data.transform(Matrix.Diagonal(Vector(scale).to_4d()))
    ob.data.transform(Matrix.Translation((lo + hi) * 0.5))
    ob.name = "Part"
    # 2026-10-23: the segmentation's labels (ms_segment, from ms segment) live on the old mesh's faces and the plan's
    # zones name them; the vendor's mesh is new geometry, so every new face takes the label of the nearest old face
    moved = 0
    try:
        import numpy as np
        from mathutils.kdtree import KDTree
        if old_me.attributes.get("ms_segment") is not None:
            n_old = len(old_me.polygons)
            lab = np.empty(n_old, np.int32)
            old_me.attributes["ms_segment"].data.foreach_get("value", lab)
            cen = np.empty(n_old * 3, np.float32)
            old_me.polygons.foreach_get("center", cen)
            cen = cen.reshape(-1, 3)
            kd = KDTree(n_old)
            for i in range(n_old):
                kd.insert(cen[i], i)
            kd.balance()
            att = ob.data.attributes.get("ms_segment") or ob.data.attributes.new("ms_segment", "INT", "FACE")
            out = np.empty(len(ob.data.polygons), np.int32)
            for i, f in enumerate(ob.data.polygons):
                out[i] = lab[kd.find(f.center)[1]]
            att.data.foreach_set("value", out)
            moved = int(len(out))
            bpy.data.meshes.remove(old_me)
    except Exception as e:  # noqa: BLE001 - a seed never segmented has nothing to carry
        print("[swap] segment labels not carried: %s" % e, flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["out_blend"]), compress=True)
    if args.get("out_render"):
        blib.setup_render(512, 24, look="preview")
        st = blib.Stage(ob, look="preview")
        st.render("iso", os.path.abspath(args["out_render"]))
        st.close()
    json.dump({"refit_scale": [round(v, 4) for v in scale], "faces": len(ob.data.polygons), "segment_labels_carried": moved},
              open(args["out_json"], "w"), indent=1)
    print("[swap] retextured mesh in place (refit %s)" % [round(v, 3) for v in scale], flush=True)

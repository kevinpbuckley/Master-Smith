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


if args["mode"] == "export":
    ob = mesh_of_blend(args["blend"])
    while len(ob.data.uv_layers) > 1:
        ob.data.uv_layers.remove(ob.data.uv_layers[-1])
    ob.data.materials.clear()
    blib.select_only([ob])
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(args["out_glb"]), export_format="GLB", use_selection=True,
                              export_materials="NONE", export_apply=True)          # UVs and normals go by default
    print("[swap] exported %d faces -> %s" % (len(ob.data.polygons), args["out_glb"]), flush=True)
else:
    old = mesh_of_blend(args["blend"])
    lo, hi = blib.dims(old)
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
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["out_blend"]), compress=True)
    if args.get("out_render"):
        blib.setup_render(512, 24, look="preview")
        st = blib.Stage(ob, look="preview")
        st.render("iso", os.path.abspath(args["out_render"]))
        st.close()
    json.dump({"refit_scale": [round(v, 4) for v in scale], "faces": len(ob.data.polygons)}, open(args["out_json"], "w"), indent=1)
    print("[swap] retextured mesh in place (refit %s)" % [round(v, 3) for v in scale], flush=True)

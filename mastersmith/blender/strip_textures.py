"""blender -b --python strip_textures.py -- <in.glb> <out.glb>: the same mesh and UVs, no images or materials.
A retexture vendor paints onto the UVs; the 4k maps packed in a delivered GLB only make the upload too big."""
import os
import sys

import bpy

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(src))
for o in list(bpy.data.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
for o in bpy.data.objects:
    o.data.materials.clear()
for m in list(bpy.data.materials):
    bpy.data.materials.remove(m)
for img in list(bpy.data.images):
    bpy.data.images.remove(img)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=os.path.abspath(dst), export_format="GLB", use_selection=True, export_materials="NONE",
                          export_image_format="NONE", export_texcoords=True, export_normals=True, export_apply=True,
                          export_animations=False, export_skins=False, export_yup=True)
print("[strip] %s -> %s: %.1f MB" % (os.path.basename(src), os.path.basename(dst), os.path.getsize(dst) / 1e6))

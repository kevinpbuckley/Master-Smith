"""Bake the seed's colour and surface detail onto the posed MetaHuman mesh Unreal generated from the conformed DNA
(inside Blender):
    blender -b --factory-startup -Y --python mh_bake.py -- <args.json>
args: {"source": the textured seed in the conform's frame (<Name>_conform.glb, or seed.glb / registered.blend),
       "posed_fbx": the skeletal mesh Unreal generated from the POSED DNA (Mesh to MetaHuman tab > save pose > generate
                    skeletal mesh > Asset Actions > Export), "name", "out_dir", "resolution": 4096, "cage_m": 0.012,
       "maps": ["color", "normal"]}
Writes T_<Name>_Head_BC.png / _N.png and T_<Name>_Body_BC.png / _N.png on the MetaHuman UV layout (head on tile
1001, the body's tile 1002 moved onto 0-1 so Blender can bake it), bake_report.json and bake_preview_<front|side>.png.

Why (the video, 2026-10-04): the MetaHuman's own textures are a generic skin; the character's look is baked from the
high-poly seed onto the MetaHuman topology in the SAME pose (the posed DNA), head and body separately, then dropped into
the built MetaHuman's Baked texture folder (T_Body_BC/N, T_Head_LOD*_BC/N) or its material instances. Normal maps baked
here are OpenGL (+Y): tick "Flip Green Channel" when importing them into Unreal."""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402


def plain(o):
    """numpy scalars as JSON values (a numpy bool is not JSON serializable)."""
    return o.item() if hasattr(o, "item") else str(o)

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
NAME = args["name"]
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
RES = int(args.get("resolution", 4096))
CAGE = float(args.get("cage_m", 0.012))
MAPS = args.get("maps") or ["color", "normal"]
report = {"name": NAME, "notes": [], "maps": {}}


def log(msg):
    print("[mh_bake] " + msg, flush=True)
    report["notes"].append(msg)


def load_any(path):
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(path))
        return [o for o in bpy.data.objects if o.type == "MESH"]
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=os.path.abspath(path))
    objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    # whatever transform the importer left on the objects or their parents (a 0.01 unit scale on an FBX root)
    # goes into the mesh data: every tool here works on data in metres with identity objects
    bpy.context.view_layer.update()
    for o in objs:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    return objs


def bounds(objs):
    lo = np.min([np.array(blib.dims(o)[0]) for o in objs], axis=0)
    hi = np.max([np.array(blib.dims(o)[1]) for o in objs], axis=0)
    return lo, hi


bpy.ops.wm.read_factory_settings(use_empty=True)
src = load_any(args["source"])
if not src:
    raise RuntimeError("no mesh in %s" % args["source"])
blib.select_only(src)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if len(src) > 1:
    bpy.ops.object.join()
source = bpy.context.view_layer.objects.active
source.name = "Source"
if not any(m and m.use_nodes and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes) for m in source.data.materials):
    log("the source has no image texture: the colour bake will be its material colour only")

tgt = load_any(args["posed_fbx"])
bpy.context.view_layer.update()
for o in tgt:
    # the importer leaves the centimetre -> metre scale on the armature parent: bake it into the mesh before the
    # armature goes (a head came in 37 m tall without this, 2026-10-04)
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
    bpy.data.objects.remove(o, do_unlink=True)
if not tgt:
    raise RuntimeError("no mesh in %s" % args["posed_fbx"])
# the FBX may carry LODs as separate objects: the one with the most faces is LOD0
target = max(tgt, key=lambda o: len(o.data.polygons))
for o in tgt:
    if o is not target:
        bpy.data.objects.remove(o, do_unlink=True)
blib.select_only([target])
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = target.data
me.validate()

# --- alignment: the posed mesh must sit on the seed (same pose, same scale). Report the residual; a height off by
# more than 3% or a centre off by 3 cm means the two were not the same import, and the bake would smear.
slo, shi = bounds([source])
tlo, thi = bounds([target])
res = {"source_height_m": round(float(shi[2] - slo[2]), 3), "posed_height_m": round(float(thi[2] - tlo[2]), 3),
       "centre_offset_m": [round(float(v), 3) for v in ((shi + slo) / 2 - (thi + tlo) / 2)]}
report["alignment"] = res
if abs(res["source_height_m"] - res["posed_height_m"]) > 0.03 * res["source_height_m"] or max(abs(v) for v in res["centre_offset_m"]) > 0.03:
    log("WARNING the posed mesh does not sit on the seed: %s - the pose or scale differs, the bake will smear" % res)

# --- split head and body by the MetaHuman UV tiles (head and its parts on 1001, the body on 1002)
uv_layer = me.uv_layers.active or me.uv_layers[0]
uv = np.empty(len(me.loops) * 2, np.float32)
uv_layer.data.foreach_get("uv", uv)
uv = uv.reshape(-1, 2)
loop_start = np.empty(len(me.polygons), np.int32)
me.polygons.foreach_get("loop_start", loop_start)
tile_u = np.floor(uv[loop_start, 0]).astype(int)
mat_index = np.empty(len(me.polygons), np.int32)
me.polygons.foreach_get("material_index", mat_index)
slot_names = [s.material.name.lower() if s.material else "" for s in target.material_slots]
report["posed_material_slots"] = slot_names
# on tile 1001 only the skin: teeth, eyes, lashes, shells keep MetaHuman's own maps. A mesh generated from the posed
# DNA carries ONE slot ("worldgridmaterial", 2026-10-04): then the tiles alone tell head from body, which is fine
skin_slots = {i for i, n in enumerate(slot_names) if not any(k in n for k in ("teeth", "eye", "lash", "saliva", "cartilage", "shell", "edge", "hide"))}
is_body = tile_u >= 1
is_head = (tile_u < 1) & np.isin(mat_index, list(skin_slots))
report["face_split"] = {"head_faces": int(is_head.sum()), "body_faces": int(is_body.sum()),
                        "other_faces": int(len(me.polygons) - is_head.sum() - is_body.sum())}
if is_body.sum() == 0:
    log("no faces on UV tile 1002: this FBX is a head only (or its UVs were already moved); the body bake is skipped")
if is_head.sum() == 0:
    log("no skin faces on UV tile 1001: body only, the head bake is skipped")


def part_object(mask, name, shift_u):
    """A copy of the target holding only the masked faces, its UVs moved onto 0-1 when asked."""
    o = target.copy()
    o.data = target.data.copy()
    o.name = o.data.name = name
    bpy.context.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    sel = np.logical_not(mask)
    o.data.polygons.foreach_set("select", sel.astype(bool))
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="FACE")
    bpy.ops.object.mode_set(mode="OBJECT")
    if shift_u:
        l = o.data.uv_layers.active or o.data.uv_layers[0]
        u = np.empty(len(o.data.loops) * 2, np.float32)
        l.data.foreach_get("uv", u)
        u = u.reshape(-1, 2)
        u[:, 0] -= shift_u
        l.data.foreach_set("uv", u.reshape(-1))
    return o


parts = []
if is_head.sum():
    parts.append(("Head", part_object(is_head, "MH_Head", 0)))
if is_body.sum():
    parts.append(("Body", part_object(is_body, "MH_Body", 1)))
bpy.data.objects.remove(target, do_unlink=True)

# --- bake, selected (source) to active (part)
scn = bpy.context.scene
scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = int(args.get("samples", 16))
scn.cycles.use_denoising = False
scn.render.bake.use_selected_to_active = True
scn.render.bake.cage_extrusion = CAGE
scn.render.bake.max_ray_distance = CAGE * 2.5
scn.render.bake.margin = max(16, RES // 128)
scn.render.bake.use_clear = True
scn.render.image_settings.file_format = "PNG"
scn.render.image_settings.color_mode = "RGB"
scn.render.image_settings.color_depth = "8"


def bake(part_name, obj, kind):
    img_name = "T_%s_%s_%s" % (NAME, part_name, "BC" if kind == "color" else "N")
    img = bpy.data.images.new(img_name, RES, RES, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if kind == "color" else "Non-Color"
    img.generated_color = (0.5, 0.5, 1.0, 1.0) if kind == "normal" else (0.0, 0.0, 0.0, 1.0)
    mat = bpy.data.materials.new("Bake_%s_%s" % (part_name, kind))
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if kind == "color":
        scn.render.bake.use_pass_direct = scn.render.bake.use_pass_indirect = False
        scn.render.bake.use_pass_color = True
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, cage_extrusion=CAGE,
                            max_ray_distance=CAGE * 2.5, margin=scn.render.bake.margin, use_clear=True)
    else:
        scn.render.bake.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True, cage_extrusion=CAGE,
                            max_ray_distance=CAGE * 2.5, margin=scn.render.bake.margin, use_clear=True)
    path = os.path.join(OUT, img_name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    # coverage: the share of texels the bake wrote (the UV islands' area plus margin). A flat normal IS the clear
    # colour, so a normal map's coverage is read off the colour bake of the same part (4% on a full head, 2026-10-04)
    if kind == "color":
        px = np.empty(RES * RES * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        covered = float((px[:, :3].max(1) > 0.02).mean())
        coverage_by_part[part_name] = covered
    else:
        covered = coverage_by_part.get(part_name)
    report["maps"][img_name] = {"file": os.path.basename(path), "kind": kind, "part": part_name, "resolution": RES,
                                "coverage": round(covered, 3) if covered is not None else None,
                                "convention": "OpenGL +Y tangent normal (flip green on Unreal import)" if kind == "normal" else "sRGB base colour"}
    log("baked %s (%s of the texels)" % (img_name, ("%.0f%%" % (covered * 100)) if covered is not None else "coverage as the colour map's"))
    return img


baked = {}
coverage_by_part = {}
for part_name, obj in parts:
    for kind in MAPS:
        baked[(part_name, kind)] = bake(part_name, obj, kind)

# --- preview: the parts shaded with their baked colour (and normal), the source hidden
for part_name, obj in parts:
    mat = bpy.data.materials.new("Preview_%s" % part_name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.55
    if (part_name, "color") in baked:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = baked[(part_name, "color")]
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    if (part_name, "normal") in baked:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = baked[(part_name, "normal")]
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
source.hide_render = True
blib.setup_render(int(args.get("size", 768)), 32, look="preview")
objs = [o for _n, o in parts]
blib.select_only(objs)
if len(objs) > 1:
    bpy.ops.object.join()
shown = bpy.context.view_layer.objects.active
stage = blib.Stage(shown, look="preview")
cam = bpy.data.objects.new("ViewCam", bpy.data.cameras.new("ViewCam"))
bpy.context.collection.objects.link(cam)
lo, hi = blib.dims(shown)
renders = {}
for view, cv in (("front", "left"), ("side", "front")):      # the character faces -Y: the "left" camera sees the face
    blib.ortho_camera(cam, cv, lo, hi, margin=1.06)
    scn.camera = cam
    path = os.path.join(OUT, "bake_preview_%s.png" % view)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[view] = os.path.basename(path)
stage.close()
report["renders"] = renders
report["unreal"] = ("drop the T_ maps into the built MetaHuman's Body/Baked and Face/Baked folders over T_Body_BC/N and "
                    "T_Head_LOD*_BC/N, or set them on MI_Body_Baked and MI_Face_Skin_Baked_LOD*; import the _N maps with "
                    "Flip Green Channel ticked (Blender bakes OpenGL +Y)")
json.dump(report, open(os.path.join(OUT, "bake_report.json"), "w", encoding="utf-8"), indent=1, default=plain)
log("done: %s" % ", ".join(report["maps"]))

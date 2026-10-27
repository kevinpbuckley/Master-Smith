"""Bake the seed's colour and surface detail onto the posed MetaHuman mesh Unreal generated from the conformed DNA
(inside Blender):
    blender -b --factory-startup -Y --python mh_bake.py -- <args.json>
args: {"source": the textured seed in the conform's frame (<Name>_conform.glb, or seed.glb / registered.blend),
       "posed_fbx": the skeletal mesh Unreal generated from the POSED DNA (Mesh to MetaHuman tab > save pose > generate
                    skeletal mesh > Asset Actions > Export), "name", "out_dir", "resolution": 4096, "cage_m": 0.012,
       "maps": ["color", "normal"], "head_source": a separate textured head mesh in the same frame (the head part bakes
       from it), "far_pass": false, "skin_color": "#rrggbb" (pale texels on the parts in "skin_parts" take it),
       "skin_parts": ["Body"], "align": true (the posed mesh moved onto the seed's bounds centre before baking),
       "face_fit": true (the head source's face warped onto the MetaHuman's landmarks first, mh_face_fit.py),
       "eye_inset": 0.35 (the seed's painted eye edge that far inside the MetaHuman's lower lid and corners),
       "head_landmarks": {"eye_in_l": [x, y, z], ...} (seed landmarks given by hand, metres, over the detected ones)}
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
# a colour hit darker than this is a miss: a ray that starts inside the seed (a limb the solver made thicker than the
# seed's) hits the far wall from behind and bakes the suit eight times too dark (the AINavigator's elbows, 2026-10-05)
DARK = float(args.get("dark_is_miss", 0.1))
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
# a separate head seed placed by mh_conform (<Name>_head.glb): the head part bakes from it, not from the body seed's
# own soft face (the AINavigator's eyes printed on its cheeks, 2026-10-05)
head_source = None
if args.get("head_source"):
    hs = load_any(args["head_source"])
    if hs:
        blib.select_only(hs)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if len(hs) > 1:
            bpy.ops.object.join()
        head_source = bpy.context.view_layer.objects.active
        head_source.name = "HeadSource"
        log("the head bakes from %s" % os.path.basename(args["head_source"]))

tgt = load_any(args["posed_fbx"])
bpy.context.view_layer.update()


def seed_hand_centre(side_sign):
    """The seed's hand on one side: the outermost tenth of the arm's reach, below the shoulders."""
    sm = source.data
    sco = np.empty(len(sm.vertices) * 3, np.float64)
    sm.vertices.foreach_get("co", sco)
    sco = sco.reshape(-1, 3)
    reach = np.abs(sco[:, 0]).max()
    sel = sco[(side_sign * sco[:, 0] > 0.82 * reach) & (sco[:, 2] < 0.75 * sco[:, 2].max())]
    return Vector(sel.mean(0)) if len(sel) > 20 else None


def swing_arms_onto_seed(arm):
    """Rotate each upper arm about its shoulder so the posed hand bone lands on the seed's hand (2026-10-05: the
    AINavigator's solve stood the arms 12 cm forward of the seed's; a rigid alignment cannot bring a limb back)."""
    out = {}
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for side, sign in (("l", 1), ("r", -1)):
        up, hand = arm.pose.bones.get("upperarm_" + side), arm.pose.bones.get("hand_" + side)
        knuckle = arm.pose.bones.get("middle_01_" + side)
        target = seed_hand_centre(sign)
        if up is None or hand is None or target is None:
            continue
        shoulder = arm.matrix_world @ up.head
        # the palm's centre, not the wrist: matched to the wrist the posed hand stood a palm's length too far out and
        # its back sampled the seed's sleeve (blue hands, 2026-10-05)
        hand_w = arm.matrix_world @ ((hand.head + knuckle.head) / 2 if knuckle is not None else hand.head)
        a = (hand_w - shoulder)
        b = (target - shoulder)
        if a.length < 1e-4 or b.length < 1e-4:
            continue
        rot = a.normalized().rotation_difference(b.normalized())
        out[side] = {"angle_deg": round(math.degrees(rot.angle), 1), "hand_was": [round(v, 3) for v in hand_w], "seed_hand": [round(v, 3) for v in target]}
        # the rotation in armature space, about the shoulder joint; the children follow
        r_arm = arm.matrix_world.to_3x3().inverted() @ rot.to_matrix() @ arm.matrix_world.to_3x3()
        pivot = up.head.copy()
        up.matrix = Matrix.Translation(pivot) @ r_arm.to_4x4() @ Matrix.Translation(-pivot) @ up.matrix
        bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode="OBJECT")
    return out


arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if arms and args.get("swing_arms", True):
    swung = swing_arms_onto_seed(arms[0])
    if swung:
        report["arms_swung_onto_seed"] = swung
        log("arms swung onto the seed's hands: " + ", ".join("%s %.1f deg" % (k, v["angle_deg"]) for k, v in swung.items()))
    dg = bpy.context.evaluated_depsgraph_get()
    for o in tgt:
        posed_me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
        o.modifiers.clear()
        o.data = posed_me
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
if abs(res["source_height_m"] - res["posed_height_m"]) > 0.03 * res["source_height_m"]:
    log("WARNING the posed mesh is not the seed's height: %s - the pose or scale differs, the bake will smear" % res)
elif args.get("align", True):
    # the solver stands the posed body off the mesh (19 cm behind it, then yawed 28 degrees and 6 cm aside, on the
    # AINavigator's tracked solves, 2026-10-05): the same pose at the same height, rigidly displaced - so bring it
    # back onto the seed with a rigid ICP (a yaw about Z and a translation), seeded from the bounds centres
    from mathutils import kdtree as _kd
    _sco = np.empty(len(source.data.vertices) * 3, np.float64)
    source.data.vertices.foreach_get("co", _sco)
    _sco = _sco.reshape(-1, 3)
    _kdt = _kd.KDTree(len(_sco))
    for _i, _v in enumerate(_sco):
        _kdt.insert(_v, _i)
    _kdt.balance()
    _tco = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", _tco)
    _tco = _tco.reshape(-1, 3)
    _rng = np.random.default_rng(1)
    _sub = _tco[_rng.choice(len(_tco), size=min(6000, len(_tco)), replace=False)]
    _yaw, _t = 0.0, np.array((shi + slo) / 2 - (thi + tlo) / 2)
    _rms = None
    for _it in range(30):
        _c, _s = math.cos(_yaw), math.sin(_yaw)
        _R = np.array([[_c, -_s, 0], [_s, _c, 0], [0, 0, 1]])
        _p = _sub @ _R.T + _t
        _q = np.array([_kdt.find(Vector(pt))[0] for pt in _p])
        _d = np.linalg.norm(_q - _p, axis=1)
        _keep = _d < max(0.05, np.percentile(_d, 80))        # the far outliers (a hand off the seed) do not steer
        _rms_new = float(np.sqrt(np.mean(_d[_keep] ** 2)))
        # Kabsch in the horizontal plane about the kept points' centroids, the vertical as a plain mean offset
        _pm, _qm = _p[_keep].mean(0), _q[_keep].mean(0)
        _P, _Q = _p[_keep] - _pm, _q[_keep] - _qm
        _H = _P[:, :2].T @ _Q[:, :2]
        _ang = math.atan2(_H[0, 1] - _H[1, 0], _H[0, 0] + _H[1, 1])
        _c2, _s2 = math.cos(_ang), math.sin(_ang)
        _R2 = np.array([[_c2, -_s2, 0], [_s2, _c2, 0], [0, 0, 1]])
        # p' = R2 (p - pm) + qm with p = R x + t: the yaw grows by ang, the translation becomes R2 (t - pm) + qm
        _yaw += _ang
        _t = _R2 @ (_t - _pm) + _qm
        if _rms is not None and abs(_rms - _rms_new) < 1e-5:
            _rms = _rms_new
            break
        _rms = _rms_new
    _c, _s = math.cos(_yaw), math.sin(_yaw)
    _M = Matrix(((_c, -_s, 0, _t[0]), (_s, _c, 0, _t[1]), (0, 0, 1, _t[2]), (0, 0, 0, 1)))
    me.transform(_M)
    res["rigid_yaw_deg"] = round(math.degrees(_yaw), 2)
    res["rigid_translation_m"] = [round(float(v), 4) for v in _t]
    res["rigid_rms_m"] = round(_rms, 4)
    res["shifted_onto_seed"] = True
    log("the posed mesh was moved onto the seed: yaw %.1f degrees, translation %s m, surface rms %.1f mm" % (
        math.degrees(_yaw), [round(float(v), 3) for v in _t], _rms * 1000))
elif max(abs(v) for v in res["centre_offset_m"]) > 0.03:
    log("WARNING the posed mesh does not sit on the seed: %s - the pose or scale differs, the bake will smear" % res)

# with a separate head source the body source loses its own head (after the alignment, which needs the full height):
# the MetaHuman's neck stands wider than the seed's collar and its rays reached the seed's chin (a pale band under the
# jaw, 2026-10-05); the nearest point for the neck is the collar now
cut_z = float(args.get("body_cut_z") or 0)
if head_source is not None and cut_z > 0:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(source.data)
    above = [v for v in bm.verts if v.co.z > cut_z]
    bmesh.ops.delete(bm, geom=above, context="VERTS")
    # the cut leaves loose vertices along its edge; unsampled (no loop, no colour) they filled the neck grey
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(source.data)
    bm.free()
    source.data.validate()
    log("the body source was cut above %.2f m (its own head goes; the head bakes from the head source)" % cut_z)

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


def seed_vertex_colours(src=None):
    """Every source vertex's base colour read off its texture at its UV (the first material with an image): the
    closest-point fallback for texels no ray reaches (the hands, 2026-10-05)."""
    sm = (src or source).data
    n = len(sm.vertices)
    cols = np.full((n, 3), 0.5, np.float32)
    done = np.zeros(n, bool)
    if not sm.uv_layers:
        return cols
    uv = np.empty(len(sm.loops) * 2, np.float32)
    sm.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(len(sm.loops), np.int32)
    sm.loops.foreach_get("vertex_index", lv)
    lm = np.empty(len(sm.polygons), np.int32)
    sm.polygons.foreach_get("material_index", lm)
    loop_start = np.empty(len(sm.polygons), np.int32)
    sm.polygons.foreach_get("loop_start", loop_start)
    loop_total = np.empty(len(sm.polygons), np.int32)
    sm.polygons.foreach_get("loop_total", loop_total)
    poly_of_loop = np.repeat(np.arange(len(sm.polygons)), loop_total)
    for mi, mat in enumerate(sm.materials):
        img = None
        if mat and mat.use_nodes:
            # the image feeding Base Color, not the first image node: a glTF material's first node was the
            # metallic-roughness map and the hands came out orange (2026-10-05)
            bsdf = next((nd for nd in mat.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
            if bsdf and bsdf.inputs["Base Color"].is_linked:
                src_node = bsdf.inputs["Base Color"].links[0].from_node
                # a packed glTF image says has_data False until something reads it: judge it by its size, and reading
                # its pixels below loads it (every vertex came out unsampled, 2026-10-05)
                if src_node.type == "TEX_IMAGE" and src_node.image and src_node.image.size[0] > 0:
                    img = src_node.image
            if img is None:
                for nd in mat.node_tree.nodes:
                    if nd.type == "TEX_IMAGE" and nd.image and nd.image.size[0] > 0 and nd.image.colorspace_settings.name != "Non-Color":
                        img = nd.image
                        break
        if img is None:
            continue
        w, h = img.size
        px = np.empty(w * h * img.channels, np.float32)
        img.pixels.foreach_get(px)
        if not img.has_data or w == 0:
            log("the seed's colour image %s could not be read" % img.name)
            continue
        px = px.reshape(h, w, img.channels)[..., :3]
        sel = lm[poly_of_loop] == mi
        us = np.clip((uv[sel, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
        vs = np.clip((uv[sel, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
        cols[lv[sel]] = px[vs, us]
        done[lv[sel]] = True
    log("seed vertex colours: %d of %d vertices sampled" % (int(done.sum()), n))
    return cols


parts = []
if is_head.sum():
    parts.append(("Head", part_object(is_head, "MH_Head", 0)))
if is_body.sum():
    parts.append(("Body", part_object(is_body, "MH_Body", 1)))
bpy.data.objects.remove(target, do_unlink=True)

# --- the head seed's face fitted onto the MetaHuman's (mh_face_fit.py): baked as placed, a stylised head's eyes landed
# on the MetaHuman's cheeks and its mouth on the chin (the AINavigator's comms portrait, 2026-10-06)
face_fit = None
head_part = next((o for n, o in parts if n == "Head"), None)
if head_source is not None and head_part is not None and args.get("face_fit", True):
    import mh_face_fit
    lmj = args.get("face_landmarks_json") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metahuman",
                                                          "templates", "face_landmarks.json")
    try:
        face_fit, _fit_src, face_fit_tgt = mh_face_fit.fit_head(head_source, head_part, lmj, log, args.get("head_landmarks"),
                                                                float(args.get("eye_inset", 0.35)))
        report["face_fit"] = face_fit
    except Exception as e:                                   # a face the detection cannot read bakes as placed
        log("WARNING face fit failed (%s): the head bakes as the conform placed it - give head_landmarks by hand" % e)

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


def lin2srgb(a):
    """Linear floats to sRGB-encoded floats (what a byte image's pixels and the saved PNG hold)."""
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def bake_once(obj, node, img, cage, kind, src=None):
    """One Cycles bake of the source (or `src`) onto obj into img, rays reaching `cage` metres. Image.pixels of a
    byte image are its sRGB bytes / 255, for the bake result and for the seed's texture alike (measured 2026-10-05:
    the seed's suit (16,66,134) baked as (11,63,126); a linear-to-sRGB "fix" made it a pale steel blue), so the
    nearest-point colours and the bake share one encoding and nothing is converted here."""
    node.image = img
    bpy.ops.object.select_all(action="DESELECT")
    (src or source).select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # only the source and the target take part: every other mesh (the head source during the body bake, the other
    # part) is hidden from the rays, or the body's neck sampled the head source's skin (a pale collar, 2026-10-05)
    hidden = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o is not obj and o is not (src or source) and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    if kind == "color":
        scn.render.bake.use_pass_direct = scn.render.bake.use_pass_indirect = False
        scn.render.bake.use_pass_color = True
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, cage_extrusion=cage,
                            max_ray_distance=cage * 2.5, margin=scn.render.bake.margin, use_clear=True)
    else:
        scn.render.bake.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True, cage_extrusion=cage,
                            max_ray_distance=cage * 2.5, margin=scn.render.bake.margin, use_clear=True)
    for o in hidden:
        o.hide_render = False
    px = np.empty(RES * RES * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(RES, RES, 4)


def position_map(obj, node, img_name):
    """Every texel's world position on obj (a POSITION bake, calibrated to the part's bounds: the pass came back 16x
    the metre coordinates on these parts, 2026-10-05, while a lone cube bakes true) and the on-mesh mask."""
    pos_img = bpy.data.images.new(img_name + "_pos", RES, RES, alpha=False, float_buffer=True)
    pos_img.colorspace_settings.name = "Non-Color"
    node.image = pos_img
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="POSITION", use_selected_to_active=False, margin=0, use_clear=True)
    pp = np.empty(RES * RES * 4, np.float32)
    pos_img.pixels.foreach_get(pp)
    pos = pp.reshape(RES, RES, 4)[..., :3]
    onmesh = np.abs(pos).sum(2) > 1e-6
    bb = np.array([obj.matrix_world @ Vector(c) for c in obj.bound_box])
    lo, hi = bb.min(0), bb.max(0)
    plo, phi = pos[onmesh].min(0), pos[onmesh].max(0)
    scale = np.where(phi - plo > 1e-6, (hi - lo) / np.maximum(phi - plo, 1e-6), 1.0)
    pos = (pos - plo) * scale + lo
    pos[~onmesh] = 0.0
    if abs(float(np.median(scale)) - 1.0) > 0.05:
        log("%s: the position pass was scaled by %s to the part's bounds" % (img_name, np.round(1 / scale, 2).tolist()))
    if args.get("debug_positions"):
        pos_img.filepath_raw = os.path.join(OUT, img_name[:-3] + "_POS.exr")
        pos_img.file_format = "OPEN_EXR"
        pos_img.save()
    bpy.data.images.remove(pos_img)
    return pos, onmesh


def bake(part_name, obj, kind):
    img_name = "T_%s_%s_%s" % (NAME, part_name, "BC" if kind == "color" else "N")
    src = head_source if (part_name == "Head" and head_source is not None) else source
    img = bpy.data.images.new(img_name, RES, RES, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if kind == "color" else "Non-Color"
    mat = bpy.data.materials.new("Bake_%s_%s" % (part_name, kind))
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    mat.node_tree.nodes.active = node
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    px = bake_once(obj, node, img, CAGE, kind, src)
    pos = onmesh = None
    neck_z = float(args.get("body_cut_z") or 0)
    if part_name == "Head" and head_source is not None and neck_z > 0:
        # the MetaHuman's face mesh carries the neck down to the collarbones; below the body seed's collar top it is
        # the suit, which the body seed knows and the head seed does not (its neck skin ran 6 cm lower: a pale
        # crescent at the collar, 2026-10-05) - so that band is baked from the body source
        pos, onmesh = position_map(obj, node, img_name)
        node.image = img
        body_img = bpy.data.images.new(img_name + "_body", RES, RES, alpha=False, float_buffer=False)
        body_img.colorspace_settings.name = img.colorspace_settings.name
        body_px = bake_once(obj, node, body_img, CAGE, kind, source)
        node.image = img
        low = onmesh & (pos[..., 2] < neck_z) & (body_px[..., :3].max(2) >= DARK)
        px[low] = body_px[low]
        bpy.data.images.remove(body_img)
        log("%s: %d neck texels below %.2f m baked from the body source" % (img_name, int(low.sum()), neck_z))
    # Where no ray reached the seed the texel stays the clear colour. Whole hands came out black when the solved
    # MetaHuman's hands stood 5-10 cm off the seed's (the AINavigator, 2026-10-05): a second pass with a far cage
    # fills exactly those texels, and what is still missing takes the nearest baked colour.
    srcmap = None
    if kind == "color":
        miss = px[..., :3].max(2) < DARK
        near_miss_by_part[part_name] = miss.copy()
        miss_by_part[part_name] = miss.copy()
        srcmap = np.where(miss, 0, 1).astype(np.uint8)        # 1 near hit
    else:
        # the normal map follows the colour map's masks: its near pass misses where the colour's did, its far pass is
        # kept only where the colour's far hit was a real one, and the rest is the flat normal (2026-10-05: 27% of
        # the body's normals were black or inside-out, black discs on the elbows and hands)
        miss = near_miss_by_part.get(part_name)
    far_share = 0.0
    # the far pass (2.5x the cage; 4x printed the seed's shaded far side as dark patches on the AINavigator's chest
    # and shoulder blades, 2026-10-05) is off by default; the nearest seed point fills what both passes miss
    if miss is not None and miss.mean() > 0.002 and args.get("far_pass", False):
        far_img = bpy.data.images.new(img_name + "_far", RES, RES, alpha=False, float_buffer=False)
        far_img.colorspace_settings.name = img.colorspace_settings.name
        far = bake_once(obj, node, far_img, CAGE * 2.5, kind, src)
        node.image = img
        if kind == "color":
            hit_far = miss & (far[..., :3].max(2) >= DARK)
            far_hit_by_part[part_name] = hit_far.copy()
            srcmap[hit_far] = 2                                  # 2 far hit
        else:
            hit_far = far_hit_by_part.get(part_name)
            hit_far = (miss & hit_far) if hit_far is not None else np.zeros_like(miss)
        px[hit_far] = far[hit_far]
        far_share = float(hit_far.mean())
        if kind == "color":
            miss = miss & ~hit_far
            miss_by_part[part_name] = miss.copy()
        else:
            miss = miss & ~hit_far
        bpy.data.images.remove(far_img)
    if kind == "normal" and miss is not None:
        # a normal that points into the surface is an inside-out hit: flat too
        bad = miss | (px[..., 2] < 0.5)
        px[bad] = np.array([0.5, 0.5, 1.0, 1.0], np.float32)
        log("%s: %d texels set to the flat normal (no hit, or an inside-out one)" % (img_name, int(bad.sum())))
    filled = 0
    nearest = 0
    missed_share = float(miss.mean()) if miss is not None else 0.0
    if kind == "color" and miss is not None and miss.any():
        # the texels still black take the seed's colour at the seed vertex nearest to their own 3D position: a bake
        # of this part's POSITION says where each texel lies; the hands stood too far off the seed for any ray
        if pos is None:
            pos, onmesh = position_map(obj, node, img_name)
        node.image = img
        from mathutils import kdtree
        sm = src.data
        kd = kdtree.KDTree(len(sm.vertices))
        for i, v in enumerate(sm.vertices):
            kd.insert(v.co, i)
        kd.balance()
        cols = seed_vertex_colours(src)
        # one texel in nine is looked up (a kd find per texel in Python took 40 minutes on 843k texels, 2026-10-05);
        # the neighbour fill below spreads them over the two-texel gaps
        rows = np.arange(RES)
        lattice = ((rows % 3 == 0)[:, None]) & ((rows % 3 == 0)[None, :])
        idx = np.argwhere(miss & lattice & (np.abs(pos).sum(2) > 1e-6))
        rgb = px[..., :3]
        for r, c in idx:
            _co, i, _d = kd.find(pos[r, c])
            rgb[r, c] = cols[i]
        miss[idx[:, 0], idx[:, 1]] = False
        nearest = int(len(idx))
        px[..., :3] = rgb
        srcmap[idx[:, 0], idx[:, 1]] = 3                         # 3 nearest seed point
    if kind == "color" and miss is not None:
        # the fill stays on the mesh (the POSITION bake says which texels are): spread across the UV gutters it carried
        # the hands' pale colour into the neck island beside them (the AINavigator's pale collar, 2026-10-05); a
        # short unrestricted pass afterwards gives the filled islands their margin
        rgb = px[..., :3]
        inside = onmesh if onmesh is not None else np.ones(miss.shape, bool)
        for restricted, passes in ((True, int(args.get("fill_passes", 64))), (False, 8)):
            for _ in range(passes):
                if not miss.any():
                    break
                acc = np.zeros_like(rgb)
                cnt = np.zeros(rgb.shape[:2], np.float32)
                known = ~miss & inside if restricted else ~miss
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    sh = np.roll(np.roll(rgb, dr, 0), dc, 1)
                    shm = np.roll(np.roll(known, dr, 0), dc, 1)
                    acc += sh * shm[..., None]
                    cnt += shm
                can = miss & (cnt > 0) & (inside if restricted else True)
                rgb[can] = acc[can] / cnt[can][:, None]
                filled += int(can.sum())
                srcmap[can] = 4                                  # 4 neighbour fill
                miss = miss & ~can
        px[..., :3] = rgb
    tinted = 0
    if kind == "color" and args.get("skin_color") and part_name in (args.get("skin_parts") or ["Body"]):
        # pale texels (the seed's washed-out hands and feet) take the planned skin colour, their shading kept:
        # the AINavigator's hands came out near white against the reference's light blue (2026-10-05)
        h = args["skin_color"].lstrip("#")
        skin = np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)
        skin_lin = skin                                  # the map holds sRGB bytes, as the seed texture does
        rgb = px[..., :3]
        mx = rgb.max(2)
        mn = rgb.min(2)
        sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
        pale = (sat < 0.22) & (mx > 0.35)
        if miss is not None:
            pale = pale & ~miss
        shade = np.clip(mx[pale] / 0.85, 0.5, 1.15)
        rgb[pale] = np.clip(skin_lin[None, :] * shade[:, None], 0, 1)
        px[..., :3] = rgb
        tinted = int(pale.sum())
        log("%s: %d pale texels tinted to the skin colour %s" % (img_name, tinted, args["skin_color"]))
    if srcmap is not None and args.get("debug_positions") and pos is not None:
        # where the pale texels of each pass sit in 3D: the pass and the place of a stray colour
        _on = np.abs(pos).sum(2) > 1e-6
        log("DEBUG %s object %s matrix %s dims %s; position pass over %d texels: min %s max %s" % (
            img_name, obj.name, [list(np.round(r, 3)) for r in obj.matrix_world], list(np.round(obj.dimensions, 3)), int(_on.sum()),
            np.round(pos[_on].min(0), 2).tolist(), np.round(pos[_on].max(0), 2).tolist()))
        rgbp = px[..., :3]
        mxp = rgbp.max(2)
        pale_m = (mxp > 0.55) & ((mxp - rgbp.min(2)) / np.maximum(mxp, 1e-4) < 0.35) & (np.abs(pos).sum(2) > 1e-6)
        for code, name in ((1, "near"), (2, "far"), (3, "nearest"), (4, "neighbour")):
            m = pale_m & (srcmap == code)
            if m.sum() > 50:
                P = pos[m]
                log("DEBUG %s pale %s texels: %d, median xyz %s, z range %.2f..%.2f, |x| range %.2f..%.2f" % (
                    img_name, name, int(m.sum()), np.round(np.median(P, 0), 3).tolist(), P[:, 2].min(), P[:, 2].max(), np.abs(P[:, 0]).min(), np.abs(P[:, 0]).max()))
    if srcmap is not None:
        palette = np.array([[0, 0, 0], [0.2, 0.8, 0.2], [0.9, 0.8, 0.1], [0.9, 0.2, 0.2], [0.2, 0.4, 0.9]], np.float32)
        sm_img = bpy.data.images.new(img_name[:-3] + "_SRC", RES, RES, alpha=False, float_buffer=False)
        sm_img.colorspace_settings.name = "Non-Color"
        sm_px = np.ones((RES, RES, 4), np.float32)
        sm_px[..., :3] = palette[srcmap]
        sm_img.pixels.foreach_set(sm_px.reshape(-1))
        sm_img.filepath_raw = os.path.join(OUT, img_name[:-3] + "_SRC.png")
        sm_img.file_format = "PNG"
        sm_img.save()
        report.setdefault("source_maps", {})[part_name] = {"file": os.path.basename(sm_img.filepath_raw),
                                                           "key": "green near hit, yellow far hit, red nearest seed point, blue neighbour fill, black never written",
                                                           "shares": {k: round(float((srcmap == i).mean()), 4) for i, k in enumerate(("none", "near", "far", "nearest", "neighbour"))}}
    img.pixels.foreach_set(px.reshape(-1))
    path = os.path.join(OUT, img_name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    # coverage: the share of texels the bake wrote (the UV islands' area plus margin), read off the colour bake
    if kind == "color":
        covered = float((px[..., :3].max(2) > 0.02).mean())
        coverage_by_part[part_name] = covered
    else:
        covered = coverage_by_part.get(part_name)
    report["maps"][img_name] = {"file": os.path.basename(path), "kind": kind, "part": part_name, "resolution": RES,
                                "coverage": round(covered, 3) if covered is not None else None,
                                "far_pass_share": round(far_share, 4), "nearest_seed_point": nearest, "filled_from_neighbours": filled, "missed_after_far": round(missed_share, 4), "skin_tinted": tinted,
                                "convention": "OpenGL +Y tangent normal (flip green on Unreal import)" if kind == "normal" else "sRGB base colour"}
    log("baked %s: %s of the texels, %.1f%% from the far pass, %d from the nearest seed point, %d filled from neighbours" % (
        img_name, ("%.0f%%" % (covered * 100)) if covered is not None else "coverage as the colour map's", far_share * 100, nearest, filled))
    return img


baked = {}
coverage_by_part = {}
miss_by_part = {}
near_miss_by_part = {}
far_hit_by_part = {}
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
if head_source is not None:
    head_source.hide_render = True
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
if face_fit is not None:
    # the fitted head seed from the front with the MetaHuman's landmarks as red dots: its painted eye corners, lids,
    # brows, nose, mouth corners and chin should sit on them
    shown.hide_render = True
    head_source.hide_render = False
    dots = []
    for k in face_fit["pairs"]:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0018, location=Vector(face_fit_tgt[k]), segments=12, ring_count=8)
        d = bpy.context.active_object
        if not bpy.data.materials.get("FitDot"):
            dm = bpy.data.materials.new("FitDot")
            dm.use_nodes = True
            em = dm.node_tree.nodes.new("ShaderNodeEmission")
            em.inputs[0].default_value = (1, 0.1, 0.1, 1)
            em.inputs[1].default_value = 4
            dm.node_tree.links.new(em.outputs[0], dm.node_tree.nodes["Material Output"].inputs[0])
        d.data.materials.append(bpy.data.materials["FitDot"])
        dots.append(d)
    T_ = np.array([face_fit_tgt[k] for k in face_fit["pairs"]])
    c_ = T_.mean(0)
    half = max(float(np.ptp(T_[:, 0])), float(np.ptp(T_[:, 2]))) * 0.75
    stage = blib.Stage(head_source, extra_hidden=[], look="preview")
    for d in dots:
        d.hide_render = False
    blib.ortho_camera(cam, "left", Vector((c_[0] - half, c_[1] - 0.2, c_[2] - half)), Vector((c_[0] + half, c_[1] + 0.2, c_[2] + half)), margin=1.0)
    scn.camera = cam
    path = os.path.join(OUT, "face_fit_front.png")
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders["face_fit"] = os.path.basename(path)
    stage.close()
report["renders"] = renders
report["unreal"] = ("drop the T_ maps into the built MetaHuman's Body/Baked and Face/Baked folders over T_Body_BC/N and "
                    "T_Head_LOD*_BC/N, or set them on MI_Body_Baked and MI_Face_Skin_Baked_LOD*; import the _N maps with "
                    "Flip Green Channel ticked (Blender bakes OpenGL +Y)")
json.dump(report, open(os.path.join(OUT, "bake_report.json"), "w", encoding="utf-8"), indent=1, default=plain)
log("done: %s" % ", ".join(report["maps"]))

"""Reference reprojection (issue #11): the crisp 2D reference picture is projected back onto the mesh.

Image-to-3D paints its own soft texture instead of using the picture it was given, so panel lines, markings and
chamfers come back blurred. We know the picture's viewpoint (the skill asked for a profile), and the probe pass
rendered the mesh from the matching camera. Fit the picture's silhouette to the mesh's silhouette in that camera,
project the picture through the camera onto the faces that face it (feathered by angle, hidden faces excluded),
bake the result into the atlas, and mirror the picture onto the far side of a symmetric object. A normal-detail
map derived from the picture's own edges is projected the same way, so chamfers shade crisply even where the
silhouette stays soft. No vendor call.

Used from finish.py as reproject.run(lod0, probe, decision, reference_path, probe_to_now, log, ...)."""
import os

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

import blib


def _pixels(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def _load_rgba(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
    return img, _pixels(img)


def _fg_mask(rgba):
    """The object: whatever differs from the border colour (white product shot or grey probe backdrop)."""
    rgb = rgba[:, :, :3]
    border = np.concatenate([rgb[:6].reshape(-1, 3), rgb[-6:].reshape(-1, 3), rgb[:, :6].reshape(-1, 3), rgb[:, -6:].reshape(-1, 3)])
    back = np.median(border, axis=0)
    diff = np.abs(rgb - back).max(axis=2)
    m = diff > 0.08
    if rgba.shape[2] == 4:
        m &= rgba[:, :, 3] > 0.5 if rgba[:, :, 3].min() < 0.99 else True
    return m


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _resample_mask(mask, box_src, box_dst, flip, shape_dst):
    """Map a mask through the affine that sends box_src to box_dst (optionally mirrored), nearest neighbour."""
    x0, y0, x1, y1 = box_dst
    hd, wd = shape_dst
    out = np.zeros(shape_dst, bool)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    fx = (xs - x0) / max(x1 - x0, 1)
    fy = (ys - y0) / max(y1 - y0, 1)
    if flip:
        fx = 1 - fx
    sx0, sy0, sx1, sy1 = box_src
    sx = np.clip((sx0 + fx * (sx1 - sx0)).astype(int), 0, mask.shape[1] - 1)
    sy = np.clip((sy0 + fy * (sy1 - sy0)).astype(int), 0, mask.shape[0] - 1)
    out[ys, xs] = mask[sy, sx]
    return out


def _iou(a, b):
    inter = (a & b).sum()
    union = (a | b).sum()
    return float(inter) / float(max(union, 1))


def _height_to_normal(L, strength=2.0):
    """A tangent-space normal map from the picture's own luminance detail (high-pass), 0-1 encoded."""
    from numpy import pad
    hp = L - _box_blur(L, 6)
    hp = hp / (np.percentile(np.abs(hp), 98) + 1e-4)
    hp = np.clip(hp, -1, 1)
    gx = np.zeros_like(hp)
    gy = np.zeros_like(hp)
    gx[:, 1:-1] = (hp[:, 2:] - hp[:, :-2]) * 0.5
    gy[1:-1, :] = (hp[2:, :] - hp[:-2, :]) * 0.5
    n = np.stack([-gx * strength, gy * strength, np.ones_like(hp)], axis=2)
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-6)
    return (n + 1) * 0.5


def _box_blur(a, r):
    if r < 1:
        return a
    k = 2 * r + 1
    p = np.pad(a, ((r, r), (r, r)), mode="edge")
    c = np.cumsum(p, axis=0)
    a1 = (c[k - 1:] - np.concatenate([np.zeros((1, c.shape[1]), c.dtype), c[:-k]], axis=0)) / k
    c = np.cumsum(a1, axis=1)
    return (c[:, k - 1:] - np.concatenate([np.zeros((c.shape[0], 1), c.dtype), c[:, :-k]], axis=1)) / k


def _fit_view(probe, view, ref_mask, work_dir):
    """How the reference picture maps onto the probe render of `view`: (affine boxes, flip, IoU) or None."""
    rec = next((r for r in probe["views"] if r["view"] == view), None)
    if rec is None:
        return None
    path = os.path.join(work_dir, rec["file"])
    if not os.path.exists(path):
        return None
    _img, px = _load_rgba(path)
    mesh_mask = _fg_mask(px)
    mb = _bbox(mesh_mask)
    rb = _bbox(ref_mask)
    if mb is None or rb is None:
        return None
    best = None
    for flip in (False, True):
        mapped = _resample_mask(ref_mask, rb, mb, flip, mesh_mask.shape)
        iou = _iou(mapped, mesh_mask)
        if best is None or iou > best["iou"]:
            best = {"view": view, "rec": rec, "ref_box": rb, "mesh_box": mb, "flip": flip, "iou": iou, "size": rec["size"]}
    return best


def run(obj, probe, decision, reference_path, probe_to_now, log, views=("posy", "negy"), mirror=True,
        colour_strength=0.85, normal_strength=0.6, min_iou=0.55):
    """Project the reference onto `obj` from the side views. Returns a stats dict or None."""
    if not reference_path or not os.path.exists(reference_path):
        return None
    scn = bpy.context.scene
    ref_img, ref_px = _load_rgba(reference_path)
    ref_mask = _fg_mask(ref_px)
    RH, RW = ref_mask.shape
    fits = [f for f in (_fit_view(probe, v, ref_mask, os.path.dirname(os.path.join(bpy.path.abspath("//"), ""))) for v in views) if f]
    return None if not fits else _apply(obj, fits, ref_img, ref_px, ref_mask, probe_to_now, log, mirror, colour_strength, normal_strength, min_iou)


def run_with_work(obj, probe, decision, reference_path, probe_to_now, work_dir, log, views=("posy", "negy"), mirror=True,
                  colour_strength=0.55, normal_strength=0.5, min_iou=0.75):
    if not reference_path or not os.path.exists(reference_path):
        return None
    ref_img, ref_px = _load_rgba(reference_path)
    ref_mask = _fg_mask(ref_px)
    fits = [f for f in (_fit_view(probe, v, ref_mask, work_dir) for v in views) if f]
    if not fits:
        log("reproject: no side probe render to fit the reference to")
        return None
    return _apply(obj, fits, ref_img, ref_px, ref_mask, probe_to_now, log, mirror, colour_strength, normal_strength, min_iou)


def _apply(obj, fits, ref_img, ref_px, ref_mask, probe_to_now, log, mirror, colour_strength, normal_strength, min_iou):
    scn = bpy.context.scene
    fits.sort(key=lambda f: -f["iou"])
    best = fits[0]
    if best["iou"] < min_iou:
        log("reproject: the reference does not fit any side view (best IoU %.2f from %s); skipped" % (best["iou"], best["view"]))
        return None
    # the picture matches `best`; with mirror, the opposite side gets the mirrored picture through the other camera
    plan = [best]
    if mirror:
        other = next((f for f in fits if f["view"] != best["view"]), None)
        if other is not None:
            other = dict(other, flip=not best["flip"], ref_box=best["ref_box"])
            plan.append(other)
    log("reproject: reference fits the %s view (IoU %.2f%s)%s" % (
        best["view"], best["iou"], ", mirrored" if best["flip"] else "", "; far side gets the mirrored picture" if len(plan) > 1 else ""))

    me = obj.data
    n_faces = len(me.polygons)
    n_loops = len(me.loops)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(obj.matrix_world)
    world = co @ mw[:3, :3].T + mw[:3, 3]
    lv = np.empty(n_loops, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    normals = np.empty(n_faces * 3, np.float32)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    centres = np.empty(n_faces * 3, np.float32)
    me.polygons.foreach_get("center", centres)
    centres = centres.reshape(-1, 3)
    loop_total = np.empty(n_faces, np.int32)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_poly = np.repeat(np.arange(n_faces), loop_total)

    # derived normal detail from the picture
    RH, RW = ref_mask.shape
    L = 0.2126 * ref_px[:, :, 0] + 0.7152 * ref_px[:, :, 1] + 0.0722 * ref_px[:, :, 2]
    nrm = _height_to_normal(L, strength=2.0)
    nrm_img = bpy.data.images.new("ms_ref_normal", RW, RH, alpha=False, float_buffer=False)
    nrm_img.colorspace_settings.name = "Non-Color"
    buf = np.ones((RH, RW, 4), np.float32)
    buf[:, :, :3] = nrm
    nrm_img.pixels.foreach_set(buf.ravel())
    ref_img.colorspace_settings.name = "sRGB"
    # the reference foreground, eroded by ~1.5% of the object width: texels that land on the white background or on
    # the silhouette edge must not be painted (wave 10 M4/Raven: white fringes and blown highlights, 2026-09-17)
    rb = _bbox(ref_mask)
    er = max(2, int((rb[2] - rb[0]) * 0.004)) if rb else 3     # 1.5% erased every barrel and scope tube (coverage 34% -> 10%)
    fgf = ref_mask.astype(np.float32)
    eroded = (_box_blur(fgf, er) > 0.999).astype(np.float32)
    msk_img = bpy.data.images.new("ms_ref_mask", RW, RH, alpha=False, float_buffer=False)
    msk_img.colorspace_settings.name = "Non-Color"
    mbuf = np.ones((RH, RW, 4), np.float32)
    mbuf[:, :, 0] = eroded
    mbuf[:, :, 1] = eroded
    mbuf[:, :, 2] = eroded
    msk_img.pixels.foreach_set(mbuf.ravel())

    # target images: the material's base colour and normal sizes
    mats = [s.material for s in obj.material_slots if s.material and s.material.node_tree]
    size = 2048
    for m in mats:
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and bsdf.inputs["Base Color"].is_linked:
            node = bsdf.inputs["Base Color"].links[0].from_node
            if node.type == "TEX_IMAGE" and node.image:
                size = max(node.image.size)
                break
    acc_col = np.zeros((size, size, 3), np.float32)
    acc_nrm = np.zeros((size, size, 3), np.float32)
    acc_w = np.zeros((size, size), np.float32)
    acc_msk = np.zeros((size, size), np.float32)

    dg = bpy.context.evaluated_depsgraph_get()
    cam_objs = []
    for f in plan:
        cam = blib.camera_from_record(f["rec"]["camera"], "Reproj_" + f["view"])
        cam.matrix_world = Matrix(probe_to_now) @ cam.matrix_world
        cam_objs.append(cam)
        scn.camera = cam
        bpy.context.view_layer.update()
        cam_pos = cam.matrix_world.translation
        view_dir = -(cam.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        # per-face weight: facing (feathered) and visible from the camera
        facing = -(normals @ np.array(view_dir))
        w_face = np.clip((facing - 0.45) / 0.4, 0, 1)          # grazing faces are where the fringes come from
        vis = np.zeros(n_faces, bool)
        for i in np.nonzero(w_face > 0)[0]:
            c = Vector(centres[i].tolist())
            d = (c - cam_pos)
            dist = d.length
            ok, loc, _n, idx, _o, _m = scn.ray_cast(dg, cam_pos, d.normalized(), distance=dist * 1.5)
            if ok and (idx == i or (loc - c).length < dist * 0.004):
                vis[i] = True
        w_face = w_face * vis
        # per-vertex projection: world -> probe camera (u,v) -> probe pixel -> reference pixel -> reference UV
        W, H = f["size"]
        mx0, my0, mx1, my1 = f["mesh_box"]
        rx0, ry0, rx1, ry1 = f["ref_box"]
        uv_vert = np.zeros((len(world), 2), np.float32)
        for vi in range(len(world)):
            u, v, _depth = world_to_camera_view(scn, cam, Vector(world[vi].tolist()))
            px = u * W
            py = (1 - v) * H
            fx = (px - mx0) / max(mx1 - mx0, 1)
            fy = (py - my0) / max(my1 - my0, 1)
            if f["flip"]:
                fx = 1 - fx
            rx = rx0 + fx * (rx1 - rx0)
            ry = ry0 + fy * (ry1 - ry0)
            uv_vert[vi] = (rx / RW, 1 - ry / RH)
        uv = uv_vert[lv]
        # only loops of weighted faces matter; clip the others to a corner so CLIP extension yields transparent
        wl = w_face[loop_poly]
        if "ms_proj" in me.uv_layers:
            me.uv_layers.remove(me.uv_layers["ms_proj"])
        layer = me.uv_layers.new(name="ms_proj")
        layer.data.foreach_set("uv", uv.ravel())
        if "ms_w" in me.color_attributes:
            me.color_attributes.remove(me.color_attributes["ms_w"])
        attr = me.color_attributes.new("ms_w", "FLOAT_COLOR", "CORNER")
        colw = np.zeros((n_loops, 4), np.float32)
        colw[:, 0] = wl
        colw[:, 1] = wl
        colw[:, 2] = wl
        colw[:, 3] = 1
        attr.data.foreach_set("color", colw.ravel())
        # bake three passes through a temporary emission shader: colour*w, normal*w, w
        for which, src_img, cs in (("col", ref_img, "sRGB"), ("nrm", nrm_img, "Non-Color"), ("msk", msk_img, "Non-Color"), ("w", None, "Non-Color")):
            target = bpy.data.images.new("ms_reproj_%s" % which, size, size, alpha=False, float_buffer=True)
            target.colorspace_settings.name = "Non-Color" if which != "col" else "sRGB"
            restore = []
            for m in mats:
                nt = m.node_tree
                outn = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
                prev = outn.inputs["Surface"].links[0].from_socket if outn.inputs["Surface"].is_linked else None
                temps = []
                e = nt.nodes.new("ShaderNodeEmission"); temps.append(e)
                wa = nt.nodes.new("ShaderNodeVertexColor"); wa.layer_name = "ms_w"; temps.append(wa)
                if src_img is not None:
                    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = "ms_proj"; temps.append(uvn)
                    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = src_img; tex.extension = "CLIP"; tex.interpolation = "Linear"; temps.append(tex)
                    nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
                    mul = nt.nodes.new("ShaderNodeMixRGB"); mul.blend_type = "MULTIPLY"; mul.inputs["Fac"].default_value = 1.0; temps.append(mul)
                    nt.links.new(tex.outputs["Color"], mul.inputs["Color1"])
                    nt.links.new(wa.outputs["Color"], mul.inputs["Color2"])
                    nt.links.new(mul.outputs["Color"], e.inputs["Color"])
                else:
                    nt.links.new(wa.outputs["Color"], e.inputs["Color"])
                for l in list(outn.inputs["Surface"].links):
                    nt.links.remove(l)
                nt.links.new(e.outputs["Emission"], outn.inputs["Surface"])
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = target; temps.append(t)
                nt.nodes.active = t
                restore.append((nt, outn, prev, temps))
            scn.render.engine = "CYCLES"
            scn.cycles.device = "CPU"
            scn.cycles.samples = 1
            blib.select_only([obj])
            me.uv_layers.active = me.uv_layers[0] if me.uv_layers[0].name != "ms_proj" else me.uv_layers[1]
            bpy.ops.object.bake(type="EMIT", margin=2, use_clear=True, target="IMAGE_TEXTURES")
            px = _pixels(target)
            if which == "col":
                acc_col += px[:, :, :3]
            elif which == "nrm":
                acc_nrm += px[:, :, :3]
            elif which == "msk":
                acc_msk += px[:, :, 0]
            else:
                acc_w += px[:, :, 0]
            for nt, outn, prev, temps in restore:
                for l in list(outn.inputs["Surface"].links):
                    nt.links.remove(l)
                if prev is not None:
                    nt.links.new(prev, outn.inputs["Surface"])
                for n in temps:
                    nt.nodes.remove(n)
            bpy.data.images.remove(target)
        me.uv_layers.remove(me.uv_layers["ms_proj"])
        me.color_attributes.remove(me.color_attributes["ms_w"])
    for cam in cam_objs:
        bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.images.remove(nrm_img)
    bpy.data.images.remove(msk_img)

    # combine: only texels whose rays landed INSIDE the eroded reference foreground carry weight
    proj_col = np.where(acc_w[..., None] > 1e-3, acc_col / np.maximum(acc_w, 1e-3)[..., None], 0)
    proj_nrm = np.where(acc_w[..., None] > 1e-3, acc_nrm / np.maximum(acc_w, 1e-3)[..., None], 0.5)
    w = np.clip(acc_msk, 0, 1)
    covered = w > 0.05
    # alignment gate: the vendor painted the same picture, so a correctly aligned projection agrees with it on
    # average; a duplicated, shifted slide texture (Glock, wave 11) disagrees almost everywhere
    for m in mats:
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and bsdf.inputs["Base Color"].is_linked:
            node = bsdf.inputs["Base Color"].links[0].from_node
            if node.type == "TEX_IMAGE" and node.image and tuple(node.image.size) == (size, size):
                bc0 = _pixels(node.image)[:, :, :3]
                sel = w > 0.5
                if sel.sum() > 500:
                    lp = 0.2126 * proj_col[:, :, 0] + 0.7152 * proj_col[:, :, 1] + 0.0722 * proj_col[:, :, 2]
                    lv = 0.2126 * bc0[:, :, 0] + 0.7152 * bc0[:, :, 1] + 0.0722 * bc0[:, :, 2]
                    # compare structure, not brightness: both luminances normalised, then the mean absolute gap
                    a = (lp[sel] - lp[sel].mean()) / (lp[sel].std() + 1e-4)
                    b = (lv[sel] - lv[sel].mean()) / (lv[sel].std() + 1e-4)
                    corr = float(np.mean(a * b))
                    log("reproject: structure agreement with the vendor texture %.2f" % corr)
                    if corr < 0.12:      # 0.25 rejected a visibly correct rifle (0.21); a shifted slide sits near zero
                        log("reproject: too little agreement - the projection is misaligned; skipped")
                        return None
                break
    stats = {"views": [f["view"] for f in plan], "iou": round(best["iou"], 3), "atlas_cover": round(float(covered.mean()), 3)}
    for m in mats:
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            continue
        # colour
        if bsdf.inputs["Base Color"].is_linked:
            node = bsdf.inputs["Base Color"].links[0].from_node
            if node.type == "TEX_IMAGE" and node.image:
                bc = _pixels(node.image)
                h, wd = bc.shape[:2]
                if (h, wd) == (size, size):
                    # first pull the whole vendor albedo to the picture's colour balance where both are known, so the
                    # projected and the unprojected texels do not mottle (yellow vendor stock vs olive picture)
                    sel = w > 0.5
                    if sel.sum() > 500:
                        gm = np.clip(proj_col[sel].mean(axis=0) / np.maximum(bc[:, :, :3][sel].mean(axis=0), 1e-3), 0.85, 1.2)   # a gentle nudge: a 1.5x blue gain turned the steel purple
                        bc[:, :, :3] = np.clip(bc[:, :, :3] * gm[None, None, :], 0, 1)
                        stats["vendor_gain"] = [round(float(g), 3) for g in gm]
                    a = np.clip(w * colour_strength, 0, 1)
                    # a projected texel much brighter than the vendor's is a specular highlight or a background remnant
                    lp = 0.2126 * proj_col[:, :, 0] + 0.7152 * proj_col[:, :, 1] + 0.0722 * proj_col[:, :, 2]
                    lv = 0.2126 * bc[:, :, 0] + 0.7152 * bc[:, :, 1] + 0.0722 * bc[:, :, 2]
                    a = np.where(lp - lv > 0.25, 0.0, a)
                    stats["highlight_rejected"] = round(float(((lp - lv > 0.25) & (w > 0.05)).mean()), 3)
                    a = a[..., None]
                    bc[:, :, :3] = a * proj_col + (1 - a) * bc[:, :, :3]
                    node.image.pixels.foreach_set(bc.ravel())
                    node.image.pack()
                    node.image.update()
        # normal detail: whiteout blend on covered texels
        if bsdf.inputs["Normal"].is_linked:
            nm = bsdf.inputs["Normal"].links[0].from_node
            tex = nm.inputs["Color"].links[0].from_node if nm.type == "NORMAL_MAP" and nm.inputs["Color"].is_linked else None
            if tex is not None and tex.type == "TEX_IMAGE" and tex.image:
                npx = _pixels(tex.image)
                h, wd = npx.shape[:2]
                if (h, wd) == (size, size):
                    a = np.clip(w * normal_strength, 0, 1)[..., None]
                    d = proj_nrm * 2 - 1
                    d[:, :, :2] *= a[:, :, 0:1]
                    v = npx[:, :, :3] * 2 - 1
                    n = np.stack([v[..., 0] + d[..., 0], v[..., 1] + d[..., 1], v[..., 2] * np.maximum(d[..., 2], 0.2)], axis=2)
                    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-6)
                    npx[:, :, :3] = (n + 1) * 0.5
                    tex.image.pixels.foreach_set(npx.ravel())
                    tex.image.pack()
                    tex.image.update()
    return stats

"""The head seed's face fitted onto the MetaHuman's face before the head bake (inside Blender, imported by mh_bake.py).

Why (the AINavigator, 2026-10-06): the conform scales the head seed by its skull, but a stylised head carries its face
lower and wider than a MetaHuman's (big cranium, big wide-set eyes, a small chin). Baked as placed, the seed's painted
eyes landed on the MetaHuman's cheeks beside the nose, a hand's width under the real eyeballs, and its mouth on the chin:
two pairs of eyes in the comms portrait. The fit finds the same landmarks on both faces - eye corners and lids, brows,
nose, mouth corners and lips, chin, ears - and moves the seed's head mesh with a smooth thin-plate warp so its
landmarks sit on the MetaHuman's, the cranium, the back of the head and the neck held where they are. The bake then
reads the seed's eyes into the MetaHuman's eyelids and its mouth into the lips.

MetaHuman side: every MetaHuman head shares one UV layout, so the landmarks are UV points
(metahuman/templates/face_landmarks.json, read off a built face mesh's joints and eyeballs) found on the posed head.
Seed side: read off the seed's own texture (iris, sclera and lash colours, the darker mouth line, brows) and its shape
(the nose tip, the chin and the ears are the extremes of the profile and the sides). Any landmark can be given by hand
("head_landmarks" in the bake args, metres in the conform's frame) when the detection reads a face wrongly: the report
lists what it found and the front render marks both sets."""
import json
import math

import bpy
import numpy as np


def _mesh_arrays(me):
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def target_landmarks(head_obj, landmarks_json):
    """The MetaHuman's landmarks on the posed head part: the vertex position at each landmark's UV (the part keeps
    MetaHuman's head UVs on 0-1)."""
    spec = json.load(open(landmarks_json, encoding="utf-8"))["landmarks"]
    me = head_obj.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    (me.uv_layers.active or me.uv_layers[0]).data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    co = _mesh_arrays(me)
    out, miss = {}, {}
    for name, s in spec.items():
        d = np.linalg.norm(uv - np.array(s["uv"], np.float32), axis=1)
        i = int(np.argmin(d))
        out[name] = co[lv[i]].copy()
        miss[name] = float(d[i])
    return out, miss


def _face_colours(me):
    """Every face's centre, normal and base colour (the Base Color image read at the face's UV centre)."""
    n = len(me.polygons)
    cen = np.empty(n * 3)
    me.polygons.foreach_get("center", cen)
    cen = cen.reshape(-1, 3)
    nrm = np.empty(n * 3)
    me.polygons.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    col = np.full((n, 3), 0.5, np.float32)
    if not me.uv_layers:
        return cen, nrm, col, False
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    ls = np.empty(n, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(n, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    mi = np.empty(n, np.int32)
    me.polygons.foreach_get("material_index", mi)
    fuv = (uv[ls] + uv[ls + np.minimum(1, lt - 1)] + uv[ls + np.minimum(2, lt - 1)]) / 3.0
    found = False
    for k, mat in enumerate(me.materials):
        if not (mat and mat.use_nodes):
            continue
        bsdf = next((nd for nd in mat.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
        if not (bsdf and bsdf.inputs["Base Color"].is_linked):
            continue
        node = bsdf.inputs["Base Color"].links[0].from_node
        if node.type != "TEX_IMAGE" or not node.image or node.image.size[0] == 0:
            continue
        img = node.image
        w, h = img.size
        px = np.empty(w * h * img.channels, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, img.channels)[..., :3]
        sel = mi == k
        us = np.clip((fuv[sel, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
        vs = np.clip((fuv[sel, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
        col[sel] = px[vs, us]
        found = True
    return cen, nrm, col, found


def _robust_centre(P, radius, iters=4):
    c = np.median(P, 0)
    for _ in range(iters):
        near = P[np.linalg.norm(P - c, axis=1) < radius]
        if len(near) < 5:
            break
        c = np.median(near, 0)
    return c


def source_landmarks(src_obj, log):
    """The seed head's landmarks in its own frame (the conform's: metres, Z up, facing -Y)."""
    me = src_obj.data
    co = _mesh_arrays(me)
    cen, nrm, col, textured = _face_colours(me)
    if not textured:
        raise RuntimeError("the head seed has no Base Color image: its eyes and mouth cannot be read")
    val = col.max(1)
    sat = (col.max(1) - col.min(1)) / np.maximum(col.max(1), 1e-4)
    top = co[:, 2].max()
    # the chin's underside: going down the midline, where the face's front gives way to the neck (the front jumps back)
    mid = np.abs(co[:, 0]) < 0.006
    zs = np.arange(top - 0.02, co[:, 2].min(), -0.004)
    front = []
    for z in zs:
        m = mid & (np.abs(co[:, 2] - z) < 0.002)
        front.append(co[m, 1].min() if m.any() else np.nan)
    front = np.array(front)
    face_y = np.nanmin(front)
    chin_z = None
    for z, y in zip(zs, front):
        if not np.isnan(y) and z < top - 0.12 and y > face_y + 0.04:
            chin_z = float(z)
            break
    if chin_z is None:
        raise RuntimeError("no chin found on the head seed's midline profile")
    face_h = top - chin_z
    # the face's front only: faces whose normal looks forward also line the inside of a collar or the back of the
    # neck, and the first mouth search found its "lips" there (2026-10-06)
    facing = (nrm[:, 1] < -0.3) & (cen[:, 2] > chin_z) & (cen[:, 2] < chin_z + 0.75 * face_h) & (cen[:, 1] < face_y + 0.06)
    skin = np.median(col[facing], 0)
    skin_v = float(skin.max())
    skin_s = float((skin.max() - skin.min()) / max(skin.max(), 1e-4))
    lm = {}
    # eyes: the saturated iris, then the eye's whole painted shape (iris, sclera, lashes and liner) for its corners
    iris = facing & (sat > 0.5) & (col[:, 2] > 0.45) & (col[:, 2] >= col[:, 1]) & (col[:, 0] < 0.3)
    for side, sg in (("l", 1), ("r", -1)):
        m = iris & (sg * cen[:, 0] > 0.008) & (sg * cen[:, 0] < 0.6 * face_h)
        if m.sum() < 20:
            raise RuntimeError("no %s iris found on the head seed's texture" % side)
        c = _robust_centre(cen[m], 0.012)
        r = np.linalg.norm(cen[m] - c, axis=1)
        c = cen[m][r < 0.012].mean(0)
        shape = facing & (np.abs(cen[:, 0] - c[0]) < 0.04) & (np.abs(cen[:, 2] - c[2]) < 0.02) & (
            ((sat > 0.5) & (col[:, 2] > 0.45) & (col[:, 0] < 0.3)) | ((val > 0.82) & (sat < 0.15)) | (val < 0.45 * skin_v))
        P = cen[shape]
        row = P[np.abs(P[:, 2] - c[2]) < 0.006]
        inner = row[np.argmin(sg * row[:, 0])] if len(row) else c
        outer = row[np.argmax(sg * row[:, 0])] if len(row) else c
        # the corners: the 3rd / 97th percentile along the row, so a stray liner fleck does not pull them
        xs = np.sort(sg * row[:, 0])
        if len(xs) > 30:
            xi, xo = xs[int(0.03 * len(xs))], xs[int(0.97 * len(xs))]
            inner = row[np.argmin(np.abs(sg * row[:, 0] - xi))]
            outer = row[np.argmin(np.abs(sg * row[:, 0] - xo))]
        col_ = P[np.abs(P[:, 0] - c[0]) < 0.004]
        if len(col_) > 10:
            zsrt = np.sort(col_[:, 2])
            up = col_[np.argmin(np.abs(col_[:, 2] - zsrt[int(0.97 * len(zsrt))]))]
            low = col_[np.argmin(np.abs(col_[:, 2] - zsrt[int(0.03 * len(zsrt))]))]
        else:
            up, low = c + np.array([0, 0, 0.008]), c - np.array([0, 0, 0.008])
        lm["eye_in_" + side], lm["eye_out_" + side] = inner, outer
        lm["lid_up_" + side], lm["lid_low_" + side] = up, low
        lm["_iris_" + side] = c
        # the brow: the stroke above the eye, darker and more saturated than the skin (the AINavigator's: value 0.70
        # against the skin's 0.82, saturation 0.40 against 0.24; the cyan circuit traces are brighter than the skin)
        eye_h = max(up[2] - low[2], 0.008)
        brow = facing & (np.abs(cen[:, 0] - c[0]) < 0.6 * abs(outer[0] - inner[0]) + 0.004) & (
            cen[:, 2] > up[2] + 0.003) & (cen[:, 2] < up[2] + 0.02 + 1.5 * eye_h) & (val < skin_v - 0.05) & (
            sat > skin_s + 0.08)
        # the MetaHuman's brow landmark stands above the eye's centre: so does this one, on the stroke
        above = brow & (np.abs(cen[:, 0] - c[0]) < 0.005)
        if above.sum() > 5:
            lm["brow_" + side] = _robust_centre(cen[above], 0.01)
        elif brow.sum() > 20:
            lm["brow_" + side] = _robust_centre(cen[brow], 0.015)
    # a brow found on one side only stands for both, mirrored about the eyes' midline
    mx = (lm["_iris_l"][0] + lm["_iris_r"][0]) / 2
    for a, b in (("brow_l", "brow_r"), ("brow_r", "brow_l")):
        if a in lm and b not in lm:
            lm[b] = lm[a] * np.array([-1, 1, 1]) + np.array([2 * mx, 0, 0])
            lm["_mirrored_" + b] = lm[b]
    eye_z = float(np.mean([lm["_iris_l"][2], lm["_iris_r"][2]]))
    # the nose tip: the front-most midline point between the chin and the eyes; the bridge: the deepest point above it
    m = mid & (co[:, 2] > chin_z) & (co[:, 2] < eye_z)
    lm["nose_tip"] = co[m][np.argmin(co[m, 1])]
    m = mid & (co[:, 2] > eye_z - 0.01) & (co[:, 2] < eye_z + 0.03)
    if m.any():
        # per 2 mm band the front-most point, then the band that stands furthest back
        bands = {}
        for p in co[m]:
            k = int(p[2] / 0.002)
            if k not in bands or p[1] < bands[k][1]:
                bands[k] = p
        lm["nose_bridge"] = max(bands.values(), key=lambda p: p[1])
    # the mouth: a THIN dark line between the nose and the chin - each 1 mm band's value near the midline against the
    # bands 4 mm above and below, so the broad shading under the chin and the nostrils (kept out by the nose margin) do
    # not win (the AINavigator's line: value 0.60 at z 1.574 against 0.79 around it)
    nose_z = float(lm["nose_tip"][2])
    band_z = np.arange(chin_z + 0.006, nose_z - 0.012, 0.001)
    band_v = []
    for z in band_z:
        m = facing & (np.abs(cen[:, 0] - mx) < 0.012) & (np.abs(cen[:, 2] - z) < 0.0006)
        band_v.append(val[m].mean() if m.sum() >= 3 else np.nan)
    band_v = np.array(band_v)
    best, zc = 0.0, None
    for i, z in enumerate(band_z):
        if np.isnan(band_v[i]):
            continue
        around = band_v[max(0, i - 6):max(0, i - 3)].tolist() + band_v[i + 4:i + 7].tolist()
        around = [v for v in around if not np.isnan(v)]
        if around and np.median(around) - band_v[i] > best:
            best, zc = float(np.median(around) - band_v[i]), float(z)
    if zc is not None and best > 0.05:
        # the corners: follow the line outwards column by column while it stays darker than its surroundings
        corner = {}
        for side, sg in (("l", 1), ("r", -1)):
            z, last = zc, None
            for dx in np.arange(0.0, 0.06, 0.001):
                x = mx + sg * dx
                m = facing & (np.abs(cen[:, 0] - x) < 0.0007) & (np.abs(cen[:, 2] - z) < 0.006)
                if m.sum() < 5:
                    break
                vals = val[m]
                j = int(np.argmin(vals))
                if np.median(vals) - vals[j] < 0.05:
                    break
                last = cen[m][j]
                z = 0.6 * z + 0.4 * float(last[2])
            if last is not None:
                corner[side] = last
        if len(corner) == 2:
            lm["lip_l"], lm["lip_r"] = corner["l"], corner["r"]
        cm = mid & (np.abs(co[:, 2] - zc) < 0.003)
        lm["_mouth"] = co[cm][np.argmin(co[cm, 1])] if cm.any() else np.array([mx, face_y, zc])
    else:
        log("face fit: no mouth line found on the head seed (the lips are not fitted)")
    # the chin: the front-most midline point in the lower part between the chin's underside and the mouth (the lower
    # lip stands further forward just under the line: taken as the chin it dragged the mouth into a V, 2026-10-06)
    mz = float(lm["_mouth"][2]) if "_mouth" in lm else (chin_z + nose_z) / 2
    m = mid & (co[:, 2] > chin_z + 0.002) & (co[:, 2] < mz - 0.55 * (mz - chin_z))
    if m.any():
        lm["chin"] = co[m][np.argmin(co[m, 1])]
    # the ears: the outermost points level with the nose and the eyes, behind the eyes
    for side, sg in (("l", 1), ("r", -1)):
        m = (co[:, 2] > nose_z) & (co[:, 2] < eye_z + 0.02) & (co[:, 1] > lm["_iris_" + side][1] + 0.03) & (sg * co[:, 0] > 0)
        if m.any():
            lm["ear_" + side] = co[m][np.argmax(sg * co[m, 0])]
    lm["_chin_underside_z"] = np.array([0, 0, chin_z])
    lm["_skin"] = skin
    return lm


def tps(src, dst, anchors):
    """A 3D thin-plate warp (kernel r, an affine part) taking src onto dst with the anchors held in place."""
    S = np.vstack([src, anchors])
    D = np.vstack([dst, anchors])
    n = len(S)
    K = np.linalg.norm(S[:, None, :] - S[None, :, :], axis=2)
    P = np.hstack([np.ones((n, 1)), S])
    A = np.zeros((n + 4, n + 4))
    A[:n, :n] = K + np.eye(n) * 1e-6
    A[:n, n:] = P
    A[n:, :n] = P.T
    b = np.zeros((n + 4, 3))
    b[:n] = D
    sol = np.linalg.solve(A, b)
    w, a = sol[:n], sol[n:]

    def apply(X):
        out = np.empty_like(X)
        for i in range(0, len(X), 50000):
            x = X[i:i + 50000]
            k = np.linalg.norm(x[:, None, :] - S[None, :, :], axis=2)
            out[i:i + 50000] = k @ w + np.hstack([np.ones((len(x), 1)), x]) @ a
        return out
    return apply


PAIRS = ("eye_in_l", "eye_out_l", "lid_up_l", "lid_low_l", "eye_in_r", "eye_out_r", "lid_up_r", "lid_low_r",
         "brow_l", "brow_r", "nose_tip", "nose_bridge", "lip_l", "lip_r", "chin", "ear_l", "ear_r")


def fit_head(src_obj, head_obj, landmarks_json, log, overrides=None, eye_inset=0.35):
    """Warp src_obj's mesh (the head seed, in place) so its face landmarks sit on head_obj's (the posed MetaHuman
    head part). eye_inset: the share of the way from the lower lid (and 0.4 of it from the corners) toward the eye's
    centre that the seed's painted eye edge is placed (0 = on the lid margins). Returns the report: both landmark
    sets, the moves, the residuals."""
    tgt, uv_miss = target_landmarks(head_obj, landmarks_json)
    src = source_landmarks(src_obj, log)
    for k, v in (overrides or {}).items():
        src[k] = np.array(v, float)
    # the seed's painted eye goes just INSIDE the MetaHuman's lower lid and corners: mapped onto the lid margins, a
    # stylised eye's oversized iris and sclera showed as a bright crescent on the lower lid's rim and white flecks in
    # the corners (the AINavigator, 2026-10-06). The upper lid keeps its margin: the seed's liner belongs there
    inset = float(eye_inset)
    for side in ("l", "r"):
        keys = ["eye_in_" + side, "eye_out_" + side, "lid_up_" + side, "lid_low_" + side]
        if all(k in tgt for k in keys):
            c = np.mean([tgt[k] for k in keys], 0)
            tgt["lid_low_" + side] = tgt["lid_low_" + side] + inset * (c - tgt["lid_low_" + side])
            for k in keys[:2]:
                tgt[k] = tgt[k] + 0.4 * inset * (c - tgt[k])
    names = [k for k in PAIRS if k in src and k in tgt]
    # the mouth's centre goes between the MetaHuman's lips
    if "_mouth" in src and "lip_up" in tgt and "lip_low" in tgt:
        src["mouth"] = src["_mouth"]
        tgt["mouth"] = (tgt["lip_up"] + tgt["lip_low"]) / 2
        names.append("mouth")
    S = np.array([src[k] for k in names])
    T = np.array([tgt[k] for k in names])
    co = _mesh_arrays(src_obj.data)
    # away from the face the seed's surface goes onto the MetaHuman's nearest surface: the cranium above the brows, the
    # back of the head behind the ears, the neck below the chin. A stylised head is bigger than any MetaHuman's (the
    # AINavigator's ears stood 11 cm out against the MetaHuman's 7.5): held in place instead, the warp had to squeeze
    # the sides of the face against a cranium that stayed wide
    from mathutils.bvhtree import BVHTree
    hm = head_obj.data
    bvh = BVHTree.FromPolygons([v.co.copy() for v in hm.vertices], [tuple(p.vertices) for p in hm.polygons])
    brow_z = max(src.get("brow_l", src["lid_up_l"])[2], src.get("brow_r", src["lid_up_r"])[2])
    ear_y = min(src.get("ear_l", np.array([0, 0.03, 0]))[1], src.get("ear_r", np.array([0, 0.03, 0]))[1])
    chin_under = float(src["_chin_underside_z"][2])
    rng = np.random.default_rng(7)
    groups = [(co[:, 2] > brow_z + 0.05), (co[:, 1] > ear_y + 0.02) & (co[:, 2] > chin_under), (co[:, 2] < chin_under - 0.025)]
    a_src, a_dst = [], []
    for g in groups:
        idx = np.nonzero(g)[0]
        if not len(idx):
            continue
        for p in co[rng.choice(idx, size=min(30, len(idx)), replace=False)]:
            hit = bvh.find_nearest(p)
            if hit[0] is not None:
                a_src.append(p)
                a_dst.append(np.array(hit[0][:]))
    anchors = np.array(a_src) if a_src else np.zeros((0, 3))
    S = np.vstack([S, anchors])
    T = np.vstack([T, np.array(a_dst) if a_dst else np.zeros((0, 3))])
    warp = tps(S, T, np.zeros((0, 3)))
    new = warp(co)
    src_obj.data.vertices.foreach_set("co", new.reshape(-1))
    src_obj.data.update()
    moved = np.linalg.norm(new - co, axis=1)
    resid = np.linalg.norm(warp(S) - T, axis=1)
    rep = {"pairs": {k: {"seed": np.round(src[k], 4).tolist(), "metahuman": np.round(tgt[k], 4).tolist(),
                         "move_mm": round(float(np.linalg.norm(T[i] - S[i]) * 1000), 1)} for i, k in enumerate(names)},
           "anchors": int(len(anchors)), "eye_inset": inset, "residual_mm_max": round(float(resid.max() * 1000), 2),
           "max_vertex_move_mm": round(float(moved.max() * 1000), 1), "uv_lookup_max": round(max(uv_miss.values()), 6),
           "seed_skin_rgb": [int(round(float(v) * 255)) for v in src["_skin"]],
           "missing": [k for k in PAIRS if k not in names],
           "mirrored": [k[len("_mirrored_"):] for k in src if k.startswith("_mirrored_")]}
    log("face fit: %d landmark pairs, %d anchors; the eyes moved %.0f / %.0f mm, the mouth %.0f mm, the largest vertex move %.0f mm" % (
        len(names), len(anchors), rep["pairs"].get("eye_in_l", {}).get("move_mm", 0), rep["pairs"].get("eye_in_r", {}).get("move_mm", 0),
        rep["pairs"].get("mouth", {}).get("move_mm", 0), rep["max_vertex_move_mm"]))
    if rep["missing"]:
        log("face fit: not found on the seed: %s" % ", ".join(rep["missing"]))
    return rep, src, tgt

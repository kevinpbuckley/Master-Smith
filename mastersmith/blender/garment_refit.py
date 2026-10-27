"""A shipped garment refitted without a new seed or a re-fit, in one Blender process (2026-10-07, MissionCommander's
r4/r5 polish, generalised off its five one-off scripts: p4_reseat.py, p4_shrink.py, p5_collar.py, p5_lift.py,
p5_weights.py):
    blender -b --factory-startup -Y --python-exit-code 1 --python garment_refit.py -- <args.json>
args: {"garment": the garment .blend to start from (garment_fit.py's fitted.blend, or a previous run's out),
       "object": the garment's mesh object name (default: the only/largest MESH in the file), "out_dir",
       "stages": a subset/order of ["reseat", "shrink", "collar", "lift", "weights"] (default: all five, in that
                 fixed order - a later stage reads the body/face/proxy the earlier one needs),
       "reseat": {"old_body_fbx", "new_body_fbx", "proxy" (body_proxy.blend; default: beside the garment), "smooth" (8)},
       "shrink": {"proxy", "k" (0.7), "floor_m" (0.010), "min_gap_m" (0.006), "smooth" (25), "band_m" (0.06),
                  "collar_weight_min" (0.01)},
       "collar": {"face_fbx", "clear_m" (0.008), "fade_m" (0.05), "neck_r_m" (0.12), "cap_m" (0.02)},
       "lift": {"proxy", "clear_m" (0.006), "fade_m" (0.03), "cap_m" (0.015)},
       "weights": {"proxy", "near_m" (0.012), "far_m" (0.030), "min_gap_m" (0.005), "mixed_share" (0.12)}}
Writes <out_dir>/fitted.blend (every requested stage applied, in order) and <out_dir>/refit_report.json
({"stages": {"reseat": {...}, "shrink": {...}, ...}} - the same numbers each one-off script printed, one key per
stage actually run). A stage that needs a body proxy and was not given one takes the previous stage's (a `reseat`
run's updated proxy, else the garment folder's own body_proxy.blend beside `garment`).

Why one script, not five: each stage needs the garment the one before left (reseat's moved garment is shrink's
input), so the chain only has to open the source once. The shared maths (the gap->pull mapping that keeps layer
order, the collar/band smoothstep hold, the mixed-label-band test, and old-mesh-to-rebuilt-mesh UV matching) is pure
numpy in `garment_refit_core.py`, which `tests/test_garment_refit_core.py` loads without Blender."""
import heapq
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import garment_refit_core as core  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
STAGES = args.get("stages") or ["reseat", "shrink", "collar", "lift", "weights"]
ORDER = ["reseat", "shrink", "collar", "lift", "weights"]
STAGES = [s for s in ORDER if s in STAGES]          # always run in this fixed order
GARMENT = os.path.abspath(args["garment"])
report = {"garment": GARMENT, "stages_requested": STAGES, "stages": {}}


def log(msg):
    print("[garment_refit] " + msg, flush=True)


def abspath(p):
    return os.path.abspath(p) if p else None


# --------------------------------------------------------------------------------------------------------- loading

bpy.ops.wm.open_mainfile(filepath=GARMENT)
obj_name = args.get("object")
if obj_name:
    g = bpy.data.objects[obj_name]
else:
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        sys.exit("no mesh object in %s" % GARMENT)
    g = max(meshes, key=lambda o: len(o.data.polygons))
log("garment object: %s (%d polygons)" % (g.name, len(g.data.polygons)))
PROXY_DEFAULT = os.path.join(os.path.dirname(GARMENT), "body_proxy.blend")


def import_fbx_mesh(path):
    """The biggest mesh of an Unreal skeletal FBX, baked to metres with an identity transform, every other imported
    object discarded. Returns (object, Nx3 world-space vertex array)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=False)
    new = [o for o in bpy.data.objects if o not in before]
    body = max((o for o in new if o.type == "MESH"), key=lambda o: len(o.data.polygons))
    bpy.context.view_layer.update()
    body.data.transform(body.matrix_world)
    body.parent = None
    body.matrix_world = Matrix.Identity(4)
    for m in list(body.modifiers):
        body.modifiers.remove(m)
    co = np.array([v.co[:] for v in body.data.vertices])
    for o in new:
        if o is not body:
            bpy.data.objects.remove(o, do_unlink=True)
    return body, co


def load_proxy(path):
    with bpy.data.libraries.load(os.path.abspath(path)) as (src, dst):
        dst.objects = ["MH_BodyProxy"]
    px = dst.objects[0]
    bpy.context.scene.collection.objects.link(px)
    return px


def vert_uv(o):
    me_ = o.data
    uv = np.zeros((len(me_.vertices), 2))
    for lp in me_.loops:
        uv[lp.vertex_index] = me_.uv_layers[0].data[lp.index].uv
    return uv


def mesh_edges(me):
    return np.array([e.vertices[:] for e in me.edges]) if len(me.edges) else np.zeros((0, 2), int)


def group_weight(me, groups, pred):
    """Per-vertex summed weight of every vertex group whose name matches `pred`."""
    n = len(me.vertices)
    names = {vg.index: vg.name for vg in groups}
    w = np.zeros(n)
    for v in me.vertices:
        for ge in v.groups:
            if pred(names[ge.group]):
                w[v.index] += ge.weight
    return w


def material_slot(me):
    slot = np.zeros(len(me.vertices), int)
    for p in me.polygons:
        for vi in p.vertices:
            slot[vi] = p.material_index
    return slot


def world_positions(obj):
    mw = obj.matrix_world
    return np.array([mw @ v.co for v in obj.data.vertices]), mw


def set_world_positions(obj, P):
    inv = obj.matrix_world.inverted()
    for v, p in zip(obj.data.vertices, P):
        v.co = inv @ Vector(p.tolist())
    obj.data.update()


# proxy carried from one stage to the next (reseat replaces it with the new body)
current_proxy_path = PROXY_DEFAULT

# ============================================================================================================ reseat
if "reseat" in STAGES:
    a = args.get("reseat") or {}
    smooth = int(a.get("smooth", 8))
    old_path, new_path = a["old_body_fbx"], a["new_body_fbx"]
    proxy_path = abspath(a.get("proxy")) or current_proxy_path
    old_b, old_co = import_fbx_mesh(old_path)
    new_b, new_co = import_fbx_mesh(new_path)
    rep = {"old": old_path, "new": new_path, "body_verts": len(old_co)}
    if len(old_co) != len(new_co):
        idx, worst_uv = core.match_by_uv(vert_uv(old_b), vert_uv(new_b), old_co, new_co)
        new_co = new_co[idx]
        rep["uv_matched"] = {"worst_uv_distance": worst_uv, "old_verts": len(old_co), "new_verts": len(bpy.data.objects[new_b.name].data.vertices)}
        log("reseat matched by UV: worst uv distance %.2e" % worst_uv)
    D = new_co - old_co
    rep["body_move_mm"] = {q: round(float(np.percentile(np.linalg.norm(D, axis=1), q)) * 1000, 1) for q in (50, 90, 99, 100)}

    px = load_proxy(proxy_path)
    px_co = np.array([px.matrix_world @ v.co for v in px.data.vertices])
    rep["proxy_vs_old_body_mm"] = round(float(np.abs(px_co - old_co).max()) * 1000, 2) if len(px_co) == len(old_co) else "topology differs"

    bvh = BVHTree.FromPolygons([Vector(p) for p in old_co], [tuple(p.vertices) for p in old_b.data.polygons])
    polys = [tuple(p.vertices) for p in old_b.data.polygons]
    P, mw = world_positions(g)
    n = len(P)
    neck = group_weight(g.data, g.vertex_groups, lambda nm: nm.startswith("neck_") or nm == "head")
    disp = np.zeros_like(P)
    for i, p in enumerate(P):
        loc, nrm, fi, dist = bvh.find_nearest(Vector(p))
        vs = polys[fi]
        w = poly_3d_calc([Vector(old_co[j]) for j in vs], loc)
        disp[i] = sum(wk * D[j] for wk, j in zip(w, vs))
    wc = np.clip((neck - 0.05) / 0.2, 0, 1)             # the collar keeps only the VERTICAL part of the body's change
    disp[:, 0] *= (1 - wc)
    disp[:, 1] *= (1 - wc)
    edges = mesh_edges(g.data)
    disp = core.laplacian_smooth(disp, edges, n, smooth)
    set_world_positions(g, P + disp)
    mag = np.linalg.norm(disp, axis=1)
    rep["garment_move_mm"] = {q: round(float(np.percentile(mag, q)) * 1000, 1) for q in (50, 90, 99, 100)}
    rep["collar_verts"] = int((wc > 0.5).sum())

    pinv = px.matrix_world.inverted()
    for v, c in zip(px.data.vertices, new_co):
        v.co = pinv @ Vector(c.tolist())
    px.data.update()
    new_proxy_path = os.path.join(OUT, "body_proxy.blend")
    bpy.data.libraries.write(new_proxy_path, {px}, fake_user=True)
    current_proxy_path = new_proxy_path
    for o in (old_b, new_b, px):
        bpy.data.objects.remove(o, do_unlink=True)
    report["stages"]["reseat"] = rep
    log("reseat: " + json.dumps(rep))

# ============================================================================================================ shrink
if "shrink" in STAGES:
    a = args.get("shrink") or {}
    K, FLOOR = float(a.get("k", 0.7)), float(a.get("floor_m", 0.010))
    MIN_GAP, SMOOTH, BAND = float(a.get("min_gap_m", 0.006)), int(a.get("smooth", 25)), float(a.get("band_m", 0.06))
    COLLAR_W = float(a.get("collar_weight_min", 0.01))
    proxy_path = abspath(a.get("proxy")) or current_proxy_path
    px = load_proxy(proxy_path)
    bv = [px.matrix_world @ v.co for v in px.data.vertices]
    bvh = BVHTree.FromPolygons(bv, [tuple(p.vertices) for p in px.data.polygons])

    P, mw = world_positions(g)
    n = len(P)
    me = g.data
    names = {vg.index: vg.name for vg in g.vertex_groups}
    best, bestw, neck = np.full(n, -1), np.zeros(n), np.zeros(n)
    for v in me.vertices:
        for ge in v.groups:
            nm = names[ge.group]
            if ge.weight > bestw[v.index]:
                bestw[v.index], best[v.index] = ge.weight, ge.group
            if nm.startswith("neck_") or nm == "head":
                neck[v.index] += ge.weight
    slot_of = material_slot(me)
    slot_names = [m.name if m else "" for m in me.materials]
    boots = np.array(["Boots" in slot_names[s] for s in slot_of])

    d = np.zeros(n)
    U = np.zeros_like(P)
    for i, p in enumerate(P):
        loc, nrm, _, dist = bvh.find_nearest(Vector(p))
        v = P[i] - np.array(loc)
        s = 1.0 if np.dot(v, np.array(nrm)) >= 0 else -1.0
        d[i] = s * dist
        U[i] = v / dist if dist > 1e-6 else np.array(nrm)

    edges = mesh_edges(me)
    elen = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)
    adj = [[] for _ in range(n)]
    for (i, j), L in zip(edges, elen):
        adj[i].append((j, L))
        adj[j].append((i, L))
    collar = neck > COLLAR_W
    dist_c = np.full(n, np.inf)
    h = [(0.0, int(i)) for i in np.where(collar)[0]]
    for _, i in h:
        dist_c[i] = 0.0
    heapq.heapify(h)
    while h:
        dd, i = heapq.heappop(h)
        if dd > dist_c[i] or dd > BAND:
            continue
        for j, L in adj[i]:
            nd = dd + L
            if nd < dist_c[j]:
                dist_c[j] = nd
                heapq.heappush(h, (nd, j))
    hold = np.maximum(core.smoothstep_hold(dist_c, BAND), boots.astype(float))

    pull = core.shrink_pull(d, K, FLOOR) * (1.0 - hold)
    D = -U * pull[:, None]
    ni = np.concatenate([edges[:, 0], edges[:, 1]]) if len(edges) else np.zeros(0, int)
    nj = np.concatenate([edges[:, 1], edges[:, 0]]) if len(edges) else np.zeros(0, int)
    deg = np.maximum(np.bincount(ni, minlength=n), 1).astype(float)
    for _ in range(SMOOTH):                            # the held parts fade back toward 0 every round, not just pinned
        acc = np.zeros_like(D)
        np.add.at(acc, ni, D[nj])
        D = 0.5 * D + 0.5 * acc / deg[:, None]
        D *= (1.0 - hold)[:, None]
    P2 = P + D

    lim = np.minimum(np.maximum(d, 0), MIN_GAP)
    clamped = 0
    for i in range(n):
        if not D[i].any():
            continue
        loc, nrm, _, dist = bvh.find_nearest(Vector(P2[i]))
        v = P2[i] - np.array(loc)
        s = 1.0 if np.dot(v, np.array(nrm)) >= 0 else -1.0
        if s * dist < lim[i]:
            lo, hi = 0.0, 1.0
            for _ in range(12):
                mid = (lo + hi) / 2
                pp = P[i] + D[i] * mid
                loc, nrm, _, dist = bvh.find_nearest(Vector(pp))
                vv = pp - np.array(loc)
                ss = 1.0 if np.dot(vv, np.array(nrm)) >= 0 else -1.0
                if ss * dist >= lim[i]:
                    lo = mid
                else:
                    hi = mid
            P2[i] = P[i] + D[i] * lo
            clamped += 1
    set_world_positions(g, P2)

    d2 = np.zeros(n)
    for i, p in enumerate(P2):
        loc, nrm, _, dist = bvh.find_nearest(Vector(p))
        v = p - np.array(loc)
        d2[i] = (1.0 if np.dot(v, np.array(nrm)) >= 0 else -1.0) * dist
    rep = {"k": K, "floor_m": FLOOR, "min_gap_m": MIN_GAP, "band_m": BAND, "verts": n,
           "collar_verts": int(collar.sum()), "boot_verts": int(boots.sum()),
           "gap_mm_before": {q: round(float(np.percentile(d, q)) * 1000, 1) for q in (10, 50, 90)},
           "gap_mm_after": {q: round(float(np.percentile(d2, q)) * 1000, 1) for q in (10, 50, 90)},
           "moved_mm": {q: round(float(np.percentile(np.linalg.norm(P2 - P, axis=1), q)) * 1000, 1) for q in (50, 90, 99, 100)},
           "clamped": clamped, "inside_before": int((d < 0).sum()), "inside_after": int((d2 < 0).sum())}
    bpy.data.objects.remove(px, do_unlink=True)
    report["stages"]["shrink"] = rep
    log("shrink: " + json.dumps(rep))

# ============================================================================================================ collar
if "collar" in STAGES:
    a = args.get("collar") or {}
    CLEAR, FADE = float(a.get("clear_m", 0.008)), float(a.get("fade_m", 0.05))
    NECK_R, CAP = float(a.get("neck_r_m", 0.12)), float(a.get("cap_m", 0.02))
    face, fco = import_fbx_mesh(a["face_fbx"])
    fbvh = BVHTree.FromPolygons([Vector(c) for c in fco], [tuple(p.vertices) for p in face.data.polygons])
    zmin_face = float(fco[:, 2].min())

    P, mw = world_positions(g)
    n = len(P)
    me = g.data
    edges = mesh_edges(me)
    elen = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)
    adj = [[] for _ in range(n)]
    for (i, j), L in zip(edges, elen):
        adj[i].append((j, L))
        adj[j].append((i, L))
    neckw = group_weight(me, g.vertex_groups, lambda nm: nm.startswith("neck_"))
    ring = neckw > 0.01
    cx, cy = (float(np.median(P[ring, 0])), float(np.median(P[ring, 1]))) if ring.any() else (0.0, 0.0)
    cand = (P[:, 2] > zmin_face - 0.02) & (np.hypot(P[:, 0] - cx, P[:, 1] - cy) < NECK_R)

    def gaps(Q):
        d = np.full(n, np.inf)
        nn = np.zeros((n, 3))
        for i in np.nonzero(cand)[0]:
            loc, nrm, fi, dist = fbvh.find_nearest(Vector(Q[i]))
            if loc is None or dist > 0.05:
                continue
            s = 1.0 if (Q[i] - np.array(loc)) @ np.array(nrm) >= 0 else -1.0
            d[i] = s * dist
            nn[i] = nrm
        return d, nn

    rep = {"clear_m": CLEAR, "fade_m": FADE, "neck_r_m": NECK_R, "cap_m": CAP, "candidates": int(cand.sum()), "rounds": []}
    Q = P.copy()
    for rnd in range(4):
        d, nn = gaps(Q)
        bad = d < CLEAR
        rep["rounds"].append({"under_clear": int(bad.sum()), "inside": int((d < 0).sum())})
        if not (d < CLEAR - 0.001).any():
            break
        push = np.zeros((n, 3))
        push[bad] = nn[bad] * np.minimum(CLEAR - d[bad], CAP)[:, None]
        dist, src = np.full(n, np.inf), np.full(n, -1)
        h = []
        for i in np.nonzero(bad)[0]:
            dist[i], src[i] = 0.0, i
            h.append((0.0, int(i)))
        heapq.heapify(h)
        while h:
            dd, i = heapq.heappop(h)
            if dd > dist[i] or dd > FADE:
                continue
            for j, L in adj[i]:
                nd = dd + L
                if nd < dist[j]:
                    dist[j], src[j] = nd, src[i]
                    heapq.heappush(h, (nd, j))
        reach = np.isfinite(dist)
        hold = core.smoothstep_hold(dist[reach], FADE)
        spread = np.zeros((n, 3))
        spread[reach] = push[src[reach]] * hold[:, None]
        spread[bad] = push[bad]
        Q = Q + spread
    set_world_positions(g, Q)
    mv = np.linalg.norm(Q - P, axis=1)
    rep["moved"] = int((mv > 1e-4).sum())
    rep["moved_mm_max"] = round(float(mv.max()) * 1000, 1)
    bpy.data.objects.remove(face, do_unlink=True)
    report["stages"]["collar"] = rep
    log("collar: " + json.dumps(rep))

# ============================================================================================================== lift
if "lift" in STAGES:
    a = args.get("lift") or {}
    CLEAR, FADE, CAP = float(a.get("clear_m", 0.006)), float(a.get("fade_m", 0.03)), float(a.get("cap_m", 0.015))
    proxy_path = abspath(a.get("proxy")) or current_proxy_path
    px = load_proxy(proxy_path)
    pm = px.matrix_world
    bvh = BVHTree.FromPolygons([pm @ v.co for v in px.data.vertices], [tuple(p.vertices) for p in px.data.polygons])

    P, mw = world_positions(g)
    n = len(P)
    me = g.data
    neckw = group_weight(me, g.vertex_groups, lambda nm: nm.startswith("neck_") or nm == "head")
    footw = group_weight(me, g.vertex_groups, lambda nm: nm.startswith(("foot", "ball")))
    slot = material_slot(me)
    mats = [m.name if m else "" for m in me.materials]
    held = (neckw > 0.01) | (footw > 0.5) | np.array(["Boots" in mats[s] for s in slot])
    edges = mesh_edges(me)
    elen = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)
    adj = [[] for _ in range(n)]
    for (i, j), L in zip(edges, elen):
        adj[i].append((j, L))
        adj[j].append((i, L))

    rep = {"clear_m": CLEAR, "fade_m": FADE, "cap_m": CAP, "rounds": []}
    Q = P.copy()
    for rnd in range(3):
        d = np.full(n, np.inf)
        nn = np.zeros((n, 3))
        for i in np.nonzero(~held)[0]:
            loc, nrm, fi, dist = bvh.find_nearest(Vector(Q[i]))
            if loc is None or dist > 0.03:
                continue
            d[i] = (1.0 if (Q[i] - np.array(loc)) @ np.array(nrm) >= 0 else -1.0) * dist
            nn[i] = nrm
        bad = d < CLEAR - 0.0005
        rep["rounds"].append({"under_clear": int(bad.sum()), "inside": int((d < 0).sum())})
        if not bad.any():
            break
        push = np.zeros((n, 3))
        push[bad] = nn[bad] * np.minimum(CLEAR - d[bad], CAP)[:, None]
        dist_, src_ = np.full(n, np.inf), np.full(n, -1)
        h = []
        for i in np.nonzero(bad)[0]:
            dist_[i], src_[i] = 0.0, i
            h.append((0.0, int(i)))
        heapq.heapify(h)
        while h:
            dd, i = heapq.heappop(h)
            if dd > dist_[i] or dd > FADE:
                continue
            for j, L in adj[i]:
                nd = dd + L
                if nd < dist_[j] and not held[j]:
                    dist_[j], src_[j] = nd, src_[i]
                    heapq.heappush(h, (nd, j))
        reach = np.isfinite(dist_)
        hold = core.smoothstep_hold(dist_[reach], FADE)
        spread = np.zeros((n, 3))
        spread[reach] = push[src_[reach]] * hold[:, None]
        spread[bad] = push[bad]
        Q = Q + spread
    set_world_positions(g, Q)
    mv = np.linalg.norm(Q - P, axis=1)
    rep["moved"] = int((mv > 1e-4).sum())
    rep["moved_mm_max"] = round(float(mv.max()) * 1000, 1)
    bpy.data.objects.remove(px, do_unlink=True)
    report["stages"]["lift"] = rep
    log("lift: " + json.dumps(rep))

# =========================================================================================================== weights
if "weights" in STAGES:
    a = args.get("weights") or {}
    NEAR, FAR, MIN_GAP = float(a.get("near_m", 0.012)), float(a.get("far_m", 0.030)), float(a.get("min_gap_m", 0.005))
    MIXED_SHARE = float(a.get("mixed_share", 0.12))
    MAXINF, SMOOTH = 8, 10
    proxy_path = abspath(a.get("proxy")) or current_proxy_path
    px = load_proxy(proxy_path)
    pm = px.matrix_world
    pco = np.array([pm @ v.co for v in px.data.vertices])
    ppolys = [tuple(p.vertices) for p in px.data.polygons]
    pnames = [vg.name for vg in px.vertex_groups]
    pw = [dict() for _ in range(len(pco))]
    for v in px.data.vertices:
        for ge in v.groups:
            if ge.weight > 0:
                pw[v.index][pnames[ge.group]] = ge.weight
    bvh = BVHTree.FromPolygons([Vector(p) for p in pco], ppolys)

    def fam_of(w):
        return core.dominant_family(w) if w else "torso"

    me = g.data
    P, mw = world_positions(g)
    N = np.array([(mw.to_3x3() @ v.normal).normalized() for v in me.vertices])
    n = len(P)
    gnames = {vg.index: vg.name for vg in g.vertex_groups}
    gw = [dict() for _ in range(n)]
    for v in me.vertices:
        for ge in v.groups:
            if ge.weight > 0:
                gw[v.index][gnames[ge.group]] = ge.weight
    neck = np.array([sum(x for k, x in w.items() if k.startswith("neck_") or k == "head") for w in gw])
    slot = material_slot(me)
    mats = [m.name if m else "" for m in me.materials]
    boots = np.array(["Boots" in mats[s] for s in slot]) | np.array(
        [fam_of(w).startswith("leg") and any(k.startswith(("foot", "ball")) for k in w)
         and sum(x for k, x in w.items() if k.startswith(("foot", "ball"))) > 0.5 for w in gw])

    bw = [None] * n
    gap = np.full(n, np.inf)
    under, unorm = np.zeros((n, 3)), np.zeros((n, 3))
    ray_used = 0
    for i in range(n):
        p, nv = Vector(P[i]), Vector(N[i])
        hit = bvh.ray_cast(p + nv * 1e-4, -nv, 0.04)
        if hit[0] is not None:
            loc, nrm, fi, dist = hit
            ray_used += 1
        else:
            loc, nrm, fi, dist = bvh.find_nearest(p)
        vs = ppolys[fi]
        bary = poly_3d_calc([Vector(pco[j]) for j in vs], loc)
        w = {}
        for bk, j in zip(bary, vs):
            for k, x in pw[j].items():
                w[k] = w.get(k, 0) + bk * x
        bw[i] = w
        sgn = 1.0 if (P[i] - np.array(loc)) @ np.array(nrm) >= 0 else -1.0
        gap[i] = sgn * dist
        under[i] = loc
        unorm[i] = nrm

    # 1 at gap <= NEAR, 0 at gap >= FAR, smoothstep between (the same shape p5_weights.py computed by hand)
    b = core.smoothstep_hold(gap - NEAR, FAR - NEAR)
    same = np.array([fam_of(bw[i]) == fam_of(gw[i]) for i in range(n)])
    mix = np.array([core.is_mixed_band(gw[i], MIXED_SHARE) or core.is_mixed_band(bw[i], MIXED_SHARE) for i in range(n)])
    b[(neck > 0.01) | boots | ~same | mix] = 0.0
    locked = (neck > 0.01) | boots
    edges = mesh_edges(me)
    b = core.laplacian_smooth(b[:, None], edges, n, SMOOTH, keep_mask=locked | mix)[:, 0]
    b[locked | mix] = 0.0

    changed = 0
    new = []
    for i in range(n):
        if b[i] <= 1e-3:
            new.append(gw[i])
            continue
        keys = set(gw[i]) | set(bw[i])
        w = {k: (1 - b[i]) * gw[i].get(k, 0) + b[i] * bw[i].get(k, 0) for k in keys}
        top = sorted(w.items(), key=lambda kv: -kv[1])[:MAXINF]
        s = sum(x for _, x in top) or 1.0
        new.append({k: x / s for k, x in top if x / s > 1e-4})
        changed += 1
    groups = {vg.name: vg for vg in g.vertex_groups}
    for i, w in enumerate(new):
        if b[i] <= 1e-3:
            continue
        for vg in g.vertex_groups:
            vg.remove([i])
        for k, x in w.items():
            if k not in groups:
                groups[k] = g.vertex_groups.new(name=k)
            groups[k].add([i], x, "REPLACE")

    lift = (b > 0.5) & (gap < MIN_GAP)
    for i in np.nonzero(lift)[0]:
        q = under[i] + unorm[i] * MIN_GAP
        me.vertices[i].co = g.matrix_world.inverted() @ Vector(q.tolist())
    me.update()
    rep = {"near_m": NEAR, "far_m": FAR, "min_gap_m": MIN_GAP, "verts": n, "ray_hits": ray_used,
           "reweighted": changed, "region_mismatch_skipped": int((~same).sum()), "mixed_band_skipped": int(mix.sum()),
           "collar_locked": int((neck > 0.01).sum()), "boots_locked": int(boots.sum()), "lifted": int(lift.sum()),
           "inside_before": int((gap < 0).sum())}
    bpy.data.objects.remove(px, do_unlink=True)
    report["stages"]["weights"] = rep
    log("weights: " + json.dumps(rep))

# -------------------------------------------------------------------------------------------------------------- write
out_blend = os.path.join(OUT, "fitted.blend")
bpy.ops.wm.save_as_mainfile(filepath=out_blend, copy=True)
report["out_blend"] = out_blend
report["stages_run"] = list(report["stages"])
with open(os.path.join(OUT, "refit_report.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(report, f, indent=1)
print("GARMENT_REFIT " + json.dumps({k: report[k] for k in ("stages_run", "out_blend")}))

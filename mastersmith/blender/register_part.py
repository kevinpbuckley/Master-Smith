"""Turn a vendor seed so its side silhouette matches the part's side picture (inside Blender).
    blender -b -Y --python register_part.py -- <args.json>
args: {"glb", "mask", "out_blend", "out_json"}; mask is a PNG whose non-black pixels are the part as seen from the side
(forward to the right, up is up), cropped to the part.

Image-to-3D vendors put a part in any orientation, and a four-way facing question left the pistol's grip tilted and
bent against its frame (2026-09-27). The four upright turns are tried first (the vendor keeps the picture's up), all 24
axis-aligned orientations only when none matches: each one's silhouette seen from the side (-Y, forward = +X to the
right, +Z up) is rasterised, normalised to its own box, and compared with the picture's by overlap (IoU), with a
penalty for a different aspect. The best one is applied, centred at the origin."""
import itertools
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1]))
RES = 96


def rotations():
    """The 24 rotations of the cube: signed axis permutations with determinant +1."""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            for r, (c, s) in enumerate(zip(perm, signs)):
                m[r, c] = s
            if round(np.linalg.det(m)) == 1:
                out.append(m)
    return out


def raster(tris2d):
    """Fill 2D triangles (n, 3, 2) already in [0, RES) into a RES x RES boolean mask (row 0 = top)."""
    mask = np.zeros((RES, RES), bool)
    ys, xs = np.mgrid[0:RES, 0:RES]
    px, py = xs + 0.5, ys + 0.5
    for t in tris2d:
        (x0, y0), (x1, y1), (x2, y2) = t
        minx, maxx = int(max(0, np.floor(min(x0, x1, x2)))), int(min(RES - 1, np.ceil(max(x0, x1, x2))))
        miny, maxy = int(max(0, np.floor(min(y0, y1, y2)))), int(min(RES - 1, np.ceil(max(y0, y1, y2))))
        if maxx < minx or maxy < miny:
            continue
        sx, sy = px[miny:maxy + 1, minx:maxx + 1], py[miny:maxy + 1, minx:maxx + 1]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-12:
            continue
        a = ((y1 - y2) * (sx - x2) + (x2 - x1) * (sy - y2)) / d
        b = ((y2 - y0) * (sx - x2) + (x0 - x2) * (sy - y2)) / d
        inside = (a >= -1e-6) & (b >= -1e-6) & (a + b <= 1 + 1e-6)
        mask[miny:maxy + 1, minx:maxx + 1] |= inside
    return mask


def side_mask(verts, faces):
    """Silhouette from the side: x across (forward to the right), z up; normalised to its own bounding box."""
    x, z = verts[:, 0], verts[:, 2]
    lo_x, hi_x, lo_z, hi_z = x.min(), x.max(), z.min(), z.max()
    w, h = max(hi_x - lo_x, 1e-9), max(hi_z - lo_z, 1e-9)
    u = (x - lo_x) / w * (RES - 1e-3)
    v = (hi_z - z) / h * (RES - 1e-3)
    tris = np.stack([np.stack([u[faces[:, k]], v[faces[:, k]]], axis=1) for k in range(3)], axis=1)
    return raster(tris), w / h


def picture_mask(path):
    img = bpy.data.images.load(os.path.abspath(path))
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)[::-1]                      # Blender stores rows bottom-up
    m = a[:, :, :3].max(axis=2) > 0.5
    ys, xs = np.nonzero(m)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    aspect = m.shape[1] / float(m.shape[0])
    yi = (np.arange(RES) * m.shape[0] / RES).astype(int)
    xi = (np.arange(RES) * m.shape[1] / RES).astype(int)
    return m[yi][:, xi], aspect


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["glb"]))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
blib.select_only(meshes)
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
# a light copy for the silhouettes
probe = ob.copy()
probe.data = ob.data.copy()
bpy.context.collection.objects.link(probe)
tris = blib.tri_count(probe)
if tris > 4000:
    # welded first: a Tripo seed is split along every UV seam and the unwelded collapse tore thin branches and leaves
    # out of the probe's silhouette (2026-10-03, as in assemble.py's decimate_to)
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(probe.data)
    lo_, hi_ = blib.dims(probe)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=max((hi_ - lo_).length * 1e-6, 1e-9))
    bm.to_mesh(probe.data)
    bm.free()
    m = probe.modifiers.new("dec", "DECIMATE")
    m.ratio = 4000.0 / tris
    blib.select_only([probe])
    bpy.ops.object.modifier_apply(modifier="dec")
me = probe.data
me.calc_loop_triangles()
verts = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", verts)
verts = verts.reshape(-1, 3)
faces = np.empty(len(me.loop_triangles) * 3, np.int32)
me.loop_triangles.foreach_get("vertices", faces)
faces = faces.reshape(-1, 3)
target, t_aspect = picture_mask(args["mask"])


def rz_deg(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])


def rx_deg(deg):
    a = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def face_luminance(o):
    """Per loop triangle of `o`: the luminance of its base-colour texture at the triangle's UV centre, or None when
    the seed carries no texture."""
    img = None
    for sl in o.material_slots:
        m = sl.material
        b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.node_tree else None
        if b is not None and b.inputs["Base Color"].is_linked:
            n = b.inputs["Base Color"].links[0].from_node
            if n.type == "TEX_IMAGE" and n.image is not None:
                img = n.image
                break
    me = o.data
    if img is None or not me.uv_layers.active or not img.size[0]:
        return None
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    lum = (px.reshape(h, w, 4)[:, :, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    loops = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("loops", loops)
    c = uv[loops.reshape(-1, 3)].mean(axis=1) % 1.0
    return lum[(c[:, 1] * (h - 1)).astype(int), (c[:, 0] * (w - 1)).astype(int)]


def picture_luminance(path, mask_path):
    """The colour picture's luminance, cropped to the mask's box and resampled to RES x RES (row 0 = top), with the
    mask, for the appearance comparison."""
    out = []
    for p in (path, mask_path):
        img = bpy.data.images.load(os.path.abspath(p), check_existing=True)
        w, h = img.size
        a = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(a)
        out.append(a.reshape(h, w, 4)[::-1])
    pic, msk = out
    m = msk[:, :, :3].max(axis=2) > 0.5
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    yi = y0 + (np.arange(RES) * (y1 - y0) / RES).astype(int)
    xi = x0 + (np.arange(RES) * (x1 - x0) / RES).astype(int)
    lum = pic[:, :, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return lum[yi][:, xi], m[yi][:, xi]


def side_luminance(rot):
    """The seed's texture seen from the side (-Y), nearest faces on top, normalised to its own box like side_mask."""
    v = verts @ rot.T
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    lo_x, hi_x, lo_z, hi_z = x.min(), x.max(), z.min(), z.max()
    u = (x - lo_x) / max(hi_x - lo_x, 1e-9) * (RES - 1e-3)
    w = (hi_z - z) / max(hi_z - lo_z, 1e-9) * (RES - 1e-3)
    img = np.full((RES, RES), np.nan, np.float32)
    ys, xs = np.mgrid[0:RES, 0:RES]
    px, py = xs + 0.5, ys + 0.5
    for i in np.argsort(-y[faces].mean(axis=1)):                 # far faces first, the camera side painted last
        (x0, y0), (x1, y1), (x2, y2) = [(u[k], w[k]) for k in faces[i]]
        minx, maxx = int(max(0, np.floor(min(x0, x1, x2)))), int(min(RES - 1, np.ceil(max(x0, x1, x2))))
        miny, maxy = int(max(0, np.floor(min(y0, y1, y2)))), int(min(RES - 1, np.ceil(max(y0, y1, y2))))
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if maxx < minx or maxy < miny or abs(d) < 1e-12:
            continue
        sx, sy = px[miny:maxy + 1, minx:maxx + 1], py[miny:maxy + 1, minx:maxx + 1]
        a = ((y1 - y2) * (sx - x2) + (x2 - x1) * (sy - y2)) / d
        b = ((y2 - y0) * (sx - x2) + (x0 - x2) * (sy - y2)) / d
        inside = (a >= -1e-6) & (b >= -1e-6) & (a + b <= 1 + 1e-6)
        img[miny:maxy + 1, minx:maxx + 1][inside] = face_lum[i]
    return img


def appearance(rot):
    """Normalised cross-correlation of the seed's side texture with the picture where both show the part (-1..1)."""
    if face_lum is None:
        return 0.0
    got = side_luminance(rot)
    both = ~np.isnan(got) & pic_mask
    if both.sum() < 50:
        return 0.0
    a, b = got[both] - got[both].mean(), pic_lum[both] - pic_lum[both].mean()
    return float((a * b).sum() / max(np.sqrt((a * a).sum() * (b * b).sum()), 1e-9))


def symmetry_error(points, rot):
    """Mean distance from the points, turned by `rot` and mirrored across their own centre plane (y = mean), to the
    nearest unmirrored point: 0 for a part that is its own mirror image left to right."""
    from mathutils.kdtree import KDTree
    p = points @ rot.T
    tree = KDTree(len(p))
    for i, q in enumerate(p):
        tree.insert(q.tolist(), i)
    tree.balance()
    m = p.copy()
    m[:, 1] = 2 * p[:, 1].mean() - p[:, 1]
    return float(np.mean([tree.find(q.tolist())[2] for q in m]))


def surface_points(n=2500, seed=7):
    """Points spread evenly over the probe's surface (by area), for the symmetry measure."""
    tri = verts[faces]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(faces), size=n, p=area / max(area.sum(), 1e-12))
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return tri[pick, 0] * (1 - s)[:, None] + tri[pick, 1] * (s * (1 - r2))[:, None] + tri[pick, 2] * (s * r2)[:, None]


face_lum = face_luminance(probe)
pic_lum, pic_mask = picture_luminance(args["picture"], args["mask"]) if args.get("picture") else (None, None)
if pic_lum is None:
    face_lum = None


import silhouette  # noqa: E402 - pure numpy, tested
# a lattice (a sea fan, kelp, a branching coral) is compared by its envelope: two lattices overlap by chance
SPARSE = silhouette.fill_ratio(target) < 0.45
target_cmp = silhouette.envelope(target) if SPARSE else target


def score_all(rots):
    out = []
    for rot in rots:
        sil, aspect = side_mask(verts @ rot.T, faces)
        iou = silhouette.iou(silhouette.envelope(sil) if SPARSE else sil, target_cmp)
        out.append((iou - 0.35 * abs(np.log(aspect / t_aspect)), iou, aspect, rot))
    return sorted(out, key=lambda s: -s[0])


# the vendor keeps the picture's up as the model's up, so first only the four turns about the vertical axis: a grip's
# side outline is nearly point-symmetric, and with all 24 orientations the pistol's came out upside down and mirrored
upright = [r for r in rotations() if r[2, 2] == 1]
scores = score_all(upright)
mode = "upright"
if scores[0][1] < 0.5:
    scores = score_all(rotations())
    mode = "any"
if args.get("yaw_sweep"):
    # a seed made from a three-quarter picture comes out turned by that view's angle, not by a multiple of 90 degrees:
    # sweep the turn about the vertical in 5 degree steps, then 1 degree around the best
    def rz(deg):
        a = np.radians(deg)
        return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    # A long object's side silhouette barely changes when it is turned a few degrees (and the fit stretches it back to
    # its box), so the silhouette alone left the bullpup body turned off the barrel's line - a mess from the front
    # (2026-09-27). Its long axis decides the turn: the turn that makes it thinnest from the front; the side
    # silhouette then only picks which end is forward. Objects that are not long fall back to the silhouette sweep.
    def extents(t):
        v = verts @ rz(t).T
        return np.ptp(v[:, 1]), np.ptp(v[:, 0])          # width seen from the front, length seen from the side
    widths = [extents(t)[0] for t in range(0, 180)]
    t0 = min(range(0, 180), key=lambda t: widths[t])
    t0 = min((t0 + e * 0.1 for e in range(-10, 11)), key=lambda t: extents(t)[0])
    width, length = extents(t0)
    # a part that is clearly thinner one way than the other (a barrel, a magazine, a grip, a rail) faces its thin side
    # to the front: the yaw that makes it thinnest seen from the front, then the silhouette picks which end is
    # forward. Length alone missed tall flat parts: the magazine settled on a 45 degree yaw (2026-09-28).
    if width < 0.6 * max(widths):
        scores = score_all([rz(t0), rz(t0 + 180)])
        mode = "long_axis"
    else:
        coarse = score_all([rz(d) for d in range(0, 360, 5)])
        b = coarse[0]
        deg0 = next(d for d in range(0, 360, 5) if np.allclose(rz(d), b[3]))
        fine = score_all([rz(deg0 + d) for d in range(-4, 5)])
        scores = sorted(fine + coarse[1:], key=lambda s: -s[0])
        mode = "yaw_sweep"
best = scores[0]
if args.get("yaw_sweep") and abs(np.log(best[2] / t_aspect)) > np.log(1.8):
    # the seed came out lying down: the M4A1's magazine registered 6.7 times wider than tall against 0.4 in its picture,
    # and a turn about the vertical cannot stand it up (2026-09-29). Each of the six ways up is tried, each with its
    # own thinnest-from-the-front turn, and the best outline wins.
    alt, seen = [], set()
    for U in rotations():
        key = tuple(np.round(U[2], 3))
        if key in seen:
            continue
        seen.add(key)
        vu = verts @ U.T
        t0 = 2 * int(np.argmin([np.ptp((vu @ rz_deg(t).T)[:, 1]) for t in range(0, 180, 2)]))
        alt += score_all([rz_deg(t0) @ U, rz_deg(t0 + 180) @ U])
    alt.sort(key=lambda s: -s[0])
    if alt[0][0] > best[0]:
        best, scores = alt[0], alt
        mode += "+reoriented"
if args.get("yaw_sweep"):
    # a part seeded from a three-quarter picture can also come out PITCHED (turned in the side plane): the magazine
    # lay at 45 degrees and no yaw could fix it (2026-09-28). The side silhouette measures pitch directly.
    def ry(deg):
        a = np.radians(deg)
        return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    base = best[3]
    pitched = score_all([ry(d) @ base for d in range(-75, 76, 5)])
    if pitched[0][1] > best[1] + 0.02:
        d0 = next(d for d in range(-75, 76, 5) if np.allclose(ry(d) @ base, pitched[0][3]))
        fine = score_all([ry(d0 + e) @ base for e in range(-4, 5)])
        best = fine[0]
        mode += "+pitch"
facing = None
if not (args.get("extra_yaw") or args.get("extra_pitch")) and args.get("picture"):
    # a box-like part has the same side outline turned end for end (the Mi-28 fuselage and the crates came back
    # backwards twice, both at 0.92, 2026-09-29): when the outline cannot tell, the seed's own texture seen from the
    # side is compared with the picture, and the better match decides which end is forward
    # The Mi-28 fuselage's outline preferred the wrong end by 0.055 (a three-quarter seed's tail and nose are both
    # tapered), so the texture is asked whenever the two outlines are within 0.1, and it overrules them only when its
    # answer is clear.
    flip = rz_deg(180) @ best[3]
    f_score = score_all([flip])[0]
    if abs(f_score[1] - best[1]) < 0.1:
        a_best, a_flip = appearance(best[3]), appearance(flip)
        facing = {"ncc": round(a_best, 3), "ncc_flipped": round(a_flip, 3), "iou_flipped": round(float(f_score[1]), 3)}
        # a clear answer only: the flash hider flipped on 0.048 against -0.016, noise (2026-09-29)
        if a_flip > a_best + max(0.08, 1.5 * (best[1] - f_score[1])):
            best = f_score
            mode += "+flipped"
if args.get("extra_yaw") or args.get("extra_pitch"):
    # a person's correction after looking at seed_render.png: degrees about the vertical, then in the side plane
    ay, ap_ = np.radians(float(args.get("extra_yaw") or 0)), np.radians(float(args.get("extra_pitch") or 0))
    ryaw = np.array([[np.cos(ay), -np.sin(ay), 0], [np.sin(ay), np.cos(ay), 0], [0, 0, 1]])
    rpit = np.array([[np.cos(ap_), 0, np.sin(ap_)], [0, 1, 0], [-np.sin(ap_), 0, np.cos(ap_)]])
    rot = rpit @ ryaw @ best[3]
    best = score_all([rot])[0]
    mode += "+manual"
symmetry = None
if not args.get("no_symmetry"):
    # a part that is its own mirror image left to right (most are: a receiver, a turret, a fuselage) is squared up on
    # that mirror plane: the M4A1's receiver and grip were registered a few degrees off and zig-zagged seen from the
    # top (2026-09-29). Turns about the vertical (yaw) and the long axis (roll) are searched; a part that is not
    # symmetric (the error stays large) is left as it was.
    pts = surface_points()
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    base = best[3]
    e0 = symmetry_error(pts, base)
    e1, y1, r1 = min((symmetry_error(pts, rx_deg(r) @ rz_deg(y) @ base), y, r) for y in range(-8, 9, 2) for r in range(-8, 9, 2))
    e2, y2, r2 = min((symmetry_error(pts, rx_deg(r1 + dr) @ rz_deg(y1 + dy) @ base), y1 + dy, r1 + dr)
                     for dy in (-1, -0.5, 0, 0.5, 1) for dr in (-1, -0.5, 0, 0.5, 1))
    symmetry = {"error_before": round(e0 / diag, 4), "error_after": round(e2 / diag, 4), "yaw": y2, "roll": r2, "applied": False}
    if e2 < 0.015 * diag and e2 < 0.8 * e0 and (y2 or r2):
        best = score_all([rx_deg(r2) @ rz_deg(y2) @ base])[0]
        mode += "+symmetry"
        symmetry["applied"] = True
bpy.data.objects.remove(probe, do_unlink=True)
R = Matrix([list(r) + [0] for r in best[3]] + [[0, 0, 0, 1]])
ob.data.transform(R)
shear = 0.0
if mode == "long_axis" and best[2] > 1.8:                 # long along X: the perspective slant is along the length
    # a seed made from a three-quarter picture comes out slanted: the picture's perspective (the near end drawn bigger)
    # reads as depth, and the bullpup body's centreline drifted 43% of its width from butt to muzzle, the sights and
    # the grip off the barrel's line (2026-09-27). The drift is a straight line along the length: sheared out.
    co = np.empty(len(ob.data.vertices) * 3, np.float32)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    edges = np.linspace(co[:, 0].min(), co[:, 0].max(), 21)
    xs, mids = [], []
    for a, b in zip(edges, edges[1:]):
        sl = (co[:, 0] >= a) & (co[:, 0] <= b)
        if sl.sum() > 20:
            xs.append((a + b) / 2)
            mids.append((co[sl, 1].min() + co[sl, 1].max()) / 2)
    if len(xs) >= 5:
        shear = float(np.polyfit(xs, mids, 1)[0])
        ob.data.transform(Matrix(((1, 0, 0, 0), (-shear, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))))
lo, hi = blib.dims(ob)
ob.data.transform(Matrix.Translation(-(lo + hi) * 0.5))
ob.name = "Part"
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args["out_blend"]), compress=True)
if args.get("out_render"):
    # the seed as the vendor made it (registered, untouched), for the page next to the picture it was made from
    blib.setup_render(512, 24, look="preview")
    st = blib.Stage(ob, look="preview")
    st.render("iso", os.path.abspath(args["out_render"]))
    st.close()
result = {"mode": mode, "iou": round(float(best[1]), 3), "score": round(float(best[0]), 3), "aspect": round(float(best[2]), 3),
          "target_aspect": round(float(t_aspect), 3), "runner_up_iou": round(float(scores[1][1]), 3), "shear": round(shear, 4),
          "facing": facing, "symmetry": symmetry,
          "rotation": [[round(float(v), 4) if mode != "upright" and mode != "any" else int(v) for v in row] for row in best[3]]}
json.dump(result, open(args["out_json"], "w"), indent=1)
print("[register] best IoU %.3f (aspect %.2f vs %.2f), runner-up %.3f" % (best[1], best[2], t_aspect, scores[1][1]), flush=True)

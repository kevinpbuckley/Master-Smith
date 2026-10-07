"""A real garment for a built MetaHuman, fitted offline (inside Blender):
    blender -b --factory-startup -Y --python-exit-code 1 --python garment_fit.py -- <args.json>
args: {"body_fbx": the BUILT body skeletal mesh exported from Unreal (A-pose, centimetres),
       "seed": the outfit seed (.glb: the character wearing the outfit, bald, A-pose),
       "face_fbx": the built face skeletal mesh (the neck and jaw the collar must clear; without it the MetaHuman template
                   face is set on the body's head bone and the head-turn pass is skipped),
       "out_dir", "name": "PilotGrinder", "part": "Outfit",
       optional: "symmetrize" "right"|"left"|null (mirror that half of the seed onto the other: a collar wing that
                 flares on one side only), "clearance_m" 0.005, "collar_clearance_m" 0.018 (the collar off the neck and
                 jaw at rest), "pose_clearance_m" 0.008 (in the head-turn poses), "ear_gap_m" 0.005 (the collar's rear
                 rim under the ear lobes), "max_offset_m" {"collar", "jacket", "legs", "sole"}, "decimate_to" 50000,
                 "texture_size" 4096, "texture_mode" "dark"|"light", "roughness" {"jacket", "shirt", "trousers",
                 "boots", "lining"}, "shirt_max_value" (the under-layer's colour cut), "pose_match" true, "yaw_deg",
                 "head_rule" "dark"|"skin", "clothing_max_value" 0.22, "render_size" 1024, "samples" 24, "debug"}
Writes into out_dir: fitted.glb (the garment in the conform's frame: metres, Z up, facing -Y, feet at z=0 - the frame
mh_attach.py --source expects), fitted.blend (the same with its weights as vertex groups, for garment_attach.py),
body_proxy.blend (the completed body with its weights: the pose test's torso), T_<Name>_<Part>_BC/RM/N.png (the
garment's own repacked UVs; RM = glTF packing, G roughness, B metallic; N tangent space, OpenGL green),
fit_report.json and the checks fit_*.png rendered with the delivered maps.

Why (2026-10-06, the Proteus MetaHuman batch): a painted outfit has no volume - the collar, the lapels and the jacket's
hem are flat on the skin. The seed of the outfit as worn has the volume; its clothing is cut out by texture colour,
put in the body's frame, its pose matched to the MetaHuman's by posing the MetaHuman's own skeleton onto the seed,
held between a clearance and a stand-off above the posed body, weighted from it, and taken back to the A-pose by
inverse skinning. v6 (after the independent check of v5 scored 5/10): the collar rides spine_05 -> neck_01 only and
stands 18 mm off the neck, clear of the jaw in head turns; the armpits are weighted by inward rays and blended across
label bands; the seed can be symmetrized; the soles stand on the floor; the texture is cleaned, repacked and given
region roughness and a baked leather/cloth normal."""
import heapq
import json
import math
import os
import re
import subprocess
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "mastersmith", "blender"))
import blib  # noqa: E402

args = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
OUT = os.path.abspath(args["out_dir"])
os.makedirs(OUT, exist_ok=True)
NAME, PART = args.get("name", "Character"), args.get("part", "Outfit")
CLEAR = float(args.get("clearance_m", 0.005))
COLLAR_CLEAR = float(args.get("collar_clearance_m", 0.018))
POSE_CLEAR = float(args.get("pose_clearance_m", 0.008))
EAR_GAP = float(args.get("ear_gap_m", 0.005))
MAXOFF = {"collar": 0.09, "jacket": 0.07, "legs": 0.04, "sole": 0.008}
MAXOFF.update(args.get("max_offset_m") or {})
ROUGH = {"jacket": 0.55, "shirt": 0.86, "trousers": 0.80, "boots": 0.45, "lining": 0.62}
ROUGH.update(args.get("roughness") or {})
# the collar's rim follows the neck this much (spine_05 takes the rest; 0 at the seam): with neck_01 alone at 50% the
# rim turned 6 degrees in a 40-degree head turn and the skin behind the jaw swung into it (2026-10-06)
COLLAR_NECK = args.get("collar_neck") or {"neck_01": 0.35, "neck_02": 0.25}
REGIONS = ["Jacket", "Shirt", "Trousers", "Boots"]
report = {"name": NAME, "part": PART, "version": 6, "notes": []}


def log(msg):
    print("[garment_fit] " + msg, flush=True)
    report["notes"].append(msg)


# ----------------------------------------------------------------------------------------------- small helpers
def coords(me):
    a = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def set_coords(me, co):
    me.vertices.foreach_set("co", np.asarray(co, np.float64).ravel())
    me.update()


def bake_object(o):
    """Whatever the importer left on an object or its parents goes into the mesh data (metres, identity object)."""
    bpy.context.view_layer.update()
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)


def import_fbx_skeletal(path):
    """-> (armature in metres with identity transform, [meshes baked to metres]) for an Unreal skeletal mesh FBX.
    Every bone is kept: "head" and the finger tips are leaf bones (mh_attach.py's lesson of 2026-10-04)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.abspath(path), use_anim=False, ignore_leaf_bones=False)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        bake_object(o)
        for m in list(o.modifiers):
            o.modifiers.remove(m)
    if arm is not None:
        mw = arm.matrix_world.copy()
        arm.parent = None
        arm.matrix_world = mw
        blib.select_only([arm])
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)      # the rest pose: the mesh data is the bind pose
    for o in new:
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    return arm, meshes


def edges_of(me):
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def laplacian(values, edges, n, iters, lam=0.5, mask=None):
    """Umbrella smoothing of a per-vertex field over the mesh graph (mask: vertices allowed to change)."""
    v = values.copy()
    deg = np.bincount(edges.ravel(), minlength=n).astype(np.float64)
    deg[deg == 0] = 1
    for _ in range(iters):
        s = np.zeros_like(v)
        np.add.at(s, edges[:, 0], v[edges[:, 1]])
        np.add.at(s, edges[:, 1], v[edges[:, 0]])
        avg = s / (deg[:, None] if v.ndim == 2 else deg)
        nv_ = (1 - lam) * v + lam * avg
        if mask is not None:
            nv_[~mask] = v[~mask]
        v = nv_
    return v


def taubin(P, edges, n, iters, mask, lam=0.5, mu=-0.53):
    """Smoothing that removes lumps without shrinking (alternate shrink and inflate steps)."""
    for _ in range(iters):
        P = laplacian(P, edges, n, 1, lam, mask)
        P = laplacian(P, edges, n, 1, mu, mask)
    return P


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, np.float64) - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def vertex_normals(P, tris):
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    vn = np.zeros_like(P)
    for i in range(3):
        np.add.at(vn, tris[:, i], fn)
    return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)


def csr(edges, n):
    """Neighbour lists of the mesh graph: (offsets, neighbours)."""
    e2 = np.concatenate([edges, edges[:, ::-1]])
    o = np.argsort(e2[:, 0], kind="stable")
    e2 = e2[o]
    off = np.searchsorted(e2[:, 0], np.arange(n + 1))
    return off, e2[:, 1]


def geodesic(seeds, P, edges, n, cap):
    """Distance along the mesh edges from the seed vertices, capped (multi-source Dijkstra)."""
    off, nb = csr(edges, n)
    dist = np.full(n, np.inf)
    h = []
    for s in np.nonzero(seeds)[0]:
        dist[s] = 0.0
        h.append((0.0, int(s)))
    heapq.heapify(h)
    while h:
        d, v = heapq.heappop(h)
        if d > dist[v] or d > cap:
            continue
        for u in nb[off[v]:off[v + 1]]:
            nd = d + float(np.linalg.norm(P[u] - P[v]))
            if nd < dist[u]:
                dist[u] = nd
                heapq.heappush(h, (nd, int(u)))
    return dist


class Surface:
    """A triangulated surface with a BVH: nearest point, normal, triangle and barycentrics."""

    def __init__(self, obj=None, depsgraph=True, co=None, tris=None):
        if obj is not None:
            if depsgraph:
                dg = bpy.context.evaluated_depsgraph_get()
                ev = obj.evaluated_get(dg)
                me = ev.to_mesh()
            else:
                me = obj.data
            me.calc_loop_triangles()
            co = coords(me)
            t = np.empty(len(me.loop_triangles) * 3, np.int64)
            me.loop_triangles.foreach_get("vertices", t)
            tris = t.reshape(-1, 3)
            if depsgraph:
                ev.to_mesh_clear()
        self.co, self.tris = np.asarray(co, np.float64), np.asarray(tris, np.int64)
        a, b, c = (self.co[self.tris[:, i]] for i in range(3))
        fn = np.cross(b - a, c - a)
        self.fn = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
        vn = np.zeros_like(self.co)
        for i in range(3):
            np.add.at(vn, self.tris[:, i], fn)
        self.vn = vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
        self.bvh = BVHTree.FromPolygons([tuple(p) for p in self.co], [tuple(t) for t in self.tris], all_triangles=True)

    def nearest(self, pts):
        """-> location (n,3), smooth normal (n,3), triangle (n,), barycentrics (n,3), signed distance (n,)."""
        n = len(pts)
        loc, tri = np.zeros((n, 3)), np.zeros(n, np.int64)
        for i, p in enumerate(pts):
            r = self.bvh.find_nearest(Vector(p))
            if r[0] is None:
                loc[i], tri[i] = p, 0
            else:
                loc[i], tri[i] = r[0], r[2]
        a, b, c = (self.co[self.tris[tri, i]] for i in range(3))
        bary = barycentric(loc, a, b, c)
        nrm = (bary[:, :1] * self.vn[self.tris[tri, 0]] + bary[:, 1:2] * self.vn[self.tris[tri, 1]]
               + bary[:, 2:] * self.vn[self.tris[tri, 2]])
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        # the side is the face normal's (a smooth normal can lean past a sharp crease); the push follows the smooth one
        d = np.einsum("ij,ij->i", pts - loc, self.fn[tri])
        dist = np.linalg.norm(pts - loc, axis=1)
        return loc, nrm, tri, bary, np.where(d < 0, -dist, dist)


def barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-18, 1e-18, d00 * d11 - d01 * d01)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1 - v - w
    return np.clip(np.stack([u, v, w], 1), 0, 1)


def facing_sign(co):
    """-1 when the figure faces -Y (its toes reach further towards -Y than its heels towards +Y), else +1."""
    z = co[:, 2]
    z0, H = z.min(), z.max() - z.min()
    feet = co[z < z0 + 0.035 * H]
    shins = co[(z > z0 + 0.12 * H) & (z < z0 + 0.2 * H)]
    cy = shins[:, 1].mean()
    return -1 if (cy - feet[:, 1].min()) > (feet[:, 1].max() - cy) else 1


def rotz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def similarity_yaw(P, Q):
    """Scale, yaw-only rotation and translation taking P onto Q (Umeyama, its rotation projected onto yaw)."""
    mp, mq = P.mean(0), Q.mean(0)
    Pc, Qc = P - mp, Q - mq
    C_ = Qc.T @ Pc / len(P)
    U, S, Vt = np.linalg.svd(C_)
    D = np.eye(3)
    if np.linalg.det(U @ Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    R = rotz(math.atan2(R[1, 0], R[0, 0]))
    s = (Qc * (Pc @ R.T)).sum() / max((Pc * Pc).sum(), 1e-12)
    return s, R, mq - s * (R @ mp)


def rotation_between(a, b):
    a, b = Vector(a).normalized(), Vector(b).normalized()
    return a.rotation_difference(b).to_matrix().to_4x4()


# ----------------------------------------------------------------------------------------------- 1. the built body
bpy.ops.wm.read_factory_settings(use_empty=True)
arm, body_meshes = import_fbx_skeletal(args["body_fbx"])
if arm is None:
    raise RuntimeError("%s has no skeleton: export the built body skeletal mesh" % args["body_fbx"])
body = max(body_meshes, key=lambda o: len(o.data.polygons))
for o in body_meshes:
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
body.name = "MH_Body"
mod = body.modifiers.new("Armature", "ARMATURE")
mod.object = arm
bones = {b.name: b for b in arm.data.bones}
NAMES_ALL = [b.name for b in arm.data.bones]
BI = {n: i for i, n in enumerate(NAMES_ALL)}
REST_INV = np.array([np.linalg.inv(np.array(arm.data.bones[n].matrix_local)) for n in NAMES_ALL])
report["body"] = {"fbx": os.path.basename(args["body_fbx"]), "faces": len(body.data.polygons), "bones": len(bones)}
bco = coords(body.data)
log("body %s: %d faces, %d bones, bounds %s .. %s" % (os.path.basename(args["body_fbx"]), len(body.data.polygons), len(bones),
                                                     bco.min(0).round(3).tolist(), bco.max(0).round(3).tolist()))
if facing_sign(bco) != -1:
    log("WARNING the body does not face -Y as an Unreal MetaHuman export does")


def descendants(bname):
    out, todo = [], [bones[bname]]
    while todo:
        b = todo.pop()
        out.append(b.name)
        todo.extend(b.children)
    return out


# the MetaHuman's primary bones; everything else (correctives, twistCor, bicep/tricep, latissimus, pec, scap) is a
# helper that Unreal's body post-process drives by RBF - a garment panel that stands off the skin must not ride them
PRIMARY = re.compile(r"^(root|pelvis|spine_0[1-5]|neck_0[12]|head|clavicle_[lr]|upperarm_[lr]|lowerarm_[lr]|hand_[lr]|"
                     r"(thumb|index|middle|ring|pinky)_(0[1-3]|metacarpal)_[lr]|thigh_[lr]|calf_[lr]|foot_[lr]|ball_[lr]|"
                     r"(upperarm|lowerarm|thigh|calf)_twist_0[12]_[lr])$")


def primary_of(n):
    b = bones.get(n)
    while b is not None and not PRIMARY.match(b.name):
        b = b.parent
    return b.name if b is not None else n


LABELS = ["torso", "arm_l", "arm_r", "leg_l", "leg_r"]
BONE_LABEL = {n: "torso" for n in NAMES_ALL}
for root_, lab_ in (("upperarm_l", "arm_l"), ("upperarm_r", "arm_r"), ("thigh_l", "leg_l"), ("thigh_r", "leg_r")):
    if root_ in bones:
        for n in descendants(root_):
            BONE_LABEL[n] = lab_


def skin_mats():
    """Per bone (NAMES_ALL order): posed @ inverse(rest), from the armature's current pose."""
    bpy.context.view_layer.update()
    P_ = np.array([np.array(arm.pose.bones[n].matrix) for n in NAMES_ALL])
    return np.einsum("bij,bjk->bik", P_, REST_INV)


def lbs(P, idx, w, S):
    """Linear blend skinning with sparse weights (idx into NAMES_ALL, w) -> (posed points, per-vertex 4x4)."""
    M = np.einsum("nk,nkij->nij", w, S[idx])
    return np.einsum("nij,nj->ni", M[:, :3, :3], P) + M[:, :3, 3], M


def reset_pose():
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


def pose_steps(steps):
    """Turn bones about world axes through their heads (the armature is identity: world = armature space)."""
    reset_pose()
    for bone, axis, deg in steps:
        if bone not in arm.pose.bones:
            continue
        pb = arm.pose.bones[bone]
        h = pb.head.copy()
        R = Matrix.Rotation(math.radians(deg), 4, Vector(axis))
        pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.matrix
        bpy.context.view_layer.update()


# the head poses the collar must clear (the pose test uses the same): +-40 deg yaw split over the neck, +-15 deg nod
HEAD_POSES = {
    "yaw_l40": [("neck_01", (0, 0, 1), 13), ("neck_02", (0, 0, 1), 12), ("head", (0, 0, 1), 15)],
    "yaw_r40": [("neck_01", (0, 0, 1), -13), ("neck_02", (0, 0, 1), -12), ("head", (0, 0, 1), -15)],
    "nod_down15": [("neck_01", (1, 0, 0), 4), ("neck_02", (1, 0, 0), 5), ("head", (1, 0, 0), 6)],
    "nod_up15": [("neck_01", (1, 0, 0), -4), ("neck_02", (1, 0, 0), -5), ("head", (1, 0, 0), -6)],
    "yaw_l30_down10": [("neck_01", (0, 0, 1), 10), ("neck_02", (0, 0, 1), 9), ("head", (0, 0, 1), 11),
                       ("neck_02", (1, 0, 0), 4), ("head", (1, 0, 0), 6)],
    "yaw_r30_down10": [("neck_01", (0, 0, 1), -10), ("neck_02", (0, 0, 1), -9), ("head", (0, 0, 1), -11),
                       ("neck_02", (1, 0, 0), 4), ("head", (1, 0, 0), 6)],
}


# ----------------------------------------------------------------------------------------------- 2. the neck (face mesh)
def face_proxy():
    """The built face mesh when given, else the MetaHuman template face moved onto the body's head bone: the neck the
    collar must clear (the body mesh stops at the neck seam). Its skin weights are kept for the head-turn pass, each
    facial bone read as its nearest ancestor in the body skeleton (the facial bones ride the head)."""
    path = args.get("face_fbx")
    exact = bool(path and os.path.exists(path))
    if not exact:
        path = os.path.join(ROOT, "mastersmith", "metahuman", "templates", "SKM_Face.fbx")
    farm, fmeshes = import_fbx_skeletal(path)
    if not fmeshes:
        return None, exact, None
    keep_ = max(fmeshes, key=lambda o: len(o.data.vertices))
    for o in fmeshes:
        if o is not keep_:
            bpy.data.objects.remove(o, do_unlink=True)
    face = keep_
    face.name = "MH_Face"
    fparent = {b.name: (b.parent.name if b.parent else None) for b in farm.data.bones} if farm else {}
    if not exact and farm is not None and "head" in farm.data.bones and "head" in bones:
        delta = bones["head"].head_local - farm.data.bones["head"].head_local
        face.data.transform(Matrix.Translation(delta))
        log("template face set on the body's head bone (moved %s m)" % [round(v, 3) for v in delta])
    if farm is not None:
        bpy.data.objects.remove(farm, do_unlink=True)
    # sparse skin weights onto body bones
    gnames = [vg.name for vg in face.vertex_groups]

    def to_body(n):
        while n is not None and n not in BI:
            n = fparent.get(n)
        return BI.get(n, BI.get("head", 0))
    gmap = [to_body(n) for n in gnames]
    nf = len(face.data.vertices)
    K = 4
    fidx = np.zeros((nf, K), np.int64)
    fw = np.zeros((nf, K))
    for v in face.data.vertices:
        acc = {}
        for g in v.groups:
            if g.weight > 0:
                b_ = gmap[g.group]
                acc[b_] = acc.get(b_, 0.0) + g.weight
        if not acc:
            acc = {BI.get("head", 0): 1.0}
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:K]
        s = sum(w_ for _, w_ in top)
        for k, (b_, w_) in enumerate(top):
            fidx[v.index, k], fw[v.index, k] = b_, w_ / s
    return face, exact, (fidx, fw)


face, face_exact, face_skin = face_proxy()
report["face"] = {"exact": face_exact, "faces": len(face.data.polygons) if face else 0}
fco = coords(face.data) if face else None
face_surf = Surface(face, depsgraph=False) if face else None


def ear_lobes():
    """Each ear lobe's lowest point, from MetaHuman's shared head UVs (the ear landmark) and the mesh round it."""
    if face is None:
        return {}
    me = face.data
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers[0].data.foreach_get("uv", uv)
    uv = np.mod(uv.reshape(-1, 2), 1.0)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    out = {}
    for side, u in (("l", 0.838907), ("r", 0.161093)):
        d = np.linalg.norm(uv - np.array([u, 0.532183]), axis=1)
        i = int(np.argmin(d))
        if d[i] > 0.01:
            continue
        c = fco[lv[i]]
        sel = (np.linalg.norm(fco - c, axis=1) < 0.045) & (np.abs(fco[:, 0]) > abs(c[0]) - 0.012)
        lob = fco[sel][np.argmin(fco[sel][:, 2])]
        EAR_V[sel] = True
        out[side] = {"centre": c.round(4).tolist(), "lobe": lob.round(4).tolist()}
    return out


EAR_V = np.zeros(len(fco) if fco is not None else 0, bool)
EARS = ear_lobes()
report["ears"] = EARS
log("ear lobes: %s" % EARS)
face_low, Z_LOW = None, None
if face is not None:
    # the neck and the jaw: the face mesh below the ear lobes, the ears left out. The fit holds the garment off THIS:
    # pushed off the ears (and the lobes' tips), the collar grew a flat fin under each ear (the review's "left rear
    # wing", 2026-10-06); the ears are handled by lowering the collar's rim under them
    Z_LOW = (min(e["lobe"][2] for e in EARS.values()) if EARS else float(fco[:, 2].min()) + 0.20) + 0.003
    _ft = face_surf.tris
    face_low = Surface(co=fco, tris=_ft[(fco[_ft].max(1)[:, 2] < Z_LOW) & ~EAR_V[_ft].any(1)])


def complete_body(body):
    """The whole body when the build removed the faces hidden under MetaHuman's default outfit (PilotGrinder's export,
    2026-10-06: arms and legs only, 47k of 60k faces): the template body (same topology, same UVs) posed onto the built
    skeleton, its vertices that the build kept moved exactly onto the build's, the rest (torso, hips, the neck seam) by a
    harmonic fill of those offsets, held at the neck by the built face's lowest ring. The garment needs a torso to stand
    off and to take spine weights from; in the engine that torso does not exist, so the garment must cover the hole."""
    tpath = os.path.join(ROOT, "mastersmith", "metahuman", "templates", "SKM_Body.fbx")
    tarm, tmeshes = import_fbx_skeletal(tpath)
    tb = max(tmeshes, key=lambda o: len(o.data.polygons))
    for o in tmeshes:
        if o is not tb:
            bpy.data.objects.remove(o, do_unlink=True)
    if len(tb.data.vertices) <= len(body.data.vertices):
        bpy.data.objects.remove(tb, do_unlink=True)
        bpy.data.objects.remove(tarm, do_unlink=True)
        return body, {"complete": True}
    depth = {b.name: len(b.parent_recursive) for b in tarm.data.bones}
    for dlev in sorted(set(depth.values())):
        for n in [n for n, dv in depth.items() if dv == dlev and n in bones]:
            tarm.pose.bones[n].matrix = bones[n].matrix_local.copy()
        bpy.context.view_layer.update()
    tm = tb.modifiers.new("Armature", "ARMATURE")
    tm.object = tarm
    bpy.context.view_layer.update()
    T = Surface(tb).co

    def loop_uv(me):
        u = np.empty(len(me.loops) * 2)
        me.uv_layers[0].data.foreach_get("uv", u)
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", lv)
        return u.reshape(-1, 2), lv
    tuv, tlv = loop_uv(tb.data)
    guv, glv = loop_uv(body.data)
    kd = KDTree(len(tuv))
    for i, (u, v) in enumerate(tuv):
        kd.insert((u, v, 0.0), i)
    kd.balance()
    G0 = coords(body.data)
    first = {}
    for li, vi in enumerate(glv):
        first.setdefault(int(vi), li)
    match = np.full(len(G0), -1)
    for vi, li in first.items():
        cands = kd.find_n((guv[li, 0], guv[li, 1], 0.0), 4)
        best, bd = -1, 1e9
        for co_, ti, du in cands:
            if du > 1e-4:
                continue
            tv = tlv[ti]
            dd = np.linalg.norm(T[tv] - G0[vi])
            if dd < bd:
                best, bd = tv, dd
        if best >= 0 and bd < 0.06:
            match[vi] = best
    nt = len(T)
    known = np.zeros(nt, bool)
    r = np.zeros((nt, 3))
    ok = match >= 0
    known[match[ok]] = True
    r[match[ok]] = G0[ok] - T[match[ok]]
    te = edges_of(tb.data)
    tle = np.empty(len(tb.data.loops), np.int64)
    tb.data.loops.foreach_get("edge_index", tle)
    ecount = np.bincount(tle, minlength=len(te))
    bverts = np.unique(te[ecount == 1].ravel())
    neck_n = 0
    if face is not None and "spine_05" in bones:
        zs = bones["spine_05"].head_local.z
        fkd = KDTree(len(fco))
        for i, p in enumerate(fco):
            fkd.insert(p, i)
        fkd.balance()
        for v in bverts:
            if T[v, 2] > zs and not known[v]:
                p, i, dist = fkd.find(T[v])
                if dist < 0.04:
                    known[v] = True
                    r[v] = np.array(p) - T[v]
                    neck_n += 1
    unknown = ~known
    nbr_sum = np.zeros_like(r)
    deg = np.bincount(te.ravel(), minlength=nt).astype(float)
    deg[deg == 0] = 1
    for _ in range(3000):
        nbr_sum[:] = 0
        np.add.at(nbr_sum, te[:, 0], r[te[:, 1]])
        np.add.at(nbr_sum, te[:, 1], r[te[:, 0]])
        r[unknown] = nbr_sum[unknown] / deg[unknown, None]
    P = T + r
    tb.modifiers.remove(tm)
    set_coords(tb.data, P)
    gw = {}
    gnames = [vg.name for vg in body.vertex_groups]
    for v in body.data.vertices:
        if match[v.index] >= 0:
            gw[int(match[v.index])] = [(gnames[g.group], g.weight) for g in v.groups if g.weight > 0]
    tnames = [vg.name for vg in tb.vertex_groups]
    tw = {v.index: [(tnames[g.group], g.weight) for g in v.groups if g.weight > 0] for v in tb.data.vertices}
    for vg in list(tb.vertex_groups):
        tb.vertex_groups.remove(vg)
    groups = {}
    for vi in range(nt):
        for gname, w in gw.get(vi, tw[vi]):
            if gname not in groups:
                groups[gname] = tb.vertex_groups.new(name=gname)
            groups[gname].add([vi], w, "REPLACE")
    bpy.data.objects.remove(tarm, do_unlink=True)
    bpy.data.objects.remove(body, do_unlink=True)
    tb.name = "MH_Body"
    mm = tb.modifiers.new("Armature", "ARMATURE")
    mm.object = arm
    info = {"complete": False, "built_vertices": int(len(G0)), "template_vertices": int(nt), "matched": int(ok.sum()),
            "unmatched_built": int((~ok).sum()), "neck_ring_held": int(neck_n), "filled": int(unknown.sum()),
            "max_match_mm": round(float(np.linalg.norm(G0[ok] - T[match[ok]], axis=1).max()) * 1000, 1)}
    log("body completed from the template: %s" % info)
    return tb, info


body, report["body_completion"] = complete_body(body)
bco = coords(body.data)
H_body = float(max(bco[:, 2].max(), fco[:, 2].max() if fco is not None else 0) - bco[:, 2].min())
log("MetaHuman height %.3f m (%s)" % (H_body, "built face" if face_exact else "template face on the head bone"))
# the completed body with its weights for the pose test (its torso is where the jacket's pokes would show)
_px = body.copy()
_px.data = body.data.copy()
_px.name = _px.data.name = "MH_BodyProxy"
for m in list(_px.modifiers):
    _px.modifiers.remove(m)
bpy.data.libraries.write(os.path.join(OUT, "body_proxy.blend"), {_px}, fake_user=True)
bpy.data.objects.remove(_px, do_unlink=True)

# ----------------------------------------------------------------------------------------------- 3. the seed
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args["seed"]))
smeshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
for o in smeshes:
    bake_object(o)
for o in [o for o in bpy.data.objects if o not in before and o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
blib.select_only(smeshes)
if len(smeshes) > 1:
    bpy.ops.object.join()
seed = bpy.context.view_layer.objects.active
seed.name = "Seed"
sme = seed.data
log("seed %s: %d faces" % (os.path.basename(args["seed"]), len(sme.polygons)))

mat = sme.materials[0] if sme.materials else None
bc_img, rough_img = None, None
if mat and mat.use_nodes:
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf and bsdf.inputs["Base Color"].links:
        n = bsdf.inputs["Base Color"].links[0].from_node
        bc_img = n.image if n.type == "TEX_IMAGE" else None
    if bsdf and bsdf.inputs["Roughness"].links:
        src = bsdf.inputs["Roughness"].links[0].from_node
        while src.type != "TEX_IMAGE" and src.inputs and src.inputs[0].links:
            src = src.inputs[0].links[0].from_node
        rough_img = src.image if src.type == "TEX_IMAGE" else None
if bc_img is None:
    raise RuntimeError("the seed has no base colour texture to cut the clothing by")
small = bc_img.copy()
small.scale(1024, 1024)
px = np.empty(1024 * 1024 * 4, np.float32)
small.pixels.foreach_get(px)
px = px.reshape(1024, 1024, 4)
bpy.data.images.remove(small)


def face_colours(me):
    """Per face: the seed texture's colour at its UV centre -> (rgb, value, saturation, hue, uv centre)."""
    npoly_ = len(me.polygons)
    ls = np.empty(npoly_, np.int64)
    lt = np.empty(npoly_, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    uv_ = np.empty(len(me.loops) * 2, np.float64)
    me.uv_layers.active.data.foreach_get("uv", uv_)
    uv_ = uv_.reshape(-1, 2)
    fuv_ = np.add.reduceat(uv_, ls) / lt[:, None]
    iu = np.clip((np.mod(fuv_[:, 0], 1.0) * 1024).astype(int), 0, 1023)
    iv = np.clip((np.mod(fuv_[:, 1], 1.0) * 1024).astype(int), 0, 1023)
    rgb_ = px[iv, iu, :3]
    mx_, mn_ = rgb_.max(1), rgb_.min(1)
    sat_ = np.where(mx_ > 1e-4, (mx_ - mn_) / np.maximum(mx_, 1e-4), 0)
    r_, g_, b_ = rgb_[:, 0], rgb_[:, 1], rgb_[:, 2]
    d_ = np.maximum(mx_ - mn_, 1e-6)
    hue_ = np.where(mx_ == r_, ((g_ - b_) / d_) % 6, np.where(mx_ == g_, (b_ - r_) / d_ + 2, (r_ - g_) / d_ + 4)) * 60
    return rgb_, mx_, sat_, hue_, ls, lt


def classify(me):
    """The seed's per-face arrays: colours, skin candidates, loops, edge-adjacent face pairs, areas."""
    rgb_, mx_, sat_, hue_, ls, lt = face_colours(me)
    npoly_ = len(me.polygons)
    SK = args.get("skin_rule", {})
    r_, b_ = rgb_[:, 0], rgb_[:, 2]
    cand = ((mx_ > SK.get("min_value", 0.25)) & (sat_ > SK.get("min_sat", 0.08)) & (sat_ < SK.get("max_sat", 0.85))
            & ((hue_ < SK.get("max_hue", 50)) | (hue_ > 340)) & (r_ > b_))
    le_ = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("edge_index", le_)
    po = np.argsort(ls)
    lp_ = np.empty(len(me.loops), np.int64)
    lp_[np.concatenate([np.arange(a, a + t) for a, t in zip(ls[po], lt[po])])] = np.repeat(po, lt[po])
    o_ = np.argsort(le_, kind="stable")
    le2, lp2 = le_[o_], lp_[o_]
    same = le2[1:] == le2[:-1]
    pr = np.stack([lp2[:-1][same], lp2[1:][same]], 1)
    ar = np.empty(npoly_, np.float64)
    me.polygons.foreach_get("area", ar)
    fv_ = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", fv_)
    return {"npoly": npoly_, "lstart": ls, "ltotal": lt, "rgb": rgb_, "mx": mx_, "sat": sat_, "hue": hue_,
            "skin_cand": cand, "loop_poly": lp_, "pairs": pr, "area": ar, "fverts": fv_}


def components(mask, C_):
    """Connected components of the faces in mask (edge-adjacent) -> label per face (-1 outside the mask)."""
    parent = np.arange(C_["npoly"])

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root
    pm = C_["pairs"][mask[C_["pairs"][:, 0]] & mask[C_["pairs"][:, 1]]]
    for a, b in pm:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    lab = np.array([find(i) for i in range(C_["npoly"])])
    lab[~mask] = -1
    return lab


def first_cut(C_):
    """Skin = large skin-coloured regions; everything else in the big islands is clothing (refined by region later)."""
    lab = components(C_["skin_cand"], C_)
    tot_ = C_["area"].sum()
    skin_big_ = np.zeros(C_["npoly"], bool)
    parts = []
    for L in np.unique(lab[lab >= 0]):
        sel = lab == L
        if C_["area"][sel].sum() > 0.003 * tot_:
            skin_big_ |= sel
            parts.append(sel)
    lab2 = components(~skin_big_, C_)
    keep_ = np.zeros(C_["npoly"], bool)
    ga = {L: C_["area"][lab2 == L].sum() for L in np.unique(lab2[lab2 >= 0])}
    gm = max(ga.values())
    for L, a in ga.items():
        if a > 0.01 * gm:
            keep_ |= lab2 == L
    vk = np.zeros(len(sme.vertices), bool)
    vk[C_["fverts"][keep_[C_["loop_poly"]]]] = True
    return keep_, parts, skin_big_, vk, {"faces": int(C_["npoly"]), "skin_faces": int(skin_big_.sum()), "skin_parts": len(parts),
                                         "garment_faces": int(keep_.sum()),
                                         "dropped_islands": int(sum(1 for a in ga.values() if a <= 0.01 * gm))}


C = classify(sme)
keep, skin_parts, skin_big, vert_keep, report["cut"] = first_cut(C)
log("cut: %s" % report["cut"])

# ----------------------------------------------------------------------------------------------- 5. the seed in the body's frame
sco = coords(sme)
if args.get("yaw_deg") is not None:
    turn = math.radians(float(args["yaw_deg"]))
else:
    turn = 0.0 if facing_sign(sco) == -1 else math.pi
H_seed = float(sco[:, 2].max() - sco[:, 2].min())
s0 = H_body / H_seed
X = (sco - [0, 0, sco[:, 2].min()]) @ rotz(turn).T * s0
legs_b = bco[(bco[:, 2] > 0.15 * H_body) & (bco[:, 2] < 0.4 * H_body)]
legs_s = X[(X[:, 2] > 0.15 * H_body) & (X[:, 2] < 0.4 * H_body)]
X[:, :2] += legs_b[:, :2].mean(0) - legs_s[:, :2].mean(0)
log("seed turned %.0f deg, scaled %.4f to the MetaHuman's height, legs centred" % (math.degrees(turn), s0))
rest = Surface(body, depsgraph=True)
zc = X[:, 2]
ax = np.abs(X[:, 0] - legs_b[:, 0].mean())
legs_sel = vert_keep & (zc > 0.1 * H_body) & (zc < 0.42 * H_body) & (ax < 0.12 * H_body)
torso_sel = vert_keep & (zc > 0.56 * H_body) & (zc < 0.72 * H_body) & (ax < 0.09 * H_body)
idx = np.nonzero(legs_sel | torso_sel)[0]
rng = np.random.default_rng(1)
idx = rng.choice(idx, min(len(idx), 6000), replace=False)
off_target = np.where(legs_sel[idx], 0.008, 0.02)
s_acc, R_acc, t_acc = 1.0, np.eye(3), np.zeros(3)
P0 = X[idx]
for it in range(25):
    P = (P0 @ R_acc.T) * s_acc + t_acc
    loc, nrm, tri, bary, dist = rest.nearest(P)
    Q = loc + nrm * off_target[:, None]
    res = np.linalg.norm(P - Q, axis=1)
    ok = res < np.quantile(res, 0.7)
    s, R, t = similarity_yaw(P[ok], Q[ok])
    s_acc, R_acc, t_acc = s * s_acc, R @ R_acc, s * (R @ t_acc) + t
    if abs(s - 1) < 1e-5 and np.linalg.norm(t) < 1e-5:
        break
X = (X @ R_acc.T) * s_acc + t_acc
yaw_icp = math.degrees(math.atan2(R_acc[1, 0], R_acc[0, 0]))
report["alignment"] = {"turn_deg": round(math.degrees(turn), 1), "scale": round(s0 * s_acc, 5), "icp_scale": round(s_acc, 5),
                       "icp_yaw_deg": round(yaw_icp, 3), "icp_shift_m": [round(float(v), 4) for v in t_acc],
                       "icp_median_residual_mm": round(float(np.median(res)) * 1000, 2), "icp_iterations": it + 1}
log("ICP: %s" % report["alignment"])
set_coords(sme, X)
cx_body = float(legs_b[:, 0].mean())

# ----------------------------------------------------------------------------------------------- 5b. symmetric seed
SYM = args.get("symmetrize")
if SYM in ("right", "left"):
    # 2026-10-06: the seed's left collar wing flared out flat like a fin while the right hugged the neck; mirroring the
    # good half (about the seed's own mirror plane, found by scanning) gives a symmetric collar, cuffs and boots
    sel = vert_keep & (np.abs(X[:, 0] - cx_body) < 0.16) & (X[:, 2] > 0.25 * H_body) & (X[:, 2] < 0.8 * H_body)
    Ssm = X[sel]
    Ssm = Ssm[rng.choice(len(Ssm), min(len(Ssm), 12000), replace=False)]
    kd = KDTree(len(Ssm))
    for i, p in enumerate(Ssm):
        kd.insert(p, i)
    kd.balance()
    best = (1e9, cx_body)
    for c_ in np.arange(cx_body - 0.03, cx_body + 0.0301, 0.0015):
        M_ = Ssm[::4].copy()
        M_[:, 0] = 2 * c_ - M_[:, 0]
        sc = float(np.median([kd.find(p)[2] for p in M_]))
        if sc < best[0]:
            best = (sc, float(c_))
    set_coords(sme, X - [best[1], 0, 0])
    bm = bmesh.new()
    bm.from_mesh(sme)
    bmesh.ops.symmetrize(bm, input=bm.verts[:] + bm.edges[:] + bm.faces[:], direction="-X" if SYM == "right" else "X", dist=1e-5)
    bm.to_mesh(sme)
    bm.free()
    X = coords(sme)                     # symmetric about x = 0 (the body's midline is within 0.1 mm of it)
    report["symmetrize"] = {"kept": SYM, "mirror_plane_x_m": round(best[1], 4), "median_mirror_gap_mm": round(best[0] * 1000, 2),
                            "faces": len(sme.polygons)}
    log("seed symmetrized: the %s half mirrored about x=%.4f (median gap %.1f mm), %d faces" % (SYM, best[1], best[0] * 1000, len(sme.polygons)))
    C = classify(sme)
    keep, skin_parts, skin_big, vert_keep, cut2 = first_cut(C)
    report["cut"]["after_symmetrize"] = cut2
npoly, fverts, loop_poly, area = C["npoly"], C["fverts"], C["loop_poly"], C["area"]
tot = area.sum()
mx, sat, hue, skin_cand = C["mx"], C["sat"], C["hue"], C["skin_cand"]
r_col, b_col = C["rgb"][:, 0], C["rgb"][:, 2]
DEBUG = bool(args.get("debug"))

# ----------------------------------------------------------------------------------------------- 6. the MetaHuman posed onto the seed
side_bones = {}
for side in ("l", "r"):
    side_bones[side] = {"upper": "upperarm_" + side, "lower": "lowerarm_" + side, "hand": "hand_" + side,
                        "thigh": "thigh_" + side, "calf": "calf_" + side, "foot": "foot_" + side}
_bnames = [vg.name for vg in body.vertex_groups]
vg_names = list(_bnames)
for n_ in _bnames + ["spine_05", "neck_01", "neck_02", "spine_04", "pelvis"]:
    for q_ in (n_, primary_of(n_)):
        if q_ in bones and q_ not in vg_names:
            vg_names.append(q_)
gi = {n: i for i, n in enumerate(vg_names)}
nb = len(body.data.vertices)
W = np.zeros((nb, len(vg_names)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, gi[_bnames[g.group]]] = g.weight


def group_mass(names):
    cols = [gi[n] for n in names if n in gi]
    return W[:, cols].sum(1) if cols else np.zeros(nb)


pose_report = {}
if args.get("pose_match", True):
    skin_v = np.zeros(len(sme.vertices), bool)
    cx = cx_body
    best_ = {}
    for part in skin_parts:
        pv = np.zeros(len(sme.vertices), bool)
        pv[fverts[part[loop_poly]]] = True
        c = X[pv].mean(0)
        if c[2] < 0.75 * H_body and area[part].sum() > 0.001 * tot:
            sd = 1 if c[0] > cx else -1
            best_.setdefault(sd, []).append((abs(c[0] - cx), pv))
    # the hand is every skin part on its side within 8 cm of the outermost one (2026-10-06, DrHart: the Hi3D seed split
    # each hand along its UV seams into a back-of-hand piece and a fingers piece; the outermost alone, the fingers, lay
    # 8 cm from the cuff, so no sleeve rim was found, the arm was not posed onto the sleeve and came through its back)
    for sd, cands_ in best_.items():
        far_ = max(d_ for d_, _ in cands_)
        for d_, pv in cands_:
            if d_ > far_ - 0.08:
                skin_v |= pv
    for side in ("l", "r"):
        sb = side_bones[side]
        if sb["upper"] not in bones:
            continue
        sgn = 1 if bones[sb["hand"]].head_local.x > 0 else -1
        seed_hand = X[skin_v & (np.sign(X[:, 0] - cx) == sgn)]
        hand_w = group_mass(descendants(sb["hand"])) > 0.5
        mov = {}
        if len(seed_hand) > 50 and hand_w.sum() > 50:
            target = seed_hand.mean(0)
            hk = KDTree(len(seed_hand))
            for i_, p_ in enumerate(seed_hand):
                hk.insert(p_, i_)
            hk.balance()
            cloth_side = np.nonzero(vert_keep & (np.sign(X[:, 0] - cx) == sgn))[0]
            rim = [i_ for i_ in cloth_side if hk.find(X[i_])[2] < 0.03]
            S0 = np.array(arm.pose.bones[sb["upper"]].head)
            if len(rim) > 20:
                wrist_seed = X[rim].mean(0)
                ax_ = wrist_seed - S0
                u_ = ax_ / np.linalg.norm(ax_)
                Xs = X[cloth_side]
                t_ = (Xs - S0) @ u_
                rad_ = np.linalg.norm(Xs - S0 - t_[:, None] * u_, axis=1)
                Lu = float(np.linalg.norm(np.array(arm.pose.bones[sb["lower"]].head) - S0))
                band = (np.abs(t_ - Lu) < 0.04) & (rad_ < 0.10)
                if band.sum() > 30:
                    elbow_seed = Xs[band].mean(0)
                    pb = arm.pose.bones[sb["upper"]]
                    E0 = np.array(arm.pose.bones[sb["lower"]].head)
                    Rm = rotation_between(E0 - S0, elbow_seed - S0)
                    pb.matrix = Matrix.Translation(Vector(S0)) @ Rm @ Matrix.Translation(Vector(-S0)) @ pb.matrix
                    bpy.context.view_layer.update()
                    E1 = np.array(arm.pose.bones[sb["lower"]].head)
                    W1 = np.array(arm.pose.bones[sb["hand"]].head)
                    pl = arm.pose.bones[sb["lower"]]
                    Rm = rotation_between(W1 - E1, wrist_seed - E1)
                    pl.matrix = Matrix.Translation(Vector(E1)) @ Rm @ Matrix.Translation(Vector(-E1)) @ pl.matrix
                    bpy.context.view_layer.update()
                    mov["elbow_miss_mm"] = round(float(np.linalg.norm(np.array(arm.pose.bones[sb["lower"]].head) - elbow_seed)) * 1000, 1)
                    mov["wrist_miss_mm"] = round(float(np.linalg.norm(np.array(arm.pose.bones[sb["hand"]].head) - wrist_seed)) * 1000, 1)
            else:
                for _ in range(3):
                    cur = Surface(body).co[hand_w].mean(0)
                    S = arm.pose.bones[sb["upper"]].head
                    Rm = rotation_between(cur - np.array(S), target - np.array(S))
                    pb = arm.pose.bones[sb["upper"]]
                    pb.matrix = Matrix.Translation(S) @ Rm @ Matrix.Translation(-S) @ pb.matrix
                    bpy.context.view_layer.update()
            cur = Surface(body).co[hand_w].mean(0)
            mov["hand_miss_mm"] = round(float(np.linalg.norm(cur - target)) * 1000, 1)
        foot_w = group_mass(descendants(sb["foot"])) > 0.5
        seed_foot = X[vert_keep & (X[:, 2] < 0.06 * H_body) & (np.sign(X[:, 0] - cx) == sgn)]
        if len(seed_foot) > 50 and foot_w.sum() > 50:
            target = seed_foot.mean(0)
            target[2] = Surface(body).co[foot_w].mean(0)[2]
            for _ in range(2):
                cur = Surface(body).co[foot_w].mean(0)
                S = arm.pose.bones[sb["thigh"]].head
                Rm = rotation_between(cur - np.array(S), target - np.array(S))
                pb = arm.pose.bones[sb["thigh"]]
                pb.matrix = Matrix.Translation(S) @ Rm @ Matrix.Translation(-S) @ pb.matrix
                bpy.context.view_layer.update()
            cur = Surface(body).co[foot_w].mean(0)
            mov["foot_miss_mm"] = round(float(np.linalg.norm((cur - target)[:2])) * 1000, 1)
        pose_report[side] = mov
    log("pose match (the MetaHuman posed onto the seed): %s" % pose_report)
report["pose_match"] = pose_report
posed = Surface(body)
POSED_S = skin_mats()                 # the seed-matched pose, kept for the inverse skinning

# ----------------------------------------------------------------------------------------------- 6b. skin only where skin can be
fc = np.zeros((npoly, 3))
np.add.at(fc, loop_poly, X[fverts])
fc /= C["ltotal"][:, None]
hand_mass = group_mass(descendants("hand_l") + descendants("hand_r"))
_loc, _nrm, _tri, _bary, _d = posed.nearest(fc)
near_hand = (_bary * hand_mass[posed.tris[_tri]]).sum(1) > 0.5
wrist_mass = group_mass([n for n in ("lowerarm_twist_01_l", "lowerarm_twist_01_r") if n in gi])
near_wrist = (_bary * wrist_mass[posed.tris[_tri]]).sum(1) > 0.3
near_hand = near_hand | (near_wrist & (mx > 0.4))
head_zone = np.zeros(npoly, bool)
if face is not None:
    _fl, _fn, _ft, _fb, _fd = face_surf.nearest(fc)
    head_zone = (fc[:, 2] > fco[:, 2].min() + 0.005) & (np.abs(_fd) < np.abs(_d))
dark = mx < float(args.get("clothing_max_value", 0.22))
if args.get("head_rule", "dark") == "skin":
    # "head_skin" {"hue_min", "hue_max", "max_sat"} narrows the window (2026-10-06, MissionCommander: crimson collar
    # tabs (hue ~5, sat ~0.75) and gold piping (hue ~40) beside the throat read as skin and were cut out); defaults
    # are the old rule
    HS = args.get("head_skin") or {}
    _h0, _h1 = float(HS.get("hue_min", 0.0)), float(HS.get("hue_max", 45.0))
    _hue_ok = ((hue >= _h0) & (hue < _h1)) | ((hue > 340) if _h0 <= 0.0 else np.zeros_like(hue, bool))
    head_skin = (mx > 0.15) & (sat > 0.08) & (sat < float(HS.get("max_sat", 0.8))) & _hue_ok & (r_col > b_col)
    skin_final = (skin_cand & near_hand) | (head_zone & head_skin)
else:
    skin_final = (skin_cand & near_hand) | (head_zone & ~dark)
if args.get("head_skin_min_island"):
    # the head's skin is one connected piece (face, neck, the throat in the collar's V); skin-coloured specks in the
    # head zone that are not part of it are trim (a collar tab's lighter edge, a button) and stay garment
    # (2026-10-06, MissionCommander); the value is a share of the largest head-skin piece's area
    _hs = skin_final & head_zone
    _lh = components(_hs, C)
    _ar = {L: area[_lh == L].sum() for L in np.unique(_lh[_lh >= 0])}
    if _ar:
        _amax = max(_ar.values())
        _back = np.isin(_lh, [L for L, a_ in _ar.items() if a_ < float(args["head_skin_min_island"]) * _amax])
        skin_final = skin_final & ~_back
        report["cut"]["head_skin_specks_kept_as_garment"] = int(_back.sum())
lab3 = components(~skin_final, C)
keep = np.zeros(npoly, bool)
gareas = {L: area[lab3 == L].sum() for L in np.unique(lab3[lab3 >= 0])}
gmax = max(gareas.values())
for L, a_ in gareas.items():
    if a_ > 0.01 * gmax:
        keep |= lab3 == L
report["cut"].update({"skin_faces_final": int(skin_final.sum()), "hand_faces": int((skin_cand & near_hand).sum()),
                      "head_zone_faces": int(head_zone.sum()), "garment_faces_final": int(keep.sum())})
log("cut refined by region: %d clothing faces" % keep.sum())

# ----------------------------------------------------------------------------------------------- 7. the garment cut out, cleaned, decimated
gar = seed.copy()
gar.data = seed.data.copy()
gar.name = gar.data.name = "SK_%s_%s" % (NAME, PART)
bpy.context.collection.objects.link(gar)
bm = bmesh.new()
bm.from_mesh(gar.data)
bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[i] for i in np.nonzero(~keep)[0]], context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
nb0 = len(bm.verts)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
report["welded_vertices"] = nb0 - len(bm.verts)
if face is not None:
    # the seed's throat in the chin's shadow is as dark as the leather, so the colour cut kept it: a thin shelf that
    # lay inside the MetaHuman's chin from one collar tip to the other, and the fit pushed it out as a crumpled plate
    # across the chin (2026-10-06). Garment faces inside the face mesh in front of the neck are not clothing.
    NA0 = np.array(bones["neck_01"].head_local)
    bm.verts.ensure_lookup_table()
    vco = np.array([v.co[:] for v in bm.verts])
    front = (vco[:, 1] < NA0[1] - 0.035) & (vco[:, 2] > NA0[2])
    inside = np.zeros(len(vco), bool)
    if front.any():
        _, _, _, _, dfc = face_surf.nearest(vco[front])
        inside[np.nonzero(front)[0][dfc < -0.002]] = True
    # an OPEN collar (Grinder's, Hart's lab coat, Ledger's and Mockingbird's open at the throat): nothing of the garment
    # stands in front of the throat above the under-layer's neckline. The band of the seed's shadowed throat ran there
    # from one collar tip to the other, through the MetaHuman's chin and mouth (the top view of 2026-10-06 showed the
    # collar ring closed across the front). A closed stand collar (Ace Vex, Dreck) sets "open_front": false.
    tc = args.get("open_front", True)
    if tc:
        half = float(tc.get("half_width_m", 0.045)) if isinstance(tc, dict) else 0.045
        inside |= (np.abs(vco[:, 0] - cx_body) < half) & (vco[:, 1] < NA0[1] - 0.03) & (vco[:, 2] > NA0[2] + 0.04)
    bm.faces.ensure_lookup_table()
    gone = [f for f in bm.faces if all(inside[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    report["throat_faces_removed"] = len(gone)
    log("faces in front of the throat / inside the jaw removed: %d" % len(gone))
# the cut's edges: spikes (faces with two open edges) and shards cut off, then each open loop smoothed along itself.
# v5 left jagged dark shards at the shirt's neckline beside the throat, in the comms portrait's framing (2026-10-06)
spikes = 0
for _ in range(4):
    ears = [f for f in bm.faces if sum(1 for e in f.edges if e.is_boundary) >= 2]
    if not ears:
        break
    spikes += len(ears)
    bmesh.ops.delete(bm, geom=ears, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bm.faces.ensure_lookup_table()
for f in bm.faces:
    f.tag = False
islands = []
for f0 in bm.faces:
    if f0.tag:
        continue
    stack, isl = [f0], []
    f0.tag = True
    while stack:
        f = stack.pop()
        isl.append(f)
        for e in f.edges:
            for g_ in e.link_faces:
                if not g_.tag:
                    g_.tag = True
                    stack.append(g_)
    islands.append(isl)
small_isl = [isl for isl in islands if sum(f.calc_area() for f in isl) < 0.0004]
bmesh.ops.delete(bm, geom=[f for isl in small_isl for f in isl], context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bverts = [v for v in bm.verts if v.is_boundary]
bnbr = {v: [e.other_vert(v) for e in v.link_edges if e.is_boundary] for v in bverts}
for _ in range(40):
    new = {v: v.co * 0.5 + (bnbr[v][0].co + bnbr[v][1].co) * 0.25 for v in bverts if len(bnbr[v]) == 2}
    for v, c_ in new.items():
        v.co = c_
ring = set()
for v in bverts:
    for e in v.link_edges:
        u = e.other_vert(v)
        if not u.is_boundary:
            ring.add(u)
for _ in range(4):
    new = {}
    for v in ring:
        nbs = [e.other_vert(v) for e in v.link_edges]
        new[v] = v.co * 0.5 + sum((u.co for u in nbs), Vector()) * (0.5 / len(nbs))
    for v, c_ in new.items():
        v.co = c_
report["cut_cleanup"] = {"spike_faces_removed": spikes, "islands_dropped": len(small_isl), "boundary_vertices_smoothed": len(bverts)}
log("cut cleaned: %s" % report["cut_cleanup"])
bm.to_mesh(gar.data)
bm.free()
bpy.data.objects.remove(seed, do_unlink=True)
tris0 = blib.tri_count(gar)
target_tris = int(args.get("decimate_to", 50000))
if target_tris and tris0 > target_tris:
    m = gar.modifiers.new("Decimate", "DECIMATE")
    m.ratio = target_tris / tris0
    if SYM in ("right", "left"):
        m.use_symmetry = True
        m.symmetry_axis = "X"
    blib.select_only([gar])
    bpy.ops.object.modifier_apply(modifier=m.name)
bm = bmesh.new()
bm.from_mesh(gar.data)
nd0 = len(bm.edges)
bmesh.ops.dissolve_degenerate(bm, dist=float(args.get("collapse_edges_under_m", 0.0022)),
                              edges=[e for e in bm.edges if min(e.verts[0].co.z, e.verts[1].co.z) > 0.17])   # not the boots: collapsed, they turned lumpy
bmesh.ops.dissolve_degenerate(bm, dist=0.0008, edges=bm.edges[:])
bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bm.to_mesh(gar.data)
bm.free()
log("garment: %d -> %d triangles (short edges collapsed: %d; slivers in the creases stretched most in the pose test)" % (tris0, blib.tri_count(gar), nd0 - len(gar.data.edges)))
gme = gar.data
G = coords(gme)
E = edges_of(gme)
nv = len(G)
gme.calc_loop_triangles()
gtris = np.empty(len(gme.loop_triangles) * 3, np.int64)
gme.loop_triangles.foreach_get("vertices", gtris)
gtris = gtris.reshape(-1, 3)

# ----------------------------------------------------------------------------------------------- 8. held between the clearance and the stand-off
zneck = float(bones["clavicle_l"].head_local.z) if "clavicle_l" in bones else 0.82 * H_body
zcrotch = float(bones["pelvis"].head_local.z) - 0.06 if "pelvis" in bones else 0.47 * H_body


def regions(P, nrm):
    """Each vertex's stand-off limit: the collar stands well off the neck, the soles are pressed under the feet."""
    lim = np.full(len(P), MAXOFF["jacket"])
    lim[P[:, 2] < zcrotch] = MAXOFF["legs"]
    lim[(P[:, 2] < 0.03) & (nrm[:, 2] < -0.3)] = MAXOFF["sole"]
    lim[P[:, 2] > zneck - 0.03] = MAXOFF["collar"]
    return lim


def nearest_both(P, surf, fsurf):
    """Nearest of the body and the neck: (location, normal, signed distance, from_face)."""
    loc, nrm, tri, bary, d = surf.nearest(P)
    if fsurf is None:
        return loc, nrm, d, np.zeros(len(P), bool)
    floc, fnrm, ftri, fbary, fd = fsurf.nearest(P)
    use = (np.abs(fd) < np.abs(d)) & (P[:, 2] > zneck - 0.05)
    loc[use], nrm[use], d[use] = floc[use], fnrm[use], fd[use]
    return loc, nrm, d, use


def body_wins(P, surf, fsurf, iters=4, reach=0.025):
    """Where a body vertex is left outside the garment (its outward ray misses the garment, its inward ray meets it
    within 3 cm), the garment round that spot is pushed out along the body's normal past it. The vertex test alone
    let the MetaHuman's forearm through a sleeve wall and its toes out under the boots' raised toe caps (2026-10-06).
    The bare feet's soles (under z 6 mm) are left out: the boots stand on the floor, the MetaHuman's soles 4 mm under it."""
    tri_l = [tuple(t) for t in gtris]
    pts = [(surf.co[surf.co[:, 2] > 0.006], surf.vn[surf.co[:, 2] > 0.006])]
    if fsurf is not None:
        low = fsurf.co[:, 2] < fsurf.co[:, 2].min() + 0.07
        pts.append((fsurf.co[low], fsurf.vn[low]))
    total = []
    for it_ in range(iters):
        bvh = BVHTree.FromPolygons([tuple(p_) for p_ in P], tri_l, all_triangles=True)
        kd = KDTree(len(P))
        for i_, p_ in enumerate(P):
            kd.insert(p_, i_)
        kd.balance()
        push = np.zeros_like(P)
        n_poke = 0
        for co_, vn_ in pts:
            for i_ in range(len(co_)):
                p_, n_ = Vector(co_[i_]), Vector(vn_[i_])
                if bvh.ray_cast(p_ + n_ * 1e-4, n_, 0.12)[0] is not None:
                    continue
                hit = bvh.ray_cast(p_ - n_ * 1e-4, -n_, 0.03)
                if hit[0] is None:
                    continue
                n_poke += 1
                need = hit[3] + CLEAR
                for (q_, j_, dq) in kd.find_range(hit[0], reach):
                    w_ = 1.0 - dq / reach
                    mv = np.array(n_) * need * w_
                    if np.dot(mv, mv) > np.dot(push[j_], push[j_]):
                        push[j_] = mv
        total.append(n_poke)
        if n_poke == 0:
            break
        push[FIXED] = 0
        sp = laplacian(push, E, nv, 2, 0.5)
        sp[FIXED] = 0
        P = P + sp
        P = P + push * 0.5
    return P, total


def sole_mask(P, nrm):
    """Boot soles at the floor: the clearance passes leave them where they are (z >= 0 is set at the end)."""
    return (P[:, 2] < 0.012) & (nrm[:, 2] < -0.5)


CLEARV = None                                   # per-vertex clearance for the final pass (zones), else CLEAR


def fit_rounds(P, surf, fsurf, rounds, pull=True, tag=""):
    """Push every vertex to the clearance and (pull) hold it within its stand-off; the moves are smoothed over the
    garment so a pushed panel moves as a panel; a last strict pass leaves no vertex inside the clearance."""
    stats = {}
    for k in range(rounds):
        loc, nrm, d, _ = nearest_both(P, surf, fsurf)
        lim = regions(P, nrm)
        if k == 0:
            stats["before"] = {"inside": int((d < 0).sum()), "under_clearance": int((d < CLEAR).sum()),
                               "over_standoff": int((d > lim).sum()), "min_mm": round(float(d.min()) * 1000, 1),
                               "median_mm": round(float(np.median(d)) * 1000, 1)}
        cl_ = CLEARV if CLEARV is not None and len(CLEARV) == len(P) else CLEAR
        tgt = np.clip(d, cl_, lim if pull else np.inf)
        so = sole_mask(P, nrm)
        tgt[so] = d[so]
        move = nrm * np.clip(tgt - d, -0.06, 0.06)[:, None]
        sm = laplacian(move, E, nv, 6, 0.5)
        need = np.maximum(tgt - d, 0)
        got = np.einsum("ij,ij->i", sm, nrm)
        sm += nrm * np.maximum(need - got, 0)[:, None]
        sm[so] = 0
        sm[FIXED] = 0
        P = P + sm
        moved = np.linalg.norm(sm, axis=1) > 0.002
        if moved.any():
            P = laplacian(P, E, nv, 1, 0.3, mask=moved)
    loc, nrm, d, _ = nearest_both(P, surf, fsurf)
    bad = (d < CLEAR) & ~sole_mask(P, nrm) & ~FIXED
    P[bad] += nrm[bad] * (CLEAR - d[bad])[:, None]
    P, stats["body_wins"] = body_wins(P, surf, fsurf)
    loc, nrm, d, _ = nearest_both(P, surf, fsurf)
    bad = (d < CLEAR) & ~sole_mask(P, nrm) & ~FIXED
    P[bad] += nrm[bad] * (CLEAR - d[bad])[:, None]
    loc, nrm, d, _ = nearest_both(P, surf, fsurf)
    lim = regions(P, nrm)
    stats["after"] = {"inside": int((d < 0).sum()), "inside_not_sole": int(((d < 0) & ~sole_mask(P, nrm)).sum()),
                      "under_clearance": int(((d < CLEAR - 1e-4) & ~sole_mask(P, nrm)).sum()),
                      "over_standoff": int((d > lim + 1e-3).sum()), "min_mm": round(float(d.min()) * 1000, 1),
                      "median_mm": round(float(np.median(d)) * 1000, 1), "max_mm": round(float(d.max()) * 1000, 1)}
    log("fit %s: %s" % (tag, stats))
    return P, stats


# the boots, as rigid pieces: v5/v6 pressed every boot vertex to the clearance, flattened the sole column by column,
# clamped it to the floor and smoothed it - the review saw lumpy, melted boots with the heel shaved off (2026-10-06).
# Each boot below BOOT_TOP is now moved as ONE piece: its toe spring flattened ahead of the ball only (the bare toes
# lie flat), scaled about its heel until the posed MetaHuman foot is inside it with no skin through it, its lowest point
# set on the floor (z = 0); a 5 cm band above blends into the trousers. Later passes leave the boot alone (FIXED).
def boot_push(cand, surf, fsel, core, rounds=4):
    """The boot (core) pushed out where the foot's skin (fsel) still comes through it: round each spot 4 cm wide,
    smoothed over the boot, so it swells as leather would instead of growing lumps."""
    hist = []
    for it_ in range(rounds):
        bvh_c = BVHTree.FromPolygons([tuple(p) for p in cand], [tuple(t) for t in gtris], all_triangles=True)
        cidx = np.nonzero(core)[0]
        kdb = KDTree(len(cidx))
        for k_, i in enumerate(cidx):
            kdb.insert(cand[i], k_)
        kdb.balance()
        push = np.zeros_like(cand)
        npk = 0
        for i in np.nonzero(fsel)[0]:
            p_, n_ = Vector(surf.co[i]), Vector(surf.vn[i])
            if p_.z < 0.006:                     # the bare sole is under the floor and under the boot's sole: not a poke
                continue                         # (pushed, it drove a sole vertex 28 mm down, 2026-10-06)
            if bvh_c.ray_cast(p_ + n_ * 1e-4, n_, 0.12)[0] is not None:
                continue
            hit = bvh_c.ray_cast(p_ - n_ * 1e-4, -n_, 0.02)
            if hit[0] is None:
                continue
            sh = surf.bvh.ray_cast(p_ - n_ * 2e-4, -n_, 0.02)
            if sh[0] is not None and sh[3] < hit[3]:
                continue
            npk += 1
            for (_, j_, dq) in kdb.find_range(hit[0], 0.04):
                mv = np.array(n_) * (hit[3] + 0.003) * (1 - dq / 0.04)
                if np.dot(mv, mv) > np.dot(push[cidx[j_]], push[cidx[j_]]):
                    push[cidx[j_]] = mv
        hist.append(["push", npk])
        if npk == 0:
            break
        push = laplacian(push, E, nv, 8, 0.5, mask=core)
        cand = cand + push * 1.3
    return cand, hist


BOOT_TOP = float(args.get("boot_top_m", 0.11))
FIXED = np.zeros(nv, bool)
# in the seed-matched pose the boots are only marked (FIXED: the fit passes leave them alone); they are set on the
# feet in the A-pose, after the inverse skinning (set in the matched pose, the leg's small pose-match turn tilted
# them 4 degrees on the way back: toes at -1 mm, heels at -18 mm, the toes and inner ankles through - 2026-10-06)
for sd in ("l", "r"):
    if "foot_" + sd in bones:
        sgn = 1 if bones["foot_" + sd].head_local.x > 0 else -1
        FIXED |= (np.sign(G[:, 0] - cx_body) == sgn) & (G[:, 2] < BOOT_TOP)


def place_boots(G, surf, fmass):
    """The boots set as rigid pieces on the feet of `surf` (see above); returns the new positions and the report."""
    global FIXED
    boot_report = {}
    for sd, fm in fmass.items():
        sgn = 1 if bones["foot_" + sd].head_local.x > 0 else -1
        side_v = np.sign(G[:, 0] - cx_body) == sgn
        core = side_v & (G[:, 2] < BOOT_TOP)
        band = side_v & (G[:, 2] < BOOT_TOP + 0.05)
        fsel = (fm > 0.5) & (surf.co[:, 2] < 0.12)
        fv = surf.co[fsel]
        if core.sum() < 50 or len(fv) < 50:
            continue
        B = G.copy()
        # the sole laid flat 4 mm under the MetaHuman's own bare sole (the template stands 3-6 mm into the floor; a sole at
        # z = 0 left the toe pads and the arch through it: 462 skin vertices, 2026-10-06), by the bottom profile along the
        # boot with a 3 cm falloff upward: the toe spring and the waist go, the upper keeps its shape
        cb = np.nonzero(core)[0]
        floor_t = float(fv[:, 2].min()) - float(args.get("sole_under_foot_m", 0.004))   # 1 mm let the lifted foot's sole graze through in a stride
        ed = np.linspace(B[cb, 1].min() - 1e-4, B[cb, 1].max() + 1e-4, 17)
        prof = np.full(16, np.nan)
        for k_ in range(16):
            mk_ = core & (B[:, 1] >= ed[k_]) & (B[:, 1] < ed[k_ + 1])
            if mk_.any():
                prof[k_] = B[mk_, 2].min()
        okp = ~np.isnan(prof)
        mids = (ed[:-1] + ed[1:]) / 2
        bottom = np.interp(B[:, 1], mids[okp], prof[okp])
        wz = np.clip(1 - (B[:, 2] - bottom) / 0.03, 0, 1)
        B[:, 2] = np.where(core, B[:, 2] - (bottom - floor_t) * wz, B[:, 2])
        m_side, m_end = 0.009, 0.012
        bx0, bx1 = B[cb, 0].min(), B[cb, 0].max()
        by0, by1 = B[cb, 1].min(), B[cb, 1].max()
        fx0, fx1, fy0, fy1 = fv[:, 0].min(), fv[:, 0].max(), fv[:, 1].min(), fv[:, 1].max()
        s = max(1.0, (fx1 - fx0 + 2 * m_side) / max(bx1 - bx0, 1e-3), (fy1 - fy0 + 2 * m_end) / max(by1 - by0, 1e-3))
        heel_f = fy1 + m_end
        tries = []
        for it_ in range(6):
            T_ = B.copy()
            T_[:, 0] = (fx0 + fx1) / 2 + (B[:, 0] - (bx0 + bx1) / 2) * s
            T_[:, 1] = heel_f + (B[:, 1] - by1) * s
            w = np.where(core, 1.0, np.where(band, smoothstep(BOOT_TOP + 0.05, BOOT_TOP, G[:, 2]), 0.0))
            cand = G * (1 - w[:, None]) + T_ * w[:, None]
            # the foot's skin through the boot's sides or top? then 2% wider and longer (the sole is already under it)
            bvh_c = BVHTree.FromPolygons([tuple(p) for p in cand], [tuple(t) for t in gtris], all_triangles=True)
            npk = 0
            for i in np.nonzero(fsel)[0]:
                p_, n_ = Vector(surf.co[i]), Vector(surf.vn[i])
                if bvh_c.ray_cast(p_ + n_ * 1e-4, n_, 0.12)[0] is not None:
                    continue
                hit = bvh_c.ray_cast(p_ - n_ * 1e-4, -n_, 0.02)
                if hit[0] is not None:
                    sh = surf.bvh.ray_cast(p_ - n_ * 2e-4, -n_, 0.02)
                    if sh[0] is None or sh[3] > hit[3]:
                        npk += 1
            tries.append([round(float(s), 4), npk])
            if npk == 0 or s * 1.02 > float(args.get("boot_max_scale", 1.15)):
                break
            s *= 1.02
        # what the scale leaves (the arch, the ankle bones): the boot pushed out round each spot, 4 cm wide and smoothed
        # over the boot, so it swells as leather would instead of growing lumps
        cand, pt_ = boot_push(cand, surf, fsel, core)
        tries.extend(pt_)
        G = cand
        FIXED |= core
        boot_report[sd] = {"scale": round(float(s), 4), "foot_len_mm": round(float(fy1 - fy0) * 1000), "boot_len_mm": round(float(by1 - by0) * 1000),
                           "sole_z_mm": round(floor_t * 1000, 1), "tries_scale_pokes": tries}
    report["boots"] = boot_report
    log("boots (rigid, on the floor): %s" % boot_report)
    return G, boot_report


G, st_posed = fit_rounds(G, posed, face_low, 6, pull=True, tag="on the posed body")
report["fit_posed"] = st_posed

# ----------------------------------------------------------------------------------------------- 9. regions and weights
GN = vertex_normals(G, gtris)
_l0, _n0, _t0, _b0, _d0 = posed.nearest(G)
if np.mean(np.einsum("ij,ij->i", G - _l0, GN) > 0) < 0.5:
    GN = -GN
    log("garment normals point inwards: flipped for the weight rays")
# each garment vertex takes its body point by a ray INTO the body along its own inward normal; the nearest point gave
# the jacket's side panel, 13 cm below the armpit, the upper arm's weights (60% upperarm twistCor) and the 30-degree
# arm raise pulled it out into a bat-wing (2026-10-06)
s_tri, s_loc = _t0.copy(), _l0.copy()
how = np.zeros(nv, np.int8)
for i in range(nv):
    hit = posed.bvh.ray_cast(Vector(G[i] - GN[i] * 1e-4), Vector(-GN[i]), 0.12)
    if hit[0] is not None and hit[3] < abs(_d0[i]) + 0.04:
        s_tri[i], s_loc[i], how[i] = hit[2], hit[0], 1
a_, b_, c_ = (posed.co[posed.tris[s_tri, k]] for k in range(3))
s_bary = barycentric(s_loc, a_, b_, c_)
Wg = (s_bary[:, :1] * W[posed.tris[s_tri, 0]] + s_bary[:, 1:2] * W[posed.tris[s_tri, 1]]
      + s_bary[:, 2:] * W[posed.tris[s_tri, 2]]).astype(np.float64)
LM = np.zeros((len(vg_names), len(LABELS)))
for j, n in enumerate(vg_names):
    LM[j, LABELS.index(BONE_LABEL.get(n, "torso"))] = 1
glab = np.argmax(Wg @ LM, 1)
off_, nbr_ = csr(E, nv)
for _ in range(3):
    cnt = np.zeros((nv, len(LABELS)))
    np.add.at(cnt, np.repeat(np.arange(nv), np.diff(off_)), np.eye(len(LABELS))[glab[nbr_]])
    cnt[np.arange(nv), glab] += 1
    newl = np.argmax(cnt, 1)
    flip = cnt[np.arange(nv), newl] > 0.6 * cnt.sum(1)
    glab = np.where(flip, newl, glab)
report["weight_sampling"] = {"by_ray": int(how.sum()), "by_nearest": int(nv - how.sum()),
                             "labels": {L: int((glab == i).sum()) for i, L in enumerate(LABELS)}}

# face regions: jacket / shirt / trousers / boots (material slots, roughness, detail normal), from the hems
gme.calc_loop_triangles()
f_ls = np.empty(len(gme.polygons), np.int64)
f_lt = np.empty(len(gme.polygons), np.int64)
gme.polygons.foreach_get("loop_start", f_ls)
gme.polygons.foreach_get("loop_total", f_lt)
f_lv = np.empty(len(gme.loops), np.int64)
gme.loops.foreach_get("vertex_index", f_lv)
nfac = len(gme.polygons)
f_of_loop = np.repeat(np.arange(nfac), f_lt)
fcen = np.zeros((nfac, 3))
np.add.at(fcen, f_of_loop, G[f_lv])
fcen /= f_lt[:, None]
fnrm = np.zeros((nfac, 3))
np.add.at(fnrm, f_of_loop, GN[f_lv])
fnrm /= np.maximum(np.linalg.norm(fnrm, axis=1, keepdims=True), 1e-9)
f_area = np.empty(nfac)
gme.polygons.foreach_get("area", f_area)
f_rgb, f_val, f_sat, f_hue, _, _ = face_colours(gme)
flab = np.zeros((nfac, len(LABELS)))
np.add.at(flab, f_of_loop, np.eye(len(LABELS))[glab[f_lv]])
f_arm = (flab[:, 1] + flab[:, 2]) > 0.5 * f_lt


def hem_z(sel, z0, z1):
    """The height of a hem: where the downward-facing area (the hem's underside) peaks between z0 and z1."""
    m = sel & (fnrm[:, 2] < -0.55) & (fcen[:, 2] > z0) & (fcen[:, 2] < z1)
    if m.sum() < 10:
        return None
    hist, ed = np.histogram(fcen[m, 2], bins=max(4, int((z1 - z0) / 0.01)), range=(z0, z1), weights=f_area[m])
    k = int(np.argmax(hist))
    zz = fcen[m, 2]
    near = np.abs(zz - (ed[k] + ed[k + 1]) / 2) < 0.012
    return float(np.average(zz[near], weights=f_area[m][near]))


pel_z = float(bones["pelvis"].head_local.z)
z_jhem = hem_z(~f_arm & (np.abs(fcen[:, 0] - cx_body) < 0.24), pel_z - 0.14, pel_z + 0.16) or pel_z
if args.get("jacket_hem_z_m"):
    # opt-in (2026-10-06, PilotDreck): the search above took the trousers' crotch underside (0.83 m, at the centre)
    # for the bomber's hem (1.025 m at the sides): the hips and upper thighs became "jacket" (leather roughness and
    # relief, a jagged shiny band across the trousers) and rode the torso. Read regions.jacket_hem_z in fit_report.json
    # against fit_front.png; set the hem's height here when it sits at the crotch. Default: the search alone.
    report["jacket_hem_z_found"] = round(float(z_jhem), 3)
    z_jhem = float(args["jacket_hem_z_m"])
z_thm = {}
for sd, sgn in (("l", 1), ("r", -1)):
    z_thm[sd] = hem_z(~f_arm & (np.sign(fcen[:, 0] - cx_body) == sgn), 0.06, 0.32) or 0.13
f_side = np.where(fcen[:, 0] > cx_body, "l", "r")
f_reg = np.zeros(nfac, np.int64)                                 # 0 jacket
below = ~f_arm & (fcen[:, 2] < z_jhem - 0.004)
f_reg[below] = 2                                                 # trousers
boot = below & (fcen[:, 2] < np.where(f_side == "l", z_thm["l"], z_thm["r"]) - 0.004)
f_reg[boot] = 3
# the under-layer in the jacket's V: dark and unsaturated against the leather, in front of the neck
NA = np.array(bones["neck_01"].head_local)
NU = np.array(bones["head"].head_local) - NA
NU /= np.linalg.norm(NU)
vreg = (f_reg == 0) & (np.abs(fcen[:, 0] - cx_body) < 0.11) & (fcen[:, 1] < NA[1] + 0.01) & (fcen[:, 2] > NA[2] - 0.24) & (fcen[:, 2] < NA[2] + 0.06)
shirt_max = float(args.get("shirt_max_value", 0.0)) or None
if vreg.sum() > 20:
    if shirt_max is None:
        vv = np.sort(f_val[vreg])
        lo_, hi_ = np.percentile(vv, 10), np.percentile(vv, 90)
        shirt_max = float(lo_ + 0.4 * (hi_ - lo_)) if hi_ - lo_ > 0.04 else float(lo_ - 1)
    shirt = vreg & (f_val < shirt_max) & (f_sat < 0.45)
    f_reg[shirt] = 1
# the regions cleaned by face adjacency (a lone face of another region inside a panel takes its neighbours')
for _ in range(2):
    le_ = np.empty(len(gme.loops), np.int64)
    gme.loops.foreach_get("edge_index", le_)
    o_ = np.argsort(le_, kind="stable")
    l2, f2 = le_[o_], f_of_loop[o_]
    same = l2[1:] == l2[:-1]
    fp = np.stack([f2[:-1][same], f2[1:][same]], 1)
    cnt = np.zeros((nfac, 4))
    np.add.at(cnt, fp[:, 0], np.eye(4)[f_reg[fp[:, 1]]])
    np.add.at(cnt, fp[:, 1], np.eye(4)[f_reg[fp[:, 0]]])
    nr = np.argmax(cnt, 1)
    flip = (cnt[np.arange(nfac), nr] >= 2) & (cnt[np.arange(nfac), f_reg] == 0)
    f_reg = np.where(flip, nr, f_reg)
report["regions"] = {"jacket_hem_z": round(z_jhem, 3), "trouser_hem_z": {k: round(v, 3) for k, v in z_thm.items()},
                     "shirt_max_value": None if shirt_max is None else round(shirt_max, 3),
                     "faces": {REGIONS[i]: int((f_reg == i).sum()) for i in range(4)}}
log("regions: %s" % report["regions"])
v_reg = np.zeros(nv, np.int64)
v_reg[f_lv] = f_reg[f_of_loop]                                    # last writer wins: fine for the weights' use
# the jacket (not its sleeves) rides the torso: a leg label there (the hip under the hem) is the torso's
jac_v = np.zeros(nv, bool)
jac_v[f_lv[np.isin(f_of_loop, np.nonzero(f_reg <= 1)[0])]] = True
glab = np.where(jac_v & (glab >= 3), 0, glab)

# sanitize by label: no arm bones on the torso, no leg bones on the arms or the jacket, helpers on torso panels
# moved onto their primary bone (the review: the collar rode upperarm_out/fwd/bck, 24 mm at a 15-degree raise)
col_lab = np.array([LABELS.index(BONE_LABEL.get(n, "torso")) for n in vg_names])
helper = np.array([not PRIMARY.match(n) for n in vg_names])
prim_col = np.array([gi.get(primary_of(n), gi[n]) for n in vg_names])
torso_v = glab == 0
Wt = Wg[torso_v]
Wt[:, (col_lab == 1) | (col_lab == 2) | (col_lab == 3) | (col_lab == 4)] = 0
for j in np.nonzero(helper)[0]:
    if col_lab[j] == 0 and prim_col[j] != j:
        Wt[:, prim_col[j]] += Wt[:, j]
        Wt[:, j] = 0
Wg[torso_v] = Wt
for li, bad in ((1, (3, 4)), (2, (3, 4)), (3, (1, 2)), (4, (1, 2))):
    m_ = glab == li
    Wg[np.ix_(m_, np.isin(col_lab, bad))] = 0
empty = Wg.sum(1) < 1e-6
if empty.any():
    # a vertex left with nothing takes the nearest body vertex's weights of its own label
    blab = np.argmax(W @ LM, 1)
    for li in np.unique(glab[empty]):
        cand = np.nonzero(blab == li)[0]
        if not len(cand):
            continue
        kd = KDTree(len(cand))
        for k_, bi_ in enumerate(cand):
            kd.insert(posed.co[bi_], k_)
        kd.balance()
        for i in np.nonzero(empty & (glab == li))[0]:
            Wg[i] = W[cand[kd.find(G[i])[1]]]
Wg /= np.maximum(Wg.sum(1, keepdims=True), 1e-9)
# smoothed over the whole garment first: neighbouring vertices whose rays met the body on two sides of a weight border
# (a pocket flap's top and underside, a seam) took weights 0.3-0.5 apart, and a spine bend pulled their edge 4x long
# (v6's first pose test, 2026-10-06; v5 smoothed globally, v6 had only the bands)
_ac = np.nonzero(Wg.max(0) > 1e-4)[0]
# (not the rigid boots: smoothed, they took thigh weight, and back in the A-pose they sat 18 mm lower than the feet
# that had been fitted into them - the walk's toes came through the toe caps)
Wg[:, _ac] = laplacian(Wg[:, _ac], E, nv, int(args.get("weight_smooth_iters", 12)), 0.5, mask=~FIXED)
Wg /= np.maximum(Wg.sum(1, keepdims=True), 1e-9)
# label bands: across every label border the weights blend over BAND each side (a harmonic fill), so the armpit, the
# crotch and the jacket's yoke stretch over a band instead of one row of triangles
bord = np.zeros(nv, bool)
diff = glab[E[:, 0]] != glab[E[:, 1]]
if float(args.get("skirt_thigh_share", 0) or 0) > 0:
    # with the skirt following the thighs (below), its hem's torso/leg border gets no band: banded, the trousers' top
    # 5 cm kept torso weight and the walk's thighs came through just under the hem (MissionCommander run 2)
    _low = (G[E[:, 0], 2] < pel_z - 0.03) & (G[E[:, 1], 2] < pel_z - 0.03)
    _tl = (glab[E[:, 0]] == 0) != (glab[E[:, 1]] == 0)
    _side = np.abs(G[E[:, 0], 0] - cx_body) > 0.05
    diff = diff & ~(_low & _tl & _side)
bord[E[diff].ravel()] = True
BAND = float(args.get("label_band_m", 0.055))
gdist = geodesic(bord, G, E, nv, BAND + 0.02)
band = gdist < BAND
sub = band.copy()
sub[E[:, 0][band[E[:, 1]]]] = True
sub[E[:, 1][band[E[:, 0]]]] = True
sidx = np.nonzero(sub)[0]
loc_of = -np.ones(nv, np.int64)
loc_of[sidx] = np.arange(len(sidx))
se = E[sub[E[:, 0]] & sub[E[:, 1]]]
se = loc_of[se]
acols = np.nonzero(Wg[sidx].max(0) > 1e-4)[0]
Ws = Wg[np.ix_(sidx, acols)]
Ws = laplacian(Ws, se, len(sidx), 200, 0.5, mask=band[sidx] & ~FIXED[sidx])
Wg[np.ix_(sidx, acols)] = Ws
report["label_bands"] = {"border_vertices": int(bord.sum()), "band_vertices": int(band.sum())}
# the two places linear skinning tears a garment: under the arms (a 30-degree raise stretched the armpit's small edges
# 4.3x) and between the legs (the walk pulled the trousers' fly 7x, left half on thigh_l, right half on thigh_r). Round
# each armpit the weights are smoothed further (8 cm); the crotch rides the pelvis, fading to the thighs 10 cm down
# and 8 cm out from the middle (the usual trouser weighting) - 2026-10-06
ZONES = {}
_ac = np.nonzero(Wg.max(0) > 1e-4)[0]
for sd in ("l", "r"):
    if "upperarm_" + sd in arm.pose.bones:
        h_ = np.array(arm.pose.bones["upperarm_" + sd].head)
        ZONES["armpit_" + sd] = h_ + np.array([0.0, 0.0, -0.12])
        m_ = np.linalg.norm(G - ZONES["armpit_" + sd], axis=1) < 0.08
        Wg[:, _ac] = laplacian(Wg[:, _ac], E, nv, 60, 0.5, mask=m_)
if "pelvis" in gi:
    # opt-in "crotch_half_width" [inner, outer] (m, default 0.035/0.085, unchanged): tried on PilotAceVex (2026-10-06,
    # [0.02, 0.05]) for the walk's lifted thigh coming through the front at z 0.80-0.90 (248 pokes); it did NOT help
    # (the pokes stayed, skirt_thigh_share .6 neither): the cause is elsewhere (PilotDreck shows the same, 431)
    _cw = args.get("crotch_half_width") or [0.035, 0.085]
    a_cr = smoothstep(pel_z - 0.20, pel_z - 0.09, G[:, 2]) * (1 - smoothstep(float(_cw[0]), float(_cw[1]), np.abs(G[:, 0] - cx_body)))
    a_cr *= (G[:, 2] < pel_z) & ~jac_v & (G[:, 1] < float(bones["pelvis"].head_local.y) + 0.03)   # the front and the inseam: the
    # seat behind follows the thighs (riding the pelvis there, the walk's backward thigh came through it: 15 pokes)
    e_p = np.zeros(Wg.shape[1])
    e_p[gi["pelvis"]] = 1.0
    Wg = (1 - a_cr)[:, None] * Wg + a_cr[:, None] * e_p
    # opt-in "crotch_smooth_half_width" (m, default 0.13, unchanged): the 40-iteration smoothing below spread the pelvis
    # weight over the thigh tops' fronts 6-12 cm from the middle (pelvis 0.43-0.59, thigh 0.27-0.55 on PilotDreck run 2)
    # and the walk's lifted thigh came through there (431 pokes); narrower keeps the thigh fronts on the thighs
    m_cr = (np.abs(G[:, 0] - cx_body) < float(args.get("crotch_smooth_half_width", 0.13))) & (G[:, 2] > pel_z - 0.28) & (G[:, 2] < pel_z + 0.02) & ~jac_v
    _ac = np.nonzero(Wg.max(0) > 1e-4)[0]
    Wg[:, _ac] = laplacian(Wg[:, _ac], E, nv, 40, 0.5, mask=m_cr)
    ZONES["crotch"] = np.array([cx_body, float(np.median(G[a_cr > 0.5, 1])) if (a_cr > 0.5).any() else 0.0, pel_z - 0.12])
report["weight_zones"] = {k: [round(float(x), 3) for x in v] for k, v in ZONES.items()}
Wbase = Wg / np.maximum(Wg.sum(1, keepdims=True), 1e-9)
SKIRT = float(args.get("skirt_thigh_share", 0) or 0)
if SKIRT > 0 and "thigh_l" in gi and "thigh_r" in gi:
    # a long tunic's skirt (to the crotch) rode the torso only and the walk's forward thigh came through its front
    # (MissionCommander run 1, 2026-10-06: 425 pokes): below the hip the skirt follows each thigh by a share growing to
    # SKIRT at the hem, half and half across the middle (6 cm blend), so the front and the seat move with the legs
    a_sk = SKIRT * smoothstep(pel_z - 0.03, pel_z - 0.15, G[:, 2]) * (jac_v & (glab == 0) & (np.abs(G[:, 0] - cx_body) < 0.25))  # not the cuffs
    s_l = smoothstep(cx_body - 0.03, cx_body + 0.03, G[:, 0])
    e_l = np.zeros(Wbase.shape[1])
    e_l[gi["thigh_l"]] = 1.0
    e_r = np.zeros(Wbase.shape[1])
    e_r[gi["thigh_r"]] = 1.0
    Wleg_ = s_l[:, None] * e_l + (1 - s_l)[:, None] * e_r
    Wbase = (1 - a_sk)[:, None] * Wbase + a_sk[:, None] * Wleg_
    report["skirt"] = {"share": SKIRT, "vertices": int((a_sk > 0.05).sum()), "pelvis_z": round(pel_z, 3)}
SHC = args.get("shoulder_clavicle")
if SHC:
    # the front of each shoulder rides the clavicle: torso panels there carried spine weight while the skin under them
    # follows the clavicle chain, and a 10-degree shrug brought the deltoid through below the shoulder boards
    # (MissionCommander run 2, 2026-10-06). {"share", "offset": [dx, dy, dz] from upperarm's head (x mirrored), "r0", "r1"}
    _sh = {}
    for sd, sg in (("l", 1.0), ("r", -1.0)):
        cb_ = "clavicle_" + sd
        if cb_ not in gi or "upperarm_" + sd not in arm.pose.bones:
            continue
        off_ = np.array(SHC.get("offset", [-0.018, -0.067, 0.071]), np.float64) * [sg, 1, 1]
        c_ = np.array(arm.pose.bones["upperarm_" + sd].head) + off_
        dd_ = np.linalg.norm(G - c_, axis=1)
        f_ = float(SHC.get("share", 0.85)) * (1 - smoothstep(float(SHC.get("r0", 0.06)), float(SHC.get("r1", 0.10)), dd_))
        f_ *= (glab == 0) & (np.sign(G[:, 0] - cx_body) == sg)
        keep_ = np.zeros(Wbase.shape[1], bool)
        keep_[gi[cb_]] = True
        keep_ |= np.isin(np.arange(Wbase.shape[1]), [gi[n] for n in descendants("upperarm_" + sd) if n in gi])
        moved_ = (Wbase[:, ~keep_].sum(1)) * f_
        Wbase[:, ~keep_] *= (1 - f_)[:, None]
        Wbase[:, gi[cb_]] += moved_
        _sh[sd] = {"centre": [round(float(x), 3) for x in c_], "vertices": int((f_ > 0.05).sum())}
    report["shoulder_clavicle"] = _sh


def collar_coords(P):
    """Height along the neck axis above neck_01's head, distance from the axis, the unit radial direction."""
    d = P - NA
    t = d @ NU
    rv = d - t[:, None] * NU
    rho = np.linalg.norm(rv, axis=1)
    return t, rho, rv / np.maximum(rho[:, None], 1e-9)


def collar_alpha(P):
    """1 on the collar (above the neck's base, round the neck; everything above neck_01's head), 0 on the shoulders
    and the chest, a 4 cm blend."""
    t, rho, _ = collar_coords(P)
    return smoothstep(-0.065, -0.025, t) * np.maximum(1 - smoothstep(0.085, 0.115, rho), smoothstep(-0.01, 0.02, t))


def collar_weights(P, Wb):
    """The collar rides the spine and the neck only: 100% spine_05 at its seam to 50/50 spine_05/neck_01 at the rim,
    blended into the panel weights below over 4 cm. v5 weighted it to the clavicles and the arm's corrective bones:
    a 15-degree arm raise moved it 24 mm and tore it open from ear to shoulder (independent check, 2026-10-06)."""
    t, rho, _ = collar_coords(P)
    al = collar_alpha(P)
    up = smoothstep(-0.02, 0.12, t)
    Cw = np.zeros_like(Wb)
    tot_n = 0
    for bn, share in COLLAR_NECK.items():
        Cw[:, gi[bn]] = share * up
        tot_n = tot_n + share * up
    Cw[:, gi["spine_05"]] = 1 - tot_n
    out = (1 - al)[:, None] * Wb + al[:, None] * Cw
    return out, al


def top8(Wd):
    """At most 8 influences, normalised (Unreal keeps 8 by default)."""
    top = np.argsort(-Wd, axis=1)[:, :8]
    Wk = np.take_along_axis(Wd, top, 1)
    Wk[Wk < 0.01] = 0
    Wk[Wk.sum(1) == 0, 0] = 1.0
    Wk /= np.maximum(Wk.sum(1, keepdims=True), 1e-9)
    out = np.zeros_like(Wd)
    np.put_along_axis(out, top, Wk, 1)
    return out


Wg, alpha = collar_weights(G, Wbase)
Wg = top8(Wg)
report["weights"] = {"from": "the posed MetaHuman body by inward rays (nearest point where none), labels cleaned, arm/leg bones "
                             "kept off the torso, helpers moved to their primary bone on torso panels, 4 cm label bands, "
                             "collar on spine_05/neck_01 only", "collar_vertices": int((alpha > 0.5).sum())}

# ----------------------------------------------------------------------------------------------- 10. back to the A-pose
VGI = np.array([BI.get(n, 0) for n in vg_names])
A = POSED_S[VGI]
M = np.einsum("ng,gij->nij", Wg, A)
Gh = np.concatenate([G, np.ones((nv, 1))], 1)
G = np.einsum("nij,nj->ni", np.linalg.inv(M), Gh)[:, :3]
reset_pose()
G, report["boots"] = place_boots(G, rest, {sd: group_mass(descendants("foot_" + sd)) for sd in ("l", "r") if "foot_" + sd in bones})
log("boots (rigid, set on the A-pose feet): %s" % report["boots"])
G, st_rest = fit_rounds(G, rest, face_low, 3, pull=False, tag="on the A-pose body")
report["fit_rest"] = st_rest


def sparse_w(Wd):
    """(idx into NAMES_ALL, weights) of the 8 strongest groups of a dense weight matrix."""
    top = np.argsort(-Wd, axis=1)[:, :8]
    return VGI[top], np.take_along_axis(Wd, top, 1)


# ----------------------------------------------------------------------------------------------- 11. the collar
if DEBUG:
    np.savez_compressed(os.path.join(OUT, "dbg_pre_collar.npz"), G=G, gtris=gtris, E=E, Wbase=Wbase.astype(np.float32),
                        v_reg=v_reg, jac_v=jac_v, vg_names=np.array(vg_names), NA=NA, NU=NU, rest_co=rest.co, rest_tris=rest.tris)
    if args.get("stop_after") == "pre_collar":
        log("debug: stopped before the collar")
        sys.exit(0)


def drop_faces(fmask):
    """Delete garment faces after the fit (their vertices' final places known), every per-vertex and per-face array
    re-indexed; loose vertices go too."""
    global G, Wbase, v_reg, jac_v, FIXED, E, gtris, nv, f_reg, f_rgb, f_area, f_ls, f_lt, f_lv, f_of_loop, nfac
    bm_ = bmesh.new()
    bm_.from_mesh(gme)
    lv_ = bm_.verts.layers.int.new("ms_v")
    lf_ = bm_.faces.layers.int.new("ms_f")
    bm_.verts.ensure_lookup_table()
    bm_.faces.ensure_lookup_table()
    for v in bm_.verts:
        v[lv_] = v.index
        v.co = G[v.index]
    for f in bm_.faces:
        f[lf_] = f.index
    bmesh.ops.delete(bm_, geom=[bm_.faces[i] for i in np.nonzero(fmask)[0]], context="FACES")
    bmesh.ops.delete(bm_, geom=[v for v in bm_.verts if not v.link_faces], context="VERTS")
    bm_.verts.index_update()
    bm_.faces.index_update()
    vmap = np.array([v[lv_] for v in bm_.verts])
    fmap = np.array([f[lf_] for f in bm_.faces])
    bm_.verts.layers.int.remove(lv_)
    bm_.faces.layers.int.remove(lf_)
    bm_.to_mesh(gme)
    bm_.free()
    G, Wbase, v_reg, jac_v, FIXED = G[vmap], Wbase[vmap], v_reg[vmap], jac_v[vmap], FIXED[vmap]
    f_reg, f_rgb = f_reg[fmap], f_rgb[fmap]
    E = edges_of(gme)
    nv = len(G)
    gme.calc_loop_triangles()
    t_ = np.empty(len(gme.loop_triangles) * 3, np.int64)
    gme.loop_triangles.foreach_get("vertices", t_)
    gtris = t_.reshape(-1, 3)
    nfac = len(gme.polygons)
    f_ls = np.empty(nfac, np.int64)
    f_lt = np.empty(nfac, np.int64)
    gme.polygons.foreach_get("loop_start", f_ls)
    gme.polygons.foreach_get("loop_total", f_lt)
    f_lv = np.empty(len(gme.loops), np.int64)
    gme.loops.foreach_get("vertex_index", f_lv)
    f_of_loop = np.repeat(np.arange(nfac), f_lt)
    f_area = np.empty(nfac)
    gme.polygons.foreach_get("area", f_area)
    return int(fmask.sum())


# what is left of the seed's cap over the neck hole after the fit (its frame moved with the collar): big flat faces
# within 6 cm of the neck axis, well above the neck's base
_c = G[gtris].mean(1)
_t, _r, _ = collar_coords(_c)
_e = np.stack([np.linalg.norm(G[gtris[:, k]] - G[gtris[:, (k + 1) % 3]], axis=1) for k in range(3)], 1).max(1)
# gtris rows are the triangulated faces in polygon order (all faces are triangles here)
_lid = (_t > 0.04) & (_r < 0.06) & (_e > 0.02)
if _lid.any() and len(gtris) == len(gme.polygons):
    report["neck_lid_faces_removed_after_fit"] = drop_faces(_lid)
    log("cap faces over the neck hole removed after the fit: %d" % report["neck_lid_faces_removed_after_fit"])
    # the open edge the lid leaves (the collar's inner top edge) cleaned like the cut's: spikes off, the loop smoothed
    # along itself (left jagged, it read as teeth behind the neck in the back views, 2026-10-06)
    for _ in range(2):
        cnt_b = np.zeros(nfac, np.int64)
        ef_ = np.empty(len(gme.loops), np.int64)
        gme.loops.foreach_get("edge_index", ef_)
        uses = np.bincount(ef_, minlength=len(gme.edges))
        np.add.at(cnt_b, f_of_loop, (uses[ef_] == 1).astype(np.int64))
        if (cnt_b >= 2).any():
            drop_faces(cnt_b >= 2)
    ef_ = np.empty(len(gme.loops), np.int64)
    gme.loops.foreach_get("edge_index", ef_)
    uses = np.bincount(ef_, minlength=len(gme.edges))
    be_ = E[uses == 1]
    bnd = np.zeros(nv, bool)
    bnd[be_.ravel()] = True
    near_lid = np.zeros(nv, bool)
    near_lid[bnd] = collar_alpha(G[bnd]) > 0.5
    for _ in range(30):
        acc = np.zeros_like(G)
        cnt_ = np.zeros(nv)
        np.add.at(acc, be_[:, 0], G[be_[:, 1]])
        np.add.at(acc, be_[:, 1], G[be_[:, 0]])
        np.add.at(cnt_, be_.ravel(), 1)
        m_ = near_lid & (cnt_ == 2)
        G[m_] = 0.5 * G[m_] + 0.5 * acc[m_] / 2
jac_collar = (collar_alpha(G) > 0.3) & (v_reg != 1)
neckline = (collar_alpha(G) > 0.3) & (v_reg == 1)
col_rep = {}
lobes = [np.array(e["lobe"]) for e in EARS.values()]
low = face_low
T_SEAM = -0.035                                            # the collar's seam, along the neck axis from neck_01's head
FLARE = float(args.get("collar_flare_m", 0.008))
MAX_PUSH = float(args.get("collar_max_push_m", 0.015))
_E1 = np.array([1.0, 0.0, 0.0]) - NU[0] * NU
_E1 /= np.linalg.norm(_E1)
_E2 = np.cross(NU, _E1)


def collar_frame(P):
    """Height along the neck axis above the collar's seam, distance from the axis, angle round it, radial direction."""
    t, rho, rdir = collar_coords(P)
    return t - T_SEAM, rho, np.arctan2(rdir @ _E2, rdir @ _E1), rdir


def lower_collar(P, kv, mask):
    """Squeeze the collar down about its seam (each vertex's height above the seam times kv): its shape and thickness
    kept, the rim lower; nothing is pushed sideways, so nothing crumples."""
    h, _, _, _ = collar_frame(P)
    w = np.clip(collar_alpha(P) / 0.6, 0, 1) * mask * (h > 0)
    return P - NU * (h * (1 - kv) * w)[:, None]


def grow_push(need, idx, P, reach=0.025):
    """Each push spread to the collar round it (the largest within reach, fading): the collar moves as a piece."""
    kd = KDTree(len(idx))
    for k_, i in enumerate(idx):
        kd.insert(P[i], k_)
    kd.balance()
    g = need.copy()
    for k_, i in enumerate(idx):
        if need[k_] > 0:
            for (_, j_, dq) in kd.find_range(P[i], reach):
                g[j_] = max(g[j_], need[k_] * (1 - dq / reach))
    return g


def radial_push(P, idx, amount, mask):
    """Out from the neck axis by amount (smoothed over mask, never less than asked): pushes from different head
    poses all point the same way, so they cannot fight (v6's first try pushed along the face normals in each pose and
    crumpled the tips across the chin)."""
    _, _, _, rdir = collar_frame(P[idx])
    disp = np.zeros_like(P)
    disp[idx] = rdir * amount[:, None]
    disp = laplacian(disp, E, nv, 6, 0.5, mask=mask)
    got = np.einsum("ij,ij->i", disp[idx], rdir)
    disp[idx] += rdir * np.maximum(amount - got, 0)[:, None]
    return P + disp


if lobes and jac_collar.any():
    # the rear rim under the ear lobes (v5 cut them: 224 face vertices at rest): the collar behind the ears is
    # squeezed down about its seam until its rim is EAR_GAP under the lower lobe
    z_lobe = min(float(l_[2]) for l_ in lobes)
    y_ear = float(np.mean([l_[1] for l_ in lobes]))
    h, _, _, _ = collar_frame(G)
    rear = jac_collar & (G[:, 1] > y_ear - 0.03) & (h > 0)
    if rear.any():
        z_rim = float(G[rear, 2].max())
        h_rim = float(h[rear].max())
        want_h = h_rim - (z_rim - (z_lobe - EAR_GAP)) / max(NU[2], 0.5)
        if z_rim > z_lobe - EAR_GAP and want_h > 0:
            wy = smoothstep(y_ear - 0.05, y_ear - 0.01, G[:, 1])
            G = lower_collar(G, 1 - (1 - want_h / h_rim) * wy, jac_collar)
        col_rep["ear_lobe_z"] = round(z_lobe, 4)
        col_rep["rear_rim_before_z"] = round(z_rim, 4)
        col_rep["rear_rim_after_z"] = round(float(G[rear, 2].max()), 4)
if low is not None and jac_collar.any():
    # the collar off the neck and jaw at rest: COLLAR_CLEAR at its seam, FLARE more at its rim (v5: 5 mm, the jaw met
    # its tips in a talking turn), out from the neck axis as a whole collar
    h, _, _, _ = collar_frame(G)
    hmax = float(h[jac_collar].max())
    for it_ in range(6):
        idxc = np.nonzero(jac_collar)[0]
        _, _, _, _, dl = low.nearest(G[idxc])
        hh, _, _, _ = collar_frame(G[idxc])
        need = np.maximum(COLLAR_CLEAR + FLARE * smoothstep(0.25 * hmax, hmax, hh) - dl, 0)
        if it_ == 0:
            col_rep["neck_clearance_before_mm"] = {"min": round(float(dl.min()) * 1000, 1), "p05": round(float(np.percentile(dl, 5)) * 1000, 1)}
        if need.max() < 5e-4:
            break
        G = radial_push(G, idxc, grow_push(need, idxc, G), jac_collar | (collar_alpha(G) > 0.05))
    idxc = np.nonzero(jac_collar)[0]
    _, _, _, _, dl = low.nearest(G[idxc])
    col_rep["neck_clearance_after_mm"] = {"min": round(float(dl.min()) * 1000, 1), "p05": round(float(np.percentile(dl, 5)) * 1000, 1)}
    # the head poses (+-40 deg yaw, +-15 deg nod and between): the collar skinned (spine_05 -> neck_01/neck_02) and
    # the face too; wherever the jaw, chin or neck comes within POSE_CLEAR of the collar, or a face vertex is truly
    # through it (the garment inside the skin's own thickness: a ray from a thin ear lobe that leaves the lobe and
    # then meets the collar is not a poke), the collar there is pushed out radially, at most MAX_PUSH; beyond that its
    # sector (10 degrees round the neck) is lowered about its seam instead
    fidx, fw = face_skin
    fz = fco[:, 2] < (Z_LOW + 0.05)
    dist_tris = face_surf.tris[(fz & ~EAR_V)[face_surf.tris].all(1)]
    tri_l = [tuple(t) for t in gtris]
    ftri_l = [tuple(t) for t in face_surf.tris]
    NSEC = 36
    cen = -math.pi + (np.arange(NSEC) + 0.5) * (2 * math.pi / NSEC)
    h0, _, th0, _ = collar_frame(G)
    sec0 = ((th0 + math.pi) / (2 * math.pi) * NSEC).astype(int) % NSEC
    hmax0 = np.array([h0[jac_collar & (sec0 == s) & (h0 > 0)].max() if (jac_collar & (sec0 == s) & (h0 > 0)).any() else 0.0
                      for s in range(NSEC)])
    floor_k = float(args.get("collar_min_height", 0.5))
    pushed = np.zeros(nv)
    pose_hist = []

    def head_check(P, poses):
        """Per pose: collar vertices too close to the face (or by a true poke), and how far each must go."""
        Wd, _ = collar_weights(P, Wbase)
        gidx, gw8 = sparse_w(top8(Wd))
        zone = collar_alpha(P) > 0.15
        iz = np.nonzero(zone)[0]
        need_all = np.zeros(nv)
        rec = {}
        for pname in poses:
            pose_steps(HEAD_POSES.get(pname, []))
            S = skin_mats()
            Pg, _ = lbs(P, gidx, gw8, S)
            Pf, _ = lbs(fco, fidx, fw, S)
            fs = Surface(co=Pf, tris=dist_tris)
            _, _, _, _, d_ = fs.nearest(Pg[iz])
            need = np.zeros(nv)
            need[iz] = np.maximum(POSE_CLEAR - d_, 0)
            gb = BVHTree.FromPolygons([tuple(p) for p in Pg], tri_l, all_triangles=True)
            fb = BVHTree.FromPolygons([tuple(p) for p in Pf], ftri_l, all_triangles=True)
            fvn = vertex_normals(Pf, face_surf.tris)
            kdz = KDTree(len(iz))
            for k_, i in enumerate(iz):
                kdz.insert(Pg[i], k_)
            kdz.balance()
            npk = 0
            for i in np.nonzero(fz)[0]:
                p_, n_ = Vector(Pf[i]), Vector(fvn[i])
                if gb.ray_cast(p_ + n_ * 1e-4, n_, 0.12)[0] is not None:
                    continue
                hit = gb.ray_cast(p_ - n_ * 1e-4, -n_, 0.03)
                if hit[0] is None:
                    continue
                sh = fb.ray_cast(p_ - n_ * 2e-4, -n_, 0.03)
                if sh[0] is not None and sh[3] < hit[3]:
                    continue
                npk += 1
                for (_, j_, dq) in kdz.find_range(hit[0], 0.02):
                    need[iz[j_]] = max(need[iz[j_]], hit[3] + POSE_CLEAR)
            rec[pname] = {"collar_vertices_too_close": int((need > 0).sum()), "face_pokes": npk, "min_mm": round(float(d_.min()) * 1000, 1)}
            need_all = np.maximum(need_all, need)
        reset_pose()
        return rec, need_all

    for rnd in range(6):
        rec, need = head_check(G, list(HEAD_POSES))
        pose_hist.append(rec)
        if not need.any():
            break
        pushable = (need > 0) & ((pushed < MAX_PUSH) | neckline)
        lowerable = (need > 0) & ~pushable & jac_collar
        idx_p = np.nonzero(pushable)[0]
        if len(idx_p):
            allz = np.nonzero(collar_alpha(G) > 0.15)[0]
            full = np.zeros(nv)
            full[idx_p] = np.minimum(need[idx_p] * 1.2, MAX_PUSH - pushed[idx_p] + 0.002)
            before_ = G.copy()
            G = radial_push(G, allz, grow_push(full[allz], allz, G), collar_alpha(G) > 0.05)
            _, _, _, rd = collar_frame(before_)
            pushed += np.maximum(np.einsum("ij,ij->i", G - before_, rd), 0)
        if lowerable.any():
            h, _, th, _ = collar_frame(G)
            sec = ((th + math.pi) / (2 * math.pi) * NSEC).astype(int) % NSEC
            ks = np.ones(NSEC)
            for s in np.unique(sec[lowerable]):
                m_s = jac_collar & (sec == s) & (h > 0)
                hm = float(h[m_s].max()) if m_s.any() else 0.0
                if hm <= 1e-3:
                    continue
                hl = float(h[lowerable & (sec == s)].min()) - 0.006
                ks[s] = max(floor_k * hmax0[s] / hm, min(1.0, hl / hm))
            ks = np.minimum.reduce([ks, 0.5 + 0.5 * np.roll(ks, 1), 0.5 + 0.5 * np.roll(ks, -1)])
            G = lower_collar(G, np.interp(th, cen, ks, period=2 * math.pi), jac_collar)
    rec, need = head_check(G, ["rest"] + list(HEAD_POSES))
    pose_hist.append(rec)
    h, _, th, _ = collar_frame(G)
    secf = ((th + math.pi) / (2 * math.pi) * NSEC).astype(int) % NSEC
    hfin = np.array([h[jac_collar & (secf == s) & (h > 0)].max() if (jac_collar & (secf == s) & (h > 0)).any() else 0.0 for s in range(NSEC)])
    col_rep["height_kept_by_sector"] = [round(float(a / b), 2) if b > 1e-3 else None for a, b in zip(hfin, hmax0)]
    col_rep["max_push_mm"] = round(float(pushed.max()) * 1000, 1)
    col_rep["head_poses"] = pose_hist
    col_rep["final"] = rec
    log("collar: %s" % {k: v for k, v in col_rep.items() if k != "head_poses"})
    log("collar in the head poses (per round): %s" % pose_hist)
report["collar"] = col_rep

# ----------------------------------------------------------------------------------------------- 12. hems, boots, final clearance, floor
# v5's trouser hems were crumpled into jagged folds and the boots lumpy (the review's feet close-up): a Taubin smoothing
# there (no shrinking), then the clearance passes again and every vertex at or above the floor
legs_low = (G[:, 2] < 0.30) & ~jac_v
hem_band = legs_low & (G[:, 2] > 0.06) & ~FIXED
G = taubin(G, E, nv, 12, hem_band)
if FIXED.any():
    # the boots once more against the A-pose feet: the push above was in the seed-matched pose, and the ankle bones
    # came 0.2-3.5 mm through the boots' inner sides at rest (2026-10-06)
    _fsel = (group_mass(descendants("foot_l") + descendants("foot_r") + descendants("calf_l") + descendants("calf_r")) > 0.5) & (rest.co[:, 2] < BOOT_TOP + 0.04)
    G, report["boots_rest_push"] = boot_push(G, rest, _fsel, FIXED)
    log("boots against the A-pose feet: %s" % report["boots_rest_push"])
# the zones where an arm or a leg moves into the garment (the armpits' backs when the arms come down, the glutes
# under the jacket's hem in a stride) get a 9 mm clearance instead of 5 for the last pass
CLEARV = np.full(nv, CLEAR)
for sd in ("l", "r"):
    if "upperarm_" + sd in bones:
        u_ = np.array(bones["upperarm_" + sd].head_local)
        c_ = u_ + np.array([0.0, 0.0, -0.12])
        CLEARV[np.linalg.norm(G - c_, axis=1) < 0.09] = float(args.get("zone_clearance_m", 0.009))
        # the trapezius behind the collar's base: the arms coming down lift its skin into the yoke
        tr_ = 0.25 * np.array(bones["neck_01"].head_local) + 0.75 * u_ + np.array([0.0, 0.045, 0.045])
        CLEARV[np.linalg.norm(G - tr_, axis=1) < 0.06] = float(args.get("zone_clearance_m", 0.009))
for sd, sg in (("l", 1), ("r", -1)):
    glute = (np.sign(G[:, 0] - cx_body) == sg) & (G[:, 1] > float(bones["pelvis"].head_local.y)) & (np.abs(G[:, 2] - (pel_z + 0.09)) < 0.06)
    CLEARV[glute] = float(args.get("zone_clearance_m", 0.009))
    if args.get("hip_front_clearance_m"):
        # opt-in (PilotDreck 2026-10-06): the trousers' front over each thigh's top stands this far off the skin, room for
        # the walk's lifted thigh (slim flight trousers: the thigh came through at the groin's front)
        _ax = np.abs(G[:, 0] - cx_body)
        hipf = (np.sign(G[:, 0] - cx_body) == sg) & (_ax > 0.025) & (_ax < 0.17) & ~jac_v & \
               (G[:, 1] < float(bones["pelvis"].head_local.y) - 0.02) & (G[:, 2] > pel_z - 0.22) & (G[:, 2] < pel_z + 0.03)
        CLEARV[hipf] = np.maximum(CLEARV[hipf], float(args["hip_front_clearance_m"]))
        report.setdefault("hip_front_clearance", {})[sd] = int(hipf.sum())
G, st_final = fit_rounds(G, rest, face_low, 2, pull=False, tag="final, on the A-pose body")
report["fit_final"] = st_final
under = (G[:, 2] < 0) & ~FIXED
report["floor"] = {"non_boot_vertices_below_0": int(under.sum()), "boot_sole_mm": round(float(G[FIXED, 2].min()) * 1000, 2) if FIXED.any() else None,
                   "boot_sole_p01_mm": round(float(np.percentile(G[FIXED, 2], 1)) * 1000, 2) if FIXED.any() else None,
                   "boot_vertices_below_minus_1mm_of_sole": int((FIXED & (G[:, 2] < G[FIXED, 2].min() + 0.001)).sum()) if FIXED.any() else 0}
G[~FIXED, 2] = np.maximum(G[~FIXED, 2], 0.0)
set_coords(gme, G)
Wg, alpha = collar_weights(G, Wbase)
Wg = top8(Wg)
used = np.nonzero(Wg.max(0) > 0)[0]
report["weights"].update({"groups": int(len(used)), "max_influences": int((Wg > 0).sum(1).max())})

# ----------------------------------------------------------------------------------------------- 13. checks at rest
gsurf = Surface(gar, depsgraph=False)


def pokes(co_, vn_, self_bvh, step=1, zmin=0.006):
    """Vertices of a skin outside the garment where the garment should cover them: the outward ray misses it within 12
    cm while the inward ray meets it within 2 cm AND inside the skin's own thickness (a ray from a thin ear lobe leaves
    the lobe and may then meet the collar below: not a poke)."""
    n_p = n_c = 0
    for i in range(0, len(co_), step):
        if co_[i, 2] < zmin:
            continue
        p, n = Vector(co_[i]), Vector(vn_[i])
        if gsurf.bvh.ray_cast(p + n * 1e-4, n, 0.12)[0] is not None:
            n_c += 1
            continue
        hit = gsurf.bvh.ray_cast(p - n * 1e-4, -n, 0.02)
        if hit[0] is None:
            continue
        sh = self_bvh.ray_cast(p - n * 2e-4, -n, 0.02)
        if sh[0] is not None and sh[3] < hit[3]:
            continue
        n_p += 1
    return n_p, n_c


bp_, bc_ = pokes(rest.co, rest.vn, rest.bvh, 2)
fp_, fc_ = pokes(fco, face_surf.vn, face_surf.bvh, 1) if face is not None else (0, 0)
report["poke_through"] = {"body_vertices_poking": bp_, "body_vertices_covered": bc_, "face_vertices_poking": fp_,
                          "face_vertices_covered": fc_, "body_step": 2,
                          "why": "a skin vertex whose outward ray misses the garment while its inward ray meets it within 2 cm"}
if low is not None and jac_collar.any():
    idxc = np.nonzero(jac_collar)[0]
    _, _, _, _, dl = low.nearest(G[idxc])
    report["collar"]["final_neck_clearance_mm"] = {"min": round(float(dl.min()) * 1000, 1), "p05": round(float(np.percentile(dl, 5)) * 1000, 1)}
log("poke-through at rest: %s" % report["poke_through"])

# ----------------------------------------------------------------------------------------------- 14. weights onto the mesh
for vg in list(gar.vertex_groups):
    gar.vertex_groups.remove(vg)
for gidx_ in used:
    vg = gar.vertex_groups.new(name=vg_names[gidx_])
    nz = np.nonzero(Wg[:, gidx_])[0]
    for v in nz:
        vg.add([int(v)], float(Wg[v, gidx_]), "REPLACE")

# ----------------------------------------------------------------------------------------------- 15. textures
# the seed's atlas cleaned (garment_tex.py: chroma speckle smoothed, pale flecks out, highlights compressed in luma),
# then baked onto the garment's own repacked UVs (v5 spent ~15% of the atlas on the cut-away head and hands); the
# collar's inner band (the seed painted neck skin there) filled with the collar's own leather; roughness per region
# (jacket leather ~0.5, shirt and trousers cloth, boots polished) and a tangent-space detail normal (leather grain,
# twill) baked from procedural relief
size = int(args.get("texture_size", 4096))
src_png = os.path.join(OUT, "_seed_bc.png")
cln_png = os.path.join(OUT, "_seed_bc_clean.png")
tmp = bc_img.copy()
if tmp.size[0] != size:
    tmp.scale(size, size)
tmp.filepath_raw = src_png
tmp.file_format = "PNG"
tmp.save()
bpy.data.images.remove(tmp)
venv_py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
tex_extra = [str(x) for x in (args.get("tex_args") or [])]          # garment_tex.py options (2026-10-06: trim kept)
acc_png = os.path.join(OUT, "_seed_accent.png")
MET = args.get("metal_accents")                                      # {"roughness", "metallic", "hue", "min_sat", "min_val"}
if MET:
    tex_extra += ["--accent_mask", acc_png]
    for k_, f_ in (("hue", "--accent_hue"), ("min_sat", "--accent_min_sat"), ("min_val", "--accent_min_val")):
        if k_ in MET:
            tex_extra += [f_] + [str(x) for x in (MET[k_] if isinstance(MET[k_], list) else [MET[k_]])]
r_ = subprocess.run([venv_py, os.path.join(HERE, "garment_tex.py"), src_png, cln_png, "--mode", args.get("texture_mode", "dark")] + tex_extra,
                    capture_output=True, text=True)
if r_.returncode != 0:
    raise RuntimeError("garment_tex.py failed: %s" % r_.stderr[-2000:])
report["texture_clean"] = json.loads(r_.stdout.strip().splitlines()[-1])
log("atlas cleaned: %s" % report["texture_clean"])
clean_img = bpy.data.images.load(cln_png)
clean_img.colorspace_settings.name = "sRGB"

# per-face bake attributes: region, lining fill, roughness base
fcen = np.zeros((nfac, 3))
np.add.at(fcen, f_of_loop, G[f_lv])
fcen /= f_lt[:, None]
GN = vertex_normals(G, gtris)
if np.mean(np.einsum("ij,ij->i", G - rest.nearest(G)[0], GN) > 0) < 0.5:
    GN = -GN
fnrm = np.zeros((nfac, 3))
np.add.at(fnrm, f_of_loop, GN[f_lv])
fnrm /= np.maximum(np.linalg.norm(fnrm, axis=1, keepdims=True), 1e-9)
t_c, rho_c, rdir_c = collar_coords(fcen)
f_alpha = collar_alpha(fcen)
inner = (f_reg == 0) & (f_alpha > 0.4) & (t_c > -0.04) & (np.einsum("ij,ij->i", fnrm, -rdir_c) > 0.3)
outer_col = (f_reg == 0) & (f_alpha > 0.5) & ~inner
fill_rgb = np.median(f_rgb[outer_col], 0) if outer_col.sum() > 20 else np.array([0.12, 0.08, 0.06])
if args.get("texture_mode", "dark") == "dark":
    yv = 0.299 * fill_rgb[0] + 0.587 * fill_rgb[1] + 0.114 * fill_rgb[2]
    if yv > 0.18:
        fill_rgb = fill_rgb * ((0.18 + (yv - 0.18) * 0.42) / yv)
fill_rgb = fill_rgb * 0.85
if args.get("lining_srgb"):
    # an explicit lining colour, sRGB 0-1 (2026-10-06, DrHart: the inner band is the green SHIRT collar's inside behind
    # the neck, but the fill took the median of the outer collar faces, the white lab coat's collar: a pale grey band)
    fill_rgb = np.array(args["lining_srgb"], np.float64)
report["lining"] ={"faces": int(inner.sum()), "colour_srgb": [round(float(c), 3) for c in fill_rgb]}
rb = np.array([ROUGH["jacket"], ROUGH["shirt"], ROUGH["trousers"], ROUGH["boots"]])[f_reg]
rb[inner] = ROUGH["lining"]
for nm_, vals in (("ms_region", f_reg.astype(np.float64)), ("ms_fill", inner.astype(np.float64)), ("ms_rough", rb)):
    at = gme.attributes.get(nm_) or gme.attributes.new(nm_, "FLOAT", "FACE")
    at.data.foreach_set("value", vals.astype(np.float32))
old_uv = gme.uv_layers.active.name
packed = gme.uv_layers.new(name="Packed", do_init=True)
gme.uv_layers.active = packed
blib.select_only([gar])
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.context.scene.tool_settings.use_uv_select_sync = True
bpy.ops.uv.select_all(action="SELECT")
bpy.ops.uv.pack_islands(rotate=True, margin=0.002, merge_overlap=True)
bpy.ops.object.mode_set(mode="OBJECT")
packed = gme.uv_layers["Packed"]                  # the edit-mode round trip leaves the old reference empty
uvp = np.empty(len(gme.loops) * 2)
packed.data.foreach_get("uv", uvp)
uvo = np.empty(len(gme.loops) * 2)
gme.uv_layers[old_uv].data.foreach_get("uv", uvo)


def uv_area(uv_):
    """The atlas area the garment's triangles cover (overlaps counted twice), by the mesh's own loop triangles."""
    gme.calc_loop_triangles()
    lt_ = np.empty(len(gme.loop_triangles) * 3, np.int64)
    gme.loop_triangles.foreach_get("loops", lt_)
    u = np.mod(uv_.reshape(-1, 2)[lt_.reshape(-1, 3)], 1.0 + 1e-9)
    a, b_, c_ = u[:, 0], u[:, 1], u[:, 2]
    return float(0.5 * np.abs((b_[:, 0] - a[:, 0]) * (c_[:, 1] - a[:, 1]) - (b_[:, 1] - a[:, 1]) * (c_[:, 0] - a[:, 0])).sum())


report["uv"] = {"atlas_share_before": round(uv_area(uvo), 3), "atlas_share_after": round(uv_area(uvp), 3),
                "packed_range": [[round(float(x), 4) for x in uvp.reshape(-1, 2).min(0)], [round(float(x), 4) for x in uvp.reshape(-1, 2).max(0)]]}
log("UVs repacked: %s (share of the atlas the garment's triangles cover; overlapping mirrored halves count twice)" % report["uv"])


def new_image(name, colour):
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    return img


def bake_material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n_ in list(nt.nodes):
        nt.nodes.remove(n_)
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    return m, nt, out_n


def attr(nt, name):
    a = nt.nodes.new("ShaderNodeAttribute")
    a.attribute_type = "GEOMETRY"
    a.attribute_name = name
    return a.outputs["Fac"]


def run_bake(mat_, target, kind, samples=1):
    gme.materials.clear()
    gme.materials.append(mat_)
    for p in gme.polygons:
        p.material_index = 0
    tn = mat_.node_tree.nodes.new("ShaderNodeTexImage")
    tn.image = target
    mat_.node_tree.nodes.active = tn
    scn_ = bpy.context.scene
    scn_.render.engine = "CYCLES"
    scn_.cycles.device = "CPU"
    scn_.cycles.samples = samples
    blib.select_only([gar])
    if kind == "NORMAL":
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", uv_layer="Packed", margin=16, margin_type="EXTEND", use_clear=True)
    else:
        bpy.ops.object.bake(type="EMIT", uv_layer="Packed", margin=16, margin_type="EXTEND", use_clear=True)


# base colour
mBC, nt, outn = bake_material("BakeBC")
uvn = nt.nodes.new("ShaderNodeUVMap")
uvn.uv_map = old_uv
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = clean_img
tex.interpolation = "Cubic"
nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
nz = nt.nodes.new("ShaderNodeTexNoise")
nz.inputs["Scale"].default_value = 90.0
nz.inputs["Detail"].default_value = 4.0
co_n = nt.nodes.new("ShaderNodeTexCoord")
nt.links.new(co_n.outputs["Object"], nz.inputs["Vector"])
lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in fill_rgb]
fillm = nt.nodes.new("ShaderNodeMix")
fillm.data_type = "RGBA"
fillm.inputs["A"].default_value = (*[c * 0.88 for c in lin], 1)
fillm.inputs["B"].default_value = (*[c * 1.12 for c in lin], 1)
nt.links.new(nz.outputs["Fac"], fillm.inputs["Factor"])
mix = nt.nodes.new("ShaderNodeMix")
mix.data_type = "RGBA"
nt.links.new(attr(nt, "ms_fill"), mix.inputs["Factor"])
nt.links.new(tex.outputs["Color"], mix.inputs["A"])
nt.links.new(fillm.outputs["Result"], mix.inputs["B"])
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(mix.outputs["Result"], em.inputs["Color"])
nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
BC = new_image("T_%s_%s_BC" % (NAME, PART), True)
run_bake(mBC, BC, "EMIT")
# roughness / metallic (glTF packing; R = 1 so an occlusion read of it is neutral)
mRM, nt, outn = bake_material("BakeRM")
rough_v = attr(nt, "ms_rough")
if rough_img is not None:
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = old_uv
    rt = nt.nodes.new("ShaderNodeTexImage")
    rt.image = rough_img
    rough_img.colorspace_settings.name = "Non-Color"
    nt.links.new(uvn.outputs["UV"], rt.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(rt.outputs["Color"], sep.inputs["Color"])
    var = nt.nodes.new("ShaderNodeMath")
    var.operation = "MULTIPLY_ADD"
    nt.links.new(sep.outputs["Green"], var.inputs[0])
    var.inputs[1].default_value = 0.14
    var.inputs[2].default_value = -0.07
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    add.use_clamp = True
    nt.links.new(rough_v, add.inputs[0])
    nt.links.new(var.outputs["Value"], add.inputs[1])
    rough_v = add.outputs["Value"]
comb = nt.nodes.new("ShaderNodeCombineColor")
comb.inputs["Red"].default_value = 1.0
comb.inputs["Blue"].default_value = 0.0
if MET and os.path.exists(acc_png):
    # gold / brass trim (buttons, boards, buckle, badges): metallic and glossier, by the hue mask garment_tex wrote
    acc_img = bpy.data.images.load(acc_png)
    acc_img.colorspace_settings.name = "Non-Color"
    uva = nt.nodes.new("ShaderNodeUVMap")
    uva.uv_map = old_uv
    at_ = nt.nodes.new("ShaderNodeTexImage")
    at_.image = acc_img
    nt.links.new(uva.outputs["UV"], at_.inputs["Vector"])
    fill_off = nt.nodes.new("ShaderNodeMath")              # never on the lining fill
    fill_off.operation = "SUBTRACT"
    fill_off.use_clamp = True
    nt.links.new(at_.outputs["Color"], fill_off.inputs[0])
    nt.links.new(attr(nt, "ms_fill"), fill_off.inputs[1])
    mr = nt.nodes.new("ShaderNodeMix")
    mr.data_type = "FLOAT"
    nt.links.new(fill_off.outputs["Value"], mr.inputs["Factor"])
    nt.links.new(rough_v, mr.inputs["A"])
    mr.inputs["B"].default_value = float(MET.get("roughness", 0.35))
    rough_v = mr.outputs["Result"]
    mm_ = nt.nodes.new("ShaderNodeMath")
    mm_.operation = "MULTIPLY"
    nt.links.new(fill_off.outputs["Value"], mm_.inputs[0])
    mm_.inputs[1].default_value = float(MET.get("metallic", 0.8))
    nt.links.new(mm_.outputs["Value"], comb.inputs["Blue"])
nt.links.new(rough_v, comb.inputs["Green"])
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(comb.outputs["Color"], em.inputs["Color"])
nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
RM = new_image("T_%s_%s_RM" % (NAME, PART), False)
run_bake(mRM, RM, "EMIT")
# detail normal: leather grain (jacket, boots), twill (trousers), jersey (shirt); object coordinates with |x| so the
# mirrored halves that share texels bake the same relief
mN, nt, outn = bake_material("BakeN")
bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
nt.links.new(bs.outputs["BSDF"], outn.inputs["Surface"])
co_n = nt.nodes.new("ShaderNodeTexCoord")
sx_ = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(co_n.outputs["Object"], sx_.inputs["Vector"])
ab = nt.nodes.new("ShaderNodeMath")
ab.operation = "ABSOLUTE"
nt.links.new(sx_.outputs["X"], ab.inputs[0])
cxyz = nt.nodes.new("ShaderNodeCombineXYZ")
nt.links.new(ab.outputs["Value"], cxyz.inputs["X"])
nt.links.new(sx_.outputs["Y"], cxyz.inputs["Y"])
nt.links.new(sx_.outputs["Z"], cxyz.inputs["Z"])
vec = cxyz.outputs["Vector"]


def tex_node(kind, scale, **kw):
    n_ = nt.nodes.new(kind)
    n_.inputs["Scale"].default_value = scale
    for k, v in kw.items():
        if k in n_.inputs:
            n_.inputs[k].default_value = v
        else:
            setattr(n_, k, v)
    nt.links.new(vec, n_.inputs["Vector"])
    return n_


grain = tex_node("ShaderNodeTexVoronoi", 430.0, feature="SMOOTH_F1")
grain_n = tex_node("ShaderNodeTexNoise", 45.0, Detail=6.0)
twill = tex_node("ShaderNodeTexWave", 260.0, wave_type="BANDS", bands_direction="DIAGONAL")
jersey = tex_node("ShaderNodeTexNoise", 900.0, Detail=2.0)
boots_g = tex_node("ShaderNodeTexVoronoi", 520.0, feature="SMOOTH_F1")


def mathn(op, a, b=None, clamp=False):
    n_ = nt.nodes.new("ShaderNodeMath")
    n_.operation = op
    n_.use_clamp = clamp
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n_.inputs[k].default_value = x
        else:
            nt.links.new(x, n_.inputs[k])
    return n_.outputs["Value"]


reg = attr(nt, "ms_region")


def comp(k):
    n_ = nt.nodes.new("ShaderNodeMath")
    n_.operation = "COMPARE"
    nt.links.new(reg, n_.inputs[0])
    n_.inputs[1].default_value = float(k)
    n_.inputs[2].default_value = 0.5
    return n_.outputs["Value"]


h_jacket = mathn("ADD", mathn("MULTIPLY", grain.outputs["Distance"], 0.8), mathn("MULTIPLY", grain_n.outputs["Fac"], 0.5))
h_trous = mathn("ADD", mathn("MULTIPLY", twill.outputs["Fac"], 0.7), mathn("MULTIPLY", grain_n.outputs["Fac"], 0.3))
if args.get("jacket_relief", "leather") == "twill":           # a wool tunic, not a leather jacket (2026-10-06)
    h_jacket = h_trous
h_shirt = jersey.outputs["Fac"]
h_boots = mathn("ADD", mathn("MULTIPLY", boots_g.outputs["Distance"], 0.6), mathn("MULTIPLY", grain_n.outputs["Fac"], 0.2))
height = mathn("ADD", mathn("ADD", mathn("MULTIPLY", h_jacket, comp(0)), mathn("MULTIPLY", h_shirt, comp(1))),
               mathn("ADD", mathn("MULTIPLY", h_trous, comp(2)), mathn("MULTIPLY", h_boots, comp(3))))
strength = mathn("ADD", mathn("ADD", mathn("MULTIPLY", comp(0), 0.30), mathn("MULTIPLY", comp(1), 0.25)),
                 mathn("ADD", mathn("MULTIPLY", comp(2), 0.35), mathn("MULTIPLY", comp(3), 0.22)))
bump = nt.nodes.new("ShaderNodeBump")
bump.inputs["Distance"].default_value = 0.0006
nt.links.new(height, bump.inputs["Height"])
nt.links.new(strength, bump.inputs["Strength"])
nt.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
NM = new_image("T_%s_%s_N" % (NAME, PART), False)
run_bake(mN, NM, "NORMAL", samples=4)
maps = {}
for img, sfx in ((BC, "BC"), (RM, "RM"), (NM, "N")):
    p_ = os.path.join(OUT, "T_%s_%s_%s.png" % (NAME, PART, sfx))
    img.filepath_raw = p_
    img.file_format = "PNG"
    img.save()
    maps[sfx] = p_
report["textures"] = {k: os.path.basename(v) for k, v in maps.items()}
report["roughness"] = ROUGH
# the garment's own UVs only, its materials: one slot per region, all on the same three maps
gme.uv_layers.remove(gme.uv_layers[old_uv])
gme.uv_layers["Packed"].name = "UVMap"
gme.uv_layers.active = gme.uv_layers["UVMap"]
gme.uv_layers["UVMap"].active_render = True
for a_n in ("ms_region", "ms_fill", "ms_rough"):
    gme.attributes.remove(gme.attributes[a_n])
for m_ in (mBC, mRM, mN):
    bpy.data.materials.remove(m_)


def garment_material(name):
    """BC, RM (G roughness, B metallic) and the tangent normal on a two-sided Principled BSDF: what the glTF carries and
    what the renders show (v5's renders used a flat 0.55 roughness, not the delivered maps)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt_ = m.node_tree
    bsdf_ = nt_.nodes["Principled BSDF"]
    t1 = nt_.nodes.new("ShaderNodeTexImage")
    t1.image = BC
    nt_.links.new(t1.outputs["Color"], bsdf_.inputs["Base Color"])
    t2 = nt_.nodes.new("ShaderNodeTexImage")
    t2.image = RM
    sp = nt_.nodes.new("ShaderNodeSeparateColor")
    nt_.links.new(t2.outputs["Color"], sp.inputs["Color"])
    nt_.links.new(sp.outputs["Green"], bsdf_.inputs["Roughness"])
    nt_.links.new(sp.outputs["Blue"], bsdf_.inputs["Metallic"])
    t3 = nt_.nodes.new("ShaderNodeTexImage")
    t3.image = NM
    nm_ = nt_.nodes.new("ShaderNodeNormalMap")
    nm_.uv_map = "UVMap"
    nt_.links.new(t3.outputs["Color"], nm_.inputs["Color"])
    nt_.links.new(nm_.outputs["Normal"], bsdf_.inputs["Normal"])
    m.use_backface_culling = False
    return m


gme.materials.clear()
for rg in REGIONS:
    gme.materials.append(garment_material("MI_%s_%s_%s" % (NAME, PART, rg)))
gme.polygons.foreach_set("material_index", f_reg.astype(np.int32))
for p in gme.polygons:
    p.use_smooth = True
gme.update()
blib.select_only([gar])
glb = os.path.join(OUT, "fitted.glb")
bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)
report["fitted_glb"] = glb
lo, hi = blib.dims(gar)
report["garment_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
report["triangles"] = blib.tri_count(gar)

# ----------------------------------------------------------------------------------------------- 16. renders
reset_pose()
_ev = Surface(body).co
report["render_body_rest_mm"] = round(float(np.abs(_ev - rest.co).max()) * 1000, 3)
skin = bpy.data.materials.new("Skin")
skin.use_nodes = True
skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.40, 0.33, 1)
skin.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
for o in [body] + ([face] if face else []):
    o.data.materials.clear()
    o.data.materials.append(skin)
size_px = int(args.get("render_size", 1024))
blib.setup_render(size_px, int(args.get("samples", 24)), look="preview")
scn = bpy.context.scene
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
bpy.context.collection.objects.link(cam)
scn.camera = cam
for nm, dvec, e in (("Key", (-0.6, -1.0, 0.8), 600), ("Fill", (1.0, -0.4, 0.3), 250), ("Back", (0.3, 1.0, 0.9), 350)):
    L = bpy.data.lights.new(nm, "AREA")
    L.energy, L.size = e, 2.0
    o = bpy.data.objects.new(nm, L)
    bpy.context.collection.objects.link(o)
    o.location = Vector(dvec).normalized() * 4 + Vector((0, 0, 1.0))
    o.rotation_euler = (Vector((0, 0, 1.0)) - o.location).to_track_quat("-Z", "Y").to_euler()
blo, bhi = blib.dims(body)
if face:
    flo, fhi = blib.dims(face)
    blo = Vector(np.minimum(np.array(blo), np.array(flo)))
    bhi = Vector(np.maximum(np.array(bhi), np.array(fhi)))
renders = {}


def shoot(name, view=None, direction=None, centre=None, extent=None):
    """An orthographic picture: one of blib's axis views of the whole figure, or a direction at a box."""
    if view:
        blib.ortho_camera(cam, view, blo, bhi, margin=1.04)
    else:
        dvec = Vector(direction).normalized()
        cam.data.type = "ORTHO"
        cam.location = Vector(centre) + dvec * 3.0
        cam.rotation_euler = (-dvec).to_track_quat("-Z", "Y").to_euler()
        cam.data.ortho_scale = extent
        cam.data.clip_start, cam.data.clip_end = 0.01, 10
    path = os.path.join(OUT, "fit_%s.png" % name)
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[name] = os.path.basename(path)


neck = Vector(NA.tolist())
shoot("front", "left")
shoot("side", "front")
shoot("back", "right")
shoot("collar", direction=(-0.55, -1.0, 0.35), centre=neck + Vector((0, 0, -0.04)), extent=0.62)
shoot("collar_portrait", direction=(0.0, -1.0, 0.08), centre=neck + Vector((0, 0, 0.06)), extent=0.46)
shoot("collar_back", direction=(0.5, 1.0, 0.45), centre=neck + Vector((0, 0, -0.04)), extent=0.62)
shoot("collar_back_left", direction=(-0.5, 1.0, 0.45), centre=neck + Vector((0, 0, -0.04)), extent=0.62)
shoot("feet", direction=(-0.45, -1.0, 0.35), centre=Vector((cx_body, -0.06, 0.09)), extent=0.62)
shoot("boot_side", direction=(1.0, 0.0, 0.05), centre=Vector((0.14, -0.04, 0.12)), extent=0.40)
shoot("sleeve", direction=(1.0, -0.25, 0.15), centre=Vector((0.33, -0.02, 1.12)), extent=0.75)
shoot("armpit", direction=(0.25, -1.0, -0.35), centre=Vector((0.22, 0.0, 1.22)), extent=0.45)
body.hide_render = True
if face:
    face.hide_render = True
shoot("garment_front", "left")
shoot("garment_back", "right")
body.hide_render = False
if face:
    face.hide_render = False
report["renders"] = renders

# ----------------------------------------------------------------------------------------------- 17. the .blend for skinning
for o in list(bpy.data.objects):
    if o is not gar:
        bpy.data.objects.remove(o, do_unlink=True)
for m_ in list(bpy.data.materials):
    if m_.name not in [x.name for x in gme.materials if x]:
        bpy.data.materials.remove(m_)
for img in list(bpy.data.images):
    if img not in (BC, RM, NM):
        bpy.data.images.remove(img)
for img in list(bpy.data.images):
    if img.users and img.has_data and img.size[0] > 0:
        try:
            img.pack()
        except Exception as ex:
            log("could not pack %s: %s" % (img.name, ex))
blend = os.path.join(OUT, "fitted.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
report["fitted_blend"] = blend
for p_ in (src_png,):
    try:
        os.remove(p_)
    except OSError:
        pass
json.dump(report, open(os.path.join(OUT, "fit_report.json"), "w", encoding="utf-8", newline="\n"), indent=1,
          default=lambda o: o.item() if hasattr(o, "item") else str(o))
log("done -> %s" % OUT)

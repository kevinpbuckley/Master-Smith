"""The bind pose of a skeletal FBX read raw (no importer between us and the file), and two files compared bone by bone.
    .venv/Scripts/python.exe out/_MetaHumanBatch/fbx_bind_check.py <reference.fbx> [<candidate.fbx>] [--json out.json]

Why (2026-10-06): the AINavigator's skinned headset came back 90 degrees off in Unreal after a Blender round trip. A
skeletal mesh that follows a MetaHuman body by leader pose is skinned with ITS OWN bind pose against the body's bone
transforms, so every bone's global bind matrix must equal the body's, and Unreal must see the same bone list: no extra
root (a Blender armature object becomes a bone unless it is named "Armature"). This reads both files' GlobalSettings
(axes, unit), node hierarchy, BindPose and cluster TransformLink matrices, maps each file into one frame (Blender's
axis_conversion of the declared axes, centimetres) and reports the worst rotation (degrees) and offset (cm) per bone."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fbxparse import parse_fbx  # noqa: E402

# Blender's fbx_utils.RIGHT_HAND_AXES: (up, forward) -> ((up axis, sign), (front axis, sign), (coord axis, sign))
RIGHT_HAND_AXES = {
    ('X', '-Y'): ((0, 1), (1, 1), (2, 1)), ('X', 'Y'): ((0, 1), (1, -1), (2, -1)),
    ('X', '-Z'): ((0, 1), (2, 1), (1, -1)), ('X', 'Z'): ((0, 1), (2, -1), (1, 1)),
    ('-X', '-Y'): ((0, -1), (1, 1), (2, -1)), ('-X', 'Y'): ((0, -1), (1, -1), (2, 1)),
    ('-X', '-Z'): ((0, -1), (2, 1), (1, 1)), ('-X', 'Z'): ((0, -1), (2, -1), (1, -1)),
    ('Y', '-X'): ((1, 1), (0, 1), (2, -1)), ('Y', 'X'): ((1, 1), (0, -1), (2, 1)),
    ('Y', '-Z'): ((1, 1), (2, 1), (0, 1)), ('Y', 'Z'): ((1, 1), (2, -1), (0, -1)),
    ('-Y', '-X'): ((1, -1), (0, 1), (2, 1)), ('-Y', 'X'): ((1, -1), (0, -1), (2, -1)),
    ('-Y', '-Z'): ((1, -1), (2, 1), (0, -1)), ('-Y', 'Z'): ((1, -1), (2, -1), (0, 1)),
    ('Z', '-X'): ((2, 1), (0, 1), (1, 1)), ('Z', 'X'): ((2, 1), (0, -1), (1, -1)),
    ('Z', '-Y'): ((2, 1), (1, 1), (0, -1)), ('Z', 'Y'): ((2, 1), (1, -1), (0, 1)),
    ('-Z', '-X'): ((2, -1), (0, 1), (1, -1)), ('-Z', 'X'): ((2, -1), (0, -1), (1, 1)),
    ('-Z', '-Y'): ((2, -1), (1, 1), (0, 1)), ('-Z', 'Y'): ((2, -1), (1, -1), (0, -1)),
}
AXV = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}


def axis_vec(s):
    """'-Y' -> (0, -1, 0)."""
    v = np.array(AXV[s[-1]], float)
    return -v if s.startswith('-') else v


def axis_conversion(from_forward, from_up):
    """Blender's bpy_extras.io_utils.axis_conversion to forward Y, up Z, as a 3x3 numpy matrix."""
    f, u = axis_vec(from_forward), axis_vec(from_up)
    r = np.cross(f, u)
    return np.vstack([r, f, u])          # rows: what lands on X, Y, Z


def name_of(props0):
    """b'root\\x00\\x01Model' -> 'root'."""
    b = props0 if isinstance(props0, bytes) else bytes(props0)
    return b.split(b'\x00\x01')[0].decode('utf-8', 'replace')


def props70(elem):
    """{name: values} of an element's Properties70."""
    out = {}
    for sub in elem.elems:
        if sub.id == b'Properties70':
            for p in sub.elems:
                out[p.props[0].decode('utf-8', 'replace')] = list(p.props[4:])
    return out


def find(elem, ident):
    return next((e for e in elem.elems if e.id == ident), None)


def euler_xyz(deg):
    """FBX eEulerXYZ: X first, then Y, then Z (R = Rz Ry Rx)."""
    x, y, z = np.radians(deg)
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def mat16(vals):
    """FBX's 16 doubles (column-major) -> 4x4 with the translation in the last column."""
    return np.array(vals, float).reshape(4, 4).T


def read(path):
    """The file's settings, models, hierarchy, bind pose and clusters."""
    root, version = parse_fbx.parse(path)
    top = {e.id: e for e in root.elems}
    gs = props70(top[b'GlobalSettings'])
    g = lambda k, d: gs.get(k, [d])[0]
    up, front, coord = (g('UpAxis', 2), g('UpAxisSign', 1)), (g('FrontAxis', 1), g('FrontAxisSign', 1)), (g('CoordAxis', 0), g('CoordAxisSign', 1))
    key = {v: k for k, v in RIGHT_HAND_AXES.items()}.get((up, front, coord), ('Z', 'Y'))
    A = axis_conversion(from_forward=key[1], from_up=key[0])
    unit = float(g('UnitScaleFactor', 1.0))           # centimetres per file unit
    creator = ''
    if b'Creator' in top:
        creator = top[b'Creator'].props[0].decode('utf-8', 'replace') if top[b'Creator'].props else ''
    objs = top[b'Objects']
    models, poses, clusters = {}, {}, {}
    for e in objs.elems:
        if e.id == b'Model':
            uid = e.props[0]
            p = props70(e)
            models[uid] = {"name": name_of(e.props[1]), "type": e.props[2].decode() if len(e.props) > 2 else '',
                           "t": np.array(p.get('Lcl Translation', [0, 0, 0])[:3], float),
                           "r": np.array(p.get('Lcl Rotation', [0, 0, 0])[:3], float),
                           "s": np.array(p.get('Lcl Scaling', [1, 1, 1])[:3], float),
                           "pre": np.array(p.get('PreRotation', [0, 0, 0])[:3], float),
                           "post": np.array(p.get('PostRotation', [0, 0, 0])[:3], float),
                           "order": int(p.get('RotationOrder', [0])[0]),
                           "pivots": any(np.abs(np.array(p.get(k, [0, 0, 0])[:3], float)).max() > 1e-6
                                         for k in ('RotationOffset', 'RotationPivot', 'ScalingOffset', 'ScalingPivot')),
                           "parent": None}
        elif e.id == b'Pose' and len(e.props) > 2 and e.props[2] == b'BindPose':
            for pn in e.elems:
                if pn.id == b'PoseNode':
                    node = find(pn, b'Node').props[0]
                    poses[node] = mat16(find(pn, b'Matrix').props[0])
        elif e.id == b'Deformer' and len(e.props) > 2 and e.props[2] == b'Cluster':
            tl = find(e, b'TransformLink')
            if tl is not None:
                clusters[e.props[0]] = mat16(tl.props[0])
    cluster_bone = {}
    for c in find(root, b'Connections').elems if find(root, b'Connections') else []:
        if c.props[0] == b'OO':
            child, parent = c.props[1], c.props[2]
            if child in models:
                if parent in models or parent == 0:
                    models[child]["parent"] = parent if parent != 0 else 0
            if child in models and parent in clusters:
                cluster_bone[parent] = child
    return {"path": path, "version": version, "creator": creator, "axes": {"up": up, "front": front, "coord": coord, "blender_key": key},
            "A": A, "unit_cm": unit, "models": models, "poses": poses, "clusters": clusters, "cluster_bone": cluster_bone}


def local_matrix(m):
    """T * Rpre * R * Rpost^-1 * S (pivots and offsets are reported, not applied)."""
    if m["order"] != 0:
        raise ValueError("%s: rotation order %d is not handled" % (m["name"], m["order"]))
    M = np.eye(4)
    M[:3, :3] = euler_xyz(m["pre"]) @ euler_xyz(m["r"]) @ np.linalg.inv(euler_xyz(m["post"])) @ np.diag(m["s"])
    M[:3, 3] = m["t"]
    return M


def globals_from_nodes(f):
    """Every model's global matrix from its Lcl chain."""
    out = {}

    def g(uid):
        if uid in out:
            return out[uid]
        m = f["models"][uid]
        par = m["parent"]
        M = local_matrix(m) if not par else g(par) @ local_matrix(m)
        out[uid] = M
        return M
    for uid in f["models"]:
        g(uid)
    return out


def to_frame(f, M):
    """A file-space global matrix -> the common frame (Blender axes, centimetres); rotation part orthonormalised."""
    A4 = np.eye(4)
    A4[:3, :3] = f["A"] * f["unit_cm"]
    G = A4 @ M
    R = G[:3, :3]
    sc = np.linalg.norm(R, axis=0)
    # the rotation Unreal keeps (FbxAMatrix::GetQ): the polar factor, so a slightly sheared bind matrix is compared by
    # its rotation, not by its raw columns
    U, _, Vt = np.linalg.svd(R)
    Rp = U @ Vt
    if np.linalg.det(Rp) < 0:
        U[:, -1] *= -1
        Rp = U @ Vt
    return Rp, G[:3, 3], sc


def rot_angle(R1, R2):
    c = (np.trace(R1.T @ R2) - 1) / 2
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def summary(f):
    """Bones, the chain from the scene root to the first bone, the mesh nodes' parents, the root bone's frame."""
    ms = f["models"]
    bones = {u: m for u, m in ms.items() if m["type"] == 'LimbNode'}
    first = [u for u, m in bones.items() if not (m["parent"] and ms[m["parent"]]["type"] == 'LimbNode')]
    chains = []
    for u in first:
        chain, p = [], u
        while p:
            chain.append("%s(%s)" % (ms[p]["name"], ms[p]["type"]))
            p = ms[p]["parent"]
        chains.append(" <- ".join(chain) + " <- SceneRoot")
    meshes = ["%s(parent %s)" % (m["name"], ms[m["parent"]]["name"] if m["parent"] else "SceneRoot") for m in ms.values() if m["type"] == 'Mesh']
    G = globals_from_nodes(f)
    nulls_above = []
    for u in first:
        p = ms[u]["parent"]
        while p:
            if ms[p]["type"] != 'LimbNode':
                R, t, sc = to_frame(f, G[p])
                nulls_above.append({"name": ms[p]["name"], "type": ms[p]["type"], "lcl_r": ms[p]["r"].round(3).tolist(),
                                    "lcl_s": ms[p]["s"].round(4).tolist(), "lcl_t": ms[p]["t"].round(3).tolist(),
                                    "pre": ms[p]["pre"].round(3).tolist()})
            p = ms[p]["parent"]
    return {"file": os.path.basename(f["path"]), "creator": f["creator"], "fbx_version": f["version"],
            "axes": {k: list(v) for k, v in f["axes"].items()}, "unit_cm_per_unit": f["unit_cm"],
            "bones": len(bones), "skeleton_chains": chains, "nodes_above_first_bone": nulls_above, "meshes": meshes,
            "bind_pose_nodes": len(f["poses"]), "clusters": len(f["clusters"]),
            "pivots_or_offsets": [m["name"] for m in ms.values() if m["pivots"]][:10]}


def bone_globals(f, source):
    """{bone name: (R, t)} in the common frame from 'bind' (BindPose, else TransformLink, else nodes), 'link' or 'nodes'."""
    ms = f["models"]
    G = globals_from_nodes(f)
    link = {f["cluster_bone"][c]: M for c, M in f["clusters"].items() if c in f["cluster_bone"]}
    out = {}
    for u, m in ms.items():
        if m["type"] != 'LimbNode':
            continue
        if source == 'nodes':
            M = G[u]
        elif source == 'link':
            if u not in link:
                continue
            M = link[u]
        else:
            M = f["poses"].get(u, link.get(u, G[u]))
        R, t, sc = to_frame(f, M)
        out[m["name"]] = (R, t, sc, ms[m["parent"]]["name"] if m["parent"] and ms[m["parent"]]["type"] == 'LimbNode' else None)
    return out


def compare(fa, fb, source):
    """Per-bone rotation (deg) and offset (cm) of b against a for the bones they share; hierarchy differences."""
    a, b = bone_globals(fa, source), bone_globals(fb, source)
    common = [n for n in a if n in b]
    rows = []
    for n in common:
        Ra, ta, sa, pa = a[n]
        Rb, tb, sb, pb = b[n]
        rows.append({"bone": n, "rot_deg": round(rot_angle(Ra, Rb), 4), "off_cm": round(float(np.linalg.norm(ta - tb)), 4),
                     "scale_ratio": round(float(np.max(np.abs(sb / np.where(sa > 1e-12, sa, 1) - 1))), 5), "parent_same": pa == pb})
    rows.sort(key=lambda r: (r["rot_deg"], r["off_cm"]), reverse=True)
    return {"source": source, "bones_a": len(a), "bones_b": len(b), "common": len(common),
            "only_in_a": sorted(set(a) - set(b))[:20], "only_in_b": sorted(set(b) - set(a))[:20],
            "parent_mismatch": [r["bone"] for r in rows if not r["parent_same"]][:20],
            "max_rot_deg": max((r["rot_deg"] for r in rows), default=None), "max_off_cm": max((r["off_cm"] for r in rows), default=None),
            "max_scale_ratio": max((r["scale_ratio"] for r in rows), default=None),
            "worst": rows[:8], "root": next((r for r in rows if r["bone"] == "root"), None)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    if out_json in args:
        args.remove(out_json)
    files = [read(p) for p in args]
    rep = {"files": [summary(f) for f in files]}
    if len(files) == 2:
        rep["compare"] = {s: compare(files[0], files[1], s) for s in ("bind", "link", "nodes")}
        c = rep["compare"]["bind"]
        ident = lambda n: n["lcl_r"] == [0.0, 0.0, 0.0] and n["lcl_s"] == [1.0, 1.0, 1.0] and n["lcl_t"] == [0.0, 0.0, 0.0] and n["pre"] == [0.0, 0.0, 0.0]
        # Unreal (FbxMainImport.cpp GetRootSkeleton) climbs from the bones through nulls to the node under the scene
        # root: a null named "root" becomes the root bone (the body's own root is an identity "Root" node), a null
        # named "Armature" in a Blender file is skipped, any other null becomes an extra bone
        above = rep["files"][1]["nodes_above_first_bone"]
        top_ok = all((n["name"] == "root" and ident(n)) or n["name"].lower() == "armature" for n in above)
        rep["verdict"] = {"bind_match": bool(c["max_rot_deg"] is not None and c["max_rot_deg"] < 0.05 and c["max_off_cm"] < 0.05),
                          "hierarchy_ok_for_unreal": bool(top_ok and not c["only_in_b"] and not c["parent_mismatch"]
                                                          and rep["files"][0]["axes"] == rep["files"][1]["axes"]),
                          "why": "every shared bone's global bind within 0.05 deg / 0.05 cm of the reference, no bone the reference lacks, "
                                 "the same parents, the reference's axis system (Unreal converts nothing), and above the bones only a "
                                 "null 'root' at identity (Unreal's root bone, as the body's) or a Blender 'Armature' null (skipped)"}
    txt = json.dumps(rep, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    if out_json:
        open(out_json, "w", encoding="utf-8", newline="\n").write(txt)
    print(txt)


if __name__ == "__main__":
    main()

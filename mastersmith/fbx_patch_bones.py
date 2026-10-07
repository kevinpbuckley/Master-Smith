"""Copy a reference skeletal FBX's exact bone transforms into another skinned FBX (binary in, binary out):
    .venv/Scripts/python.exe out/_MetaHumanBatch/fbx_patch_bones.py <reference.fbx> <in.fbx> <out.fbx>
For every bone the two files share by name: the Model's Lcl Translation / Rotation / Scaling (and Pre/PostRotation
when the reference has them), the BindPose matrix and the skin cluster's TransformLink are set to the reference's
values; a bone the reference has as its "Root" node (Unreal's root) is matched to the candidate's top node of the same
name (Blender writes its armature object there). Nothing else in the file changes.

Why (2026-10-06): Blender stores a bone as head, tail and roll, and a round trip of the MetaHuman body skeleton lost up
to 0.14 degrees on the right thigh's twist bones (Blender's roll is ill-conditioned for bones along -Y). A garment that
follows the body by leader pose is skinned with its own bind pose against the body's bone transforms, so its bind pose
should be the body's to the last digit: the file Unreal reads then carries exactly the numbers Unreal wrote. Both
files must declare the same axis system and unit (garment_attach.py exports in Unreal's own: Z up, front -Y, cm)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fbxparse import data_types, encode_bin, parse_fbx  # noqa: E402

LCL = (b"Lcl Translation", b"Lcl Rotation", b"Lcl Scaling", b"PreRotation", b"PostRotation")


def name_of(b):
    return bytes(b).split(b"\x00\x01")[0].decode("utf-8", "replace")


def child(elem, ident):
    return next((e for e in elem.elems if e.id == ident), None)


def settings(root):
    gs = child(child(root, b"GlobalSettings"), b"Properties70")
    out = {}
    for p in gs.elems:
        if p.props[0] in (b"UpAxis", b"UpAxisSign", b"FrontAxis", b"FrontAxisSign", b"CoordAxis", b"CoordAxisSign", b"UnitScaleFactor"):
            out[p.props[0].decode()] = p.props[4]
    return out


def collect(root):
    """-> {bone name: {"uid", "lcl": {prop: [x, y, z]}, "pose": 16 floats, "link": 16 floats}} for LimbNode/Root models
    and the nulls directly above them."""
    objs = child(root, b"Objects")
    models, clusters, poses = {}, {}, {}
    for e in objs.elems:
        if e.id == b"Model":
            p70 = child(e, b"Properties70")
            lcl = {}
            if p70 is not None:
                for p in p70.elems:
                    if p.props[0] in LCL:
                        lcl[p.props[0]] = [float(v) for v in p.props[4:7]]
            models[e.props[0]] = {"name": name_of(e.props[1]), "type": e.props[2], "lcl": lcl}
        elif e.id == b"Deformer" and len(e.props) > 2 and e.props[2] == b"Cluster":
            tl = child(e, b"TransformLink")
            clusters[e.props[0]] = list(tl.props[0]) if tl is not None else None
        elif e.id == b"Pose" and len(e.props) > 2 and e.props[2] == b"BindPose":
            for pn in e.elems:
                if pn.id == b"PoseNode":
                    poses[child(pn, b"Node").props[0]] = list(child(pn, b"Matrix").props[0])
    links = {}
    for c in child(root, b"Connections").elems:
        if c.props[0] == b"OO" and c.props[1] in models and c.props[2] in clusters:
            links[c.props[1]] = clusters[c.props[2]]
    out = {}
    for uid, m in models.items():
        if m["type"] in (b"LimbNode", b"Root", b"Null"):
            out.setdefault(m["name"], {"uid": uid, "type": m["type"], "lcl": m["lcl"], "pose": poses.get(uid), "link": links.get(uid)})
    return out


def patch(ref_path, in_path, out_path):
    ref_root, _ = parse_fbx.parse(ref_path)
    root, version = parse_fbx.parse(in_path)
    sr, si = settings(ref_root), settings(root)
    if any(abs(float(sr[k]) - float(si.get(k, -99))) > 1e-9 for k in sr):
        raise SystemExit("the files declare different axes or units (%s vs %s): export in the reference's own axis system first" % (sr, si))
    ref = collect(ref_root)
    cand = collect(root)
    ref_bones = {n: b for n, b in ref.items() if b["type"] in (b"LimbNode", b"Root")}
    by_uid = {}
    for n, b in cand.items():
        if n in ref_bones:
            by_uid[b["uid"]] = ref_bones[n]
    cluster_bone = {}
    for c in child(root, b"Connections").elems:
        if c.props[0] == b"OO":
            cluster_bone[c.props[2]] = c.props[1]
    counts = {"lcl": 0, "pose": 0, "link": 0}

    def convert(elem, parent_model=None):
        e = encode_bin.FBXElem(elem.id)
        props = list(elem.props)
        model_ref = None
        if elem.id == b"Model" and props and props[0] in by_uid:
            model_ref = by_uid[props[0]]
        if elem.id == b"P" and parent_model is not None and props and props[0] in LCL:
            want = parent_model["lcl"].get(props[0])
            if want is None:
                want = [1.0, 1.0, 1.0] if props[0] == b"Lcl Scaling" else [0.0, 0.0, 0.0]
            props[4:7] = [float(v) for v in want]
            counts["lcl"] += 1
        for p, t in zip(props, elem.props_type):
            add(e, p, t)
        for c in elem.elems:
            if c.id == b"Properties70" and model_ref is not None:
                e.elems.append(convert_p70(c, model_ref))
            else:
                e.elems.append(convert(c, None))
        return e

    def convert_p70(p70, model_ref):
        e = encode_bin.FBXElem(p70.id)
        seen = set()
        for p in p70.elems:
            e.elems.append(convert(p, model_ref))
            seen.add(p.props[0])
        # a transform the reference has and Blender left at its default is written out too
        for k in LCL:
            if k in model_ref["lcl"] and k not in seen:
                pe = encode_bin.FBXElem(b"P")
                kind = {b"Lcl Translation": b"Lcl Translation", b"Lcl Rotation": b"Lcl Rotation", b"Lcl Scaling": b"Lcl Scaling"}.get(k, b"Vector3D")
                pe.add_string(k)
                pe.add_string(kind)
                pe.add_string(b"" if kind == b"Vector3D" else b"")
                pe.add_string(b"A")
                for v in model_ref["lcl"][k]:
                    pe.add_float64(float(v))
                e.elems.append(pe)
                counts["lcl"] += 1
        return e

    def add(e, p, t):
        if t == data_types.BOOL:
            e.add_bool(bool(p))
        elif t == data_types.CHAR:
            e.add_char(p if isinstance(p, bytes) else bytes([p]))
        elif t == data_types.INT8:
            e.add_int8(int(p))
        elif t == data_types.INT16:
            e.add_int16(int(p))
        elif t == data_types.INT32:
            e.add_int32(int(p))
        elif t == data_types.INT64:
            e.add_int64(int(p))
        elif t == data_types.FLOAT32:
            e.add_float32(float(p))
        elif t == data_types.FLOAT64:
            e.add_float64(float(p))
        elif t == data_types.BYTES:
            e.add_bytes(bytes(p))
        elif t == data_types.STRING:
            e.add_string(bytes(p))
        elif t == data_types.INT32_ARRAY:
            e.add_int32_array(np.asarray(p, np.int32))
        elif t == data_types.INT64_ARRAY:
            e.add_int64_array(np.asarray(p, np.int64))
        elif t == data_types.FLOAT32_ARRAY:
            e.add_float32_array(np.asarray(p, np.float32))
        elif t == data_types.FLOAT64_ARRAY:
            e.add_float64_array(np.asarray(p, np.float64))
        elif t == data_types.BOOL_ARRAY:
            e.add_bool_array(np.asarray(p, bool))
        elif t == data_types.BYTE_ARRAY:
            e.add_byte_array(np.asarray(p, np.byte))
        else:
            raise ValueError("unknown FBX property type %r" % t)

    # the bind pose and cluster matrices: edited on the parsed tree before it is converted
    def edit_matrices(elem):
        if elem.id == b"PoseNode":
            node = child(elem, b"Node").props[0]
            if node in by_uid and by_uid[node]["pose"] is not None:
                m = child(elem, b"Matrix")
                m.props[0] = np.asarray(by_uid[node]["pose"], np.float64)
                counts["pose"] += 1
        elif elem.id == b"Deformer" and len(elem.props) > 2 and elem.props[2] == b"Cluster":
            bone_uid = cluster_bone.get(elem.props[0])
            if bone_uid in by_uid:
                r = by_uid[bone_uid]
                want = r["link"] if r["link"] is not None else r["pose"]
                tl = child(elem, b"TransformLink")
                if tl is not None and want is not None:
                    tl.props[0] = np.asarray(want, np.float64)
                    counts["link"] += 1
        for c in elem.elems:
            edit_matrices(c)

    root = to_mutable(root)
    for c in root.elems:
        edit_matrices(c)
    out_root = encode_bin.FBXElem(b"")
    for c in root.elems:
        out_root.elems.append(convert(c))
    encode_bin.write(out_path, out_root, version)
    missing = sorted(set(ref_bones) - set(cand))
    return {"bones_matched": len(by_uid), "reference_bones": len(ref_bones), "missing_in_candidate": missing[:20], **counts}


class M:
    """A mutable stand-in for parse_fbx's FBXElem namedtuple."""
    __slots__ = ("id", "props", "props_type", "elems")

    def __init__(self, ident, props, props_type, elems):
        self.id, self.props, self.props_type, self.elems = ident, props, props_type, elems


def to_mutable(e):
    return M(e.id, list(e.props), e.props_type, [to_mutable(c) for c in e.elems])


if __name__ == "__main__":
    print(patch(sys.argv[1], sys.argv[2], sys.argv[3]))

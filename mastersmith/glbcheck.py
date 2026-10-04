"""The delivered GLB read back without Blender (2026-10-04, from Mixar's export verification): the container parsed,
its meshes, triangles, materials, images, sockets and world-space size listed, and compared with what report.json
says was exported. The FBX is read back inside Blender at the end of `assemble`; the GLB was never checked, and a
check that needs no Blender can run in `ms package` and in the tests."""
import json
import math
import os
import struct

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
FLOATS = {5126: ("f", 4)}
INTS = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}


def read_glb(path):
    """-> (the JSON document, the BIN chunk bytes or b""); raises ValueError on a bad container."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 20:
        raise ValueError("truncated GLB header")
    magic, _version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB container")
    if length > len(data):
        raise ValueError("GLB shorter than its header says (%d of %d bytes)" % (len(data), length))
    pos, doc, blob = 12, None, b""
    while pos + 8 <= length:
        clen, ctype = struct.unpack_from("<II", data, pos)
        body = data[pos + 8:pos + 8 + clen]
        if ctype == JSON_CHUNK and doc is None:
            doc = json.loads(body.decode("utf-8"))
        elif ctype == BIN_CHUNK and not blob:
            blob = body
        pos += 8 + clen
    if doc is None:
        raise ValueError("no JSON chunk")
    return doc, blob


def _matrix(node):
    """A node's local 4x4 (row-major rows) from its matrix or its translation, rotation and scale."""
    if node.get("matrix"):
        m = node["matrix"]                                     # column-major in glTF
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = node.get("translation") or [0, 0, 0]
    q = node.get("rotation") or [0, 0, 0, 1]
    s = node.get("scale") or [1, 1, 1]
    x, y, z, w = q
    rot = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
           [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
           [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[rot[r][c] * s[c] for c in range(3)] + [t[r]] for r in range(3)] + [[0, 0, 0, 1]]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _apply(m, p):
    return [m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3] for r in range(3)]


def world_nodes(doc):
    """Every node of the scene with its world matrix, [(index, node, matrix)], the root nodes first."""
    nodes = doc.get("nodes") or []
    scenes = doc.get("scenes") or []
    roots = list(scenes[doc.get("scene", 0)].get("nodes") or []) if scenes else list(range(len(nodes)))
    out, stack = [], [(i, _identity()) for i in roots]
    seen = set()
    while stack:
        i, parent = stack.pop(0)
        if i in seen or i >= len(nodes):
            continue
        seen.add(i)
        m = _mul(parent, _matrix(nodes[i]))
        out.append((i, nodes[i], m))
        stack += [(c, m) for c in nodes[i].get("children") or []]
    return out


def _identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def to_blender(p):
    """glTF is Y up and -Z forward; Blender (and the plan frame) Z up: (x, y, z) -> (x, -z, y)."""
    return [p[0], -p[2], p[1]]


def summarize(path):
    """What the GLB holds: {"meshes", "nodes", "scenes", "materials", "images", "images_embedded", "triangles",
    "dimensions_m" (Blender frame, world space through the node transforms), "sockets": {name: [x, y, z]},
    "attributes" (which vertex attributes every primitive carries), "draco", "issues": [...]}. Never raises: a bad
    file reports its problem in "issues" with "checked": False."""
    out = {"checked": False, "file": os.path.basename(path), "file_size_bytes": 0, "meshes": 0, "nodes": 0, "scenes": 0,
           "materials": [], "images": 0, "images_embedded": None, "triangles": 0, "dimensions_m": None, "sockets": {},
           "attributes": [], "draco": False, "issues": []}
    try:
        out["file_size_bytes"] = os.path.getsize(path)
        doc, blob = read_glb(path)
    except (OSError, ValueError, UnicodeDecodeError, struct.error) as exc:
        out["issues"].append("the GLB cannot be read: %s" % exc)
        return out
    meshes = doc.get("meshes") or []
    accessors = doc.get("accessors") or []
    images = doc.get("images") or []
    out["meshes"], out["nodes"], out["scenes"] = len(meshes), len(doc.get("nodes") or []), len(doc.get("scenes") or [])
    out["materials"] = [str(m.get("name", "")) for m in doc.get("materials") or []]
    out["images"] = len(images)
    if images:
        out["images_embedded"] = all("bufferView" in im or str(im.get("uri", "")).startswith("data:") for im in images)
    out["draco"] = "KHR_draco_mesh_compression" in (doc.get("extensionsUsed") or [])
    if out["scenes"] > 1:
        out["issues"].append("the file holds %d scenes; a delivery is one scene" % out["scenes"])
    attrs = None
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            a = set((prim.get("attributes") or {}).keys())
            attrs = a if attrs is None else attrs & a
            mode = prim.get("mode", 4)
            idx = prim.get("indices")
            pos = (prim.get("attributes") or {}).get("POSITION")
            count = None
            if idx is not None and idx < len(accessors):
                count = accessors[idx].get("count")
            elif pos is not None and pos < len(accessors):
                count = accessors[pos].get("count")
            if count and mode == 4:
                out["triangles"] += int(count) // 3
            elif count and mode in (5, 6):
                out["triangles"] += max(0, int(count) - 2)
    out["attributes"] = sorted(attrs or [])
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for _i, node, m in world_nodes(doc):
        name = str(node.get("name", ""))
        if name.startswith("SOCKET_"):
            out["sockets"][name] = [round(v, 5) for v in to_blender(_apply(m, [0, 0, 0]))]
        if node.get("mesh") is None or node["mesh"] >= len(meshes):
            continue
        for prim in meshes[node["mesh"]].get("primitives") or []:
            pos = (prim.get("attributes") or {}).get("POSITION")
            if pos is None or pos >= len(accessors):
                continue
            acc = accessors[pos]
            amin, amax = acc.get("min"), acc.get("max")
            if not amin or not amax:
                out["issues"].append("a POSITION accessor has no min/max (the glTF spec requires them)")
                continue
            for corner in ((amin[0], amin[1], amin[2]), (amax[0], amin[1], amin[2]), (amin[0], amax[1], amin[2]),
                           (amin[0], amin[1], amax[2]), (amax[0], amax[1], amin[2]), (amax[0], amin[1], amax[2]),
                           (amin[0], amax[1], amax[2]), (amax[0], amax[1], amax[2])):
                p = to_blender(_apply(m, corner))
                lo = [min(a, b) for a, b in zip(lo, p)]
                hi = [max(a, b) for a, b in zip(hi, p)]
    if lo[0] < math.inf:
        out["dimensions_m"] = [round(h - l, 4) for l, h in zip(lo, hi)]
        out["bounds_m"] = [[round(v, 4) for v in lo], [round(v, 4) for v in hi]]
    if not meshes:
        out["issues"].append("the GLB holds no mesh")
    if meshes and not out["triangles"]:
        out["issues"].append("the GLB's meshes hold no triangles")
    if out["draco"]:
        out["issues"].append("Draco compression is on; Unreal's and the viewer's importers need plain buffers")
    out["checked"] = True
    return out


def check(path, report, tol=0.01):
    """The GLB against the assembler's report.json: its size, its LOD0 triangle count, its sockets and its textures
    must be what was exported. -> the summary plus "expected" and "passed"."""
    s = summarize(path)
    if not s["checked"]:
        s["passed"] = False
        return s
    issues = s["issues"]
    want = report.get("dimensions_m")
    if want and s.get("dimensions_m"):
        got, want_l = sorted(s["dimensions_m"]), sorted(float(v) for v in want)
        if any(abs(g - w) > max(tol * max(w, 1e-3), 0.0005) for g, w in zip(got, want_l)):
            issues.append("the GLB measures %s m; the delivery is %s m" % (s["dimensions_m"], want))
    lods = report.get("lods") or []
    if lods and s["triangles"]:
        want_t = int(lods[0].get("triangles") or 0)
        if want_t and abs(s["triangles"] - want_t) > 0.02 * want_t:
            issues.append("the GLB holds %d triangles; LOD0 was %d" % (s["triangles"], want_t))
    length = max(float(v) for v in want) if want else 1.0
    for q in report.get("sockets") or []:
        name = "SOCKET_" + str(q.get("name"))
        if name not in s["sockets"]:
            issues.append("socket %s is not in the GLB" % name)
            continue
        loc = q.get("location")
        if loc and max(abs(a - b) for a, b in zip(s["sockets"][name], loc)) > max(0.001, 0.005 * length):
            issues.append("socket %s sits at %s in the GLB, %s in the report" % (name, s["sockets"][name], loc))
    if report.get("maps"):
        if not s["images"]:
            issues.append("the GLB carries no textures although %d maps were baked" % len(report["maps"]))
        elif s["images_embedded"] is False:
            issues.append("the GLB references its textures by path instead of embedding them")
    for need in ("NORMAL", "TEXCOORD_0"):
        if s["meshes"] and need not in s["attributes"]:
            issues.append("a primitive has no %s attribute" % need)
    s["expected"] = {"dimensions_m": want, "triangles": (lods[0].get("triangles") if lods else None),
                     "sockets": [q.get("name") for q in report.get("sockets") or []], "maps": len(report.get("maps") or [])}
    s["passed"] = not issues
    return s

"""The delivered GLB read back without Blender (2026-10-04): a GLB built here from bytes, its size, triangles, sockets
and textures compared with a report.json the way `ms assemble` and `ms package` do."""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersmith import glbcheck  # noqa: E402


def write_glb(path, positions, triangles, sockets=(), with_image=True, extra_scene=False, translation=(0, 0, 0)):
    """A one-mesh GLB in glTF's Y-up frame: positions (n, 3), triangles (m, 3), SOCKET_ nodes at translations."""
    pos = struct.pack("<%df" % (len(positions) * 3), *[v for p in positions for v in p])
    nrm = struct.pack("<%df" % (len(positions) * 3), *[v for _p in positions for v in (0.0, 1.0, 0.0)])
    uv = struct.pack("<%df" % (len(positions) * 2), *[v for _p in positions for v in (0.5, 0.5)])
    idx = struct.pack("<%dH" % (len(triangles) * 3), *[i for t in triangles for i in t])
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
    chunks, views, off = [], [], 0
    for data in (pos, nrm, uv, idx, png):
        pad = (4 - len(data) % 4) % 4
        chunks.append(data + b"\x00" * pad)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data)})
        off += len(data) + pad
    blob = b"".join(chunks)
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    doc = {"asset": {"version": "2.0"}, "scene": 0,
           "scenes": [{"nodes": [0] + list(range(1, 1 + len(sockets)))}],
           "nodes": [{"name": "SM_Test", "mesh": 0, "translation": list(translation)}]
                    + [{"name": "SOCKET_" + n, "translation": list(t)} for n, t in sockets],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3,
                                       "material": 0, "mode": 4}]}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3", "min": lo, "max": hi},
                         {"bufferView": 1, "componentType": 5126, "count": len(positions), "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5126, "count": len(positions), "type": "VEC2"},
                         {"bufferView": 3, "componentType": 5123, "count": len(triangles) * 3, "type": "SCALAR"}],
           "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
           "materials": [{"name": "MI_Test", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
           "textures": [{"source": 0}]}
    if with_image:
        doc["images"] = [{"bufferView": 4, "mimeType": "image/png"}]
    if extra_scene:
        doc["scenes"].append({"nodes": []})
    js = json.dumps(doc).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    body = struct.pack("<II", len(js), glbcheck.JSON_CHUNK) + js + struct.pack("<II", len(blob), glbcheck.BIN_CHUNK) + blob
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


# a box 1.0 long (glTF x), 0.2 tall (glTF y), 0.3 wide (glTF z = Blender -y), as two triangles on each of two faces
BOX = [(0, 0, 0), (1, 0, 0), (1, 0.2, 0), (0, 0.2, 0), (0, 0, 0.3), (1, 0, 0.3), (1, 0.2, 0.3), (0, 0.2, 0.3)]
TRIS = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]


def test_summary_reads_size_triangles_sockets_and_textures(tmp_path):
    p = str(tmp_path / "SM_Test.glb")
    write_glb(p, BOX, TRIS, sockets=[("Muzzle", (1.0, 0.1, 0.0))])
    s = glbcheck.summarize(p)
    assert s["checked"] and s["meshes"] == 1 and s["triangles"] == 4 and s["scenes"] == 1
    assert s["dimensions_m"] == [1.0, 0.3, 0.2]                      # Blender frame: length, width, height
    assert s["sockets"] == {"SOCKET_Muzzle": [1.0, 0.0, 0.1]}         # glTF (x, y, z) -> Blender (x, -z, y)
    assert s["images"] == 1 and s["images_embedded"] is True and s["materials"] == ["MI_Test"]
    assert s["attributes"] == ["NORMAL", "POSITION", "TEXCOORD_0"] and not s["issues"]


def test_check_compares_the_file_with_the_report(tmp_path):
    p = str(tmp_path / "SM_Test.glb")
    write_glb(p, BOX, TRIS, sockets=[("Muzzle", (1.0, 0.1, 0.0))], translation=(0.5, 0, 0))
    good = {"dimensions_m": [1.0, 0.3, 0.2], "lods": [{"triangles": 4}], "maps": [{"role": "BC"}],
            "sockets": [{"name": "Muzzle", "location": [1.0, 0.0, 0.1]}]}      # a socket node is a root: unmoved by the mesh node
    chk = glbcheck.check(p, good)
    assert chk["passed"], chk["issues"]
    bad = {"dimensions_m": [1.2, 0.3, 0.2], "lods": [{"triangles": 40}], "maps": [{"role": "BC"}],
           "sockets": [{"name": "Muzzle", "location": [1.0, 0.0, 0.3]}, {"name": "Grip", "location": [0, 0, 0]}]}
    chk = glbcheck.check(p, bad)
    text = " | ".join(chk["issues"])
    assert not chk["passed"]
    for bit in ("measures", "triangles", "SOCKET_Muzzle sits", "SOCKET_Grip is not"):
        assert bit in text, (bit, text)


def test_a_second_scene_missing_textures_and_a_broken_file_are_named(tmp_path):
    p = str(tmp_path / "SM_Test.glb")
    write_glb(p, BOX, TRIS, with_image=False, extra_scene=True)
    chk = glbcheck.check(p, {"maps": [{"role": "BC"}], "lods": [{"triangles": 4}]})
    text = " | ".join(chk["issues"])
    assert "2 scenes" in text and "no textures" in text
    with open(p, "wb") as f:
        f.write(b"glTF\x02\x00\x00\x00")
    chk = glbcheck.check(p, {})
    assert chk["checked"] is False and chk["passed"] is False and "cannot be read" in chk["issues"][0]

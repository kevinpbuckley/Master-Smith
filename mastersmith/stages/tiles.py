"""Issue #7, first step: a tiling PBR material set for environment pieces. Walls, floors and bunkers come out of
image-to-3D with one soft baked atlas; the surface itself (concrete, brick, plaster) is better served by a seamless
tile the engine can layer as detail. Patina turns a crop of the reference picture into basecolor / normal /
roughness / metalness / height tiles. They ship next to the asset as T_<Name>_Tile_*; the Unreal material blends
them over the atlas (docs: README of the package)."""
import os

from PIL import Image

from .. import config
from ..fal import first_url

TILE_MODEL = "fal-ai/patina"
MAP_NAMES = {"basecolor": "BaseColor", "normal": "Normal", "roughness": "Roughness", "metalness": "Metallic", "height": "Height"}


def _crop_surface(reference, out_path):
    """The middle of the reference, square, so the tile is the material and not the silhouette."""
    im = Image.open(reference).convert("RGB")
    w, h = im.size
    side = int(min(w, h) * 0.5)
    box = ((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)
    im.crop(box).resize((1024, 1024)).save(out_path)
    return out_path


def make_tiles(job, reference, out_dir):
    spec = job.spec
    crop = _crop_surface(reference, os.path.join(job.work_dir, "tile_source.png"))
    url = job.fal.upload(crop)
    out = job.fal.run(TILE_MODEL, {"image_url": url, "output_format": "png"})
    files = []
    import json as _json
    with open(os.path.join(job.work_dir, "tiles_result.json"), "w") as f:
        _json.dump(out, f, indent=1, default=str)
    # patina answers {"images": [five files]} in the order of the requested maps (basecolor, normal, roughness,
    # metalness, height), each file possibly carrying a file_name that names its map
    maps = out.get("maps") if isinstance(out.get("maps"), dict) else {}
    if not maps and isinstance(out.get("images"), list):
        order = list(MAP_NAMES)
        for i, im in enumerate(out["images"]):
            if not isinstance(im, dict) or not im.get("url"):
                continue
            fname = str(im.get("file_name") or "").lower()
            key = next((k for k in MAP_NAMES if k in fname or (k == "metalness" and "metal" in fname)), None)
            if key is None and i < len(order):
                key = order[i]
            if key:
                maps[key] = im
    if not maps:
        for k in MAP_NAMES:
            v = out.get(k) or out.get(k + "_map")
            if isinstance(v, dict) and v.get("url"):
                maps[k] = v
    for key, label in MAP_NAMES.items():
        v = maps.get(key)
        u = v.get("url") if isinstance(v, dict) else (v if isinstance(v, str) else None)
        if not u:
            continue
        path = os.path.join(out_dir, "T_%s_Tile_%s.png" % (spec.name, label))
        job.fal.download(u, path)
        files.append(path)
    if not files:
        u = first_url(out, (".png", ".jpg", ".webp"))
        job.log("  tiles: unexpected result shape (%s)" % ", ".join(sorted(out.keys()))[:120])
        if not u:
            return []
    job.log("  tiles: %s" % ", ".join(os.path.basename(f) for f in files))
    return files

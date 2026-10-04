"""The models Master Smith can call, and the owner's choice among them (2026-09-29: "focus on letting user decide which
seeding and models to use"; "we should have command to register local models ... like trellis2").

Built in: the fal endpoints the pipeline has measured, and the two local models on this PC (TRELLIS.2 meshes,
FLUX.2 klein pictures). Registered: any other local model, by the command line that runs it, kept in
local_models.json (machine-specific, git-ignored). `ms models` lists them all with their price; `ms models add`
registers one; `ms seed --model <key>` and `ms picture/view --model <key>` use them.

A seed model takes pictures and returns a GLB: "single" takes one picture, "multiview" takes several named views.
"front" is the axis a vendor's seed usually faces after Blender's glTF import (Mixar's per-engine table, 2026-10-04:
Tripo +X, Hunyuan/TRELLIS/Rodin -Y); registration uses it as a prior to break a tie between the two ends and records
whether the seed agreed (`prior` in registration.json). A segment model splits a registered seed into parts
(`ms segment`) whose labels zones can name.
A command's placeholders: {image} the primary picture, {images} every picture (quoted, space-separated), {out} the
file to write (a .glb for a seed, a .png for a picture), {prompt} and {prompt_file} (pictures), {refs} (pictures'
references), {work} a scratch folder. It must exit 0 and leave {out}."""
import json
import os
import shlex
import subprocess
import tempfile
import time

from . import config, pricing

# key -> what it is. "endpoint" is the fal model id (or the built-in local id); "inputs" single | multiview.
BUILTIN = {
    "hi3d-mv": {"kind": "seed", "label": "Hi3D v3 multi-view (2048)", "endpoint": config.SEED_HI3D_MULTIVIEW, "inputs": "multiview",
                "notes": "M4A1 6.5/10 (2026-09-29); the eight Proteus weapons Ready (2026-09-30); the pick when cost does not matter"},
    "hi3d": {"kind": "seed", "label": "Hi3D v3 (2048)", "endpoint": "hitem3d/hi3d/v3.0/image-to-3d", "inputs": "single",
             "notes": "crisp hard-surface geometry from one picture"},
    "tripo": {"kind": "seed", "label": "Tripo H3.1 detailed", "endpoint": "tripo3d/h3.1/image-to-3d", "inputs": "single",
              "front": "+X", "notes": "tied hi3d-mv on the M4A1 (6.5); from the hero, the Havoc's 9/10 seed; benchmark 5-7 (2026-09-30)"},
    "tripo-mv": {"kind": "seed", "label": "Tripo H3.1 multi-view", "endpoint": "tripo3d/h3.1/multiview-to-3d", "inputs": "multiview",
                 "front": "+X", "notes": "needs front, left, back and right views"},
    "meshy7": {"kind": "seed", "label": "Meshy v7", "endpoint": "fal-ai/meshy/v7/image-to-3d", "inputs": "single", "notes": "cheap"},
    "meshy7-mv": {"kind": "seed", "label": "Meshy v7 multi-image", "endpoint": "fal-ai/meshy/v7/multi-image-to-3d", "inputs": "multiview",
                  "notes": "cheap; up to four pictures in any order"},
    "trellis2": {"kind": "seed", "label": "TRELLIS.2 (this PC)", "endpoint": config.LOCAL_SEED_MODEL, "inputs": "single",
                 "notes": "free, 1.5-6.5 min; soft edges"},
    "hunyuan-part": {"kind": "segment", "label": "Hunyuan3D-Part (P3-SAM)", "endpoint": "fal-ai/hunyuan-3d/v3.1/part",
                     "inputs": "fbx", "notes": "splits a registered seed (sent decimated under 30k faces) into parts; "
                                               "the labels are numbered, named by you after Reading segments.png"},
    "meshy-retexture": {"kind": "texture", "label": "Meshy v5 retexture", "endpoint": "fal-ai/meshy/v5/retexture",
                        "inputs": "single", "notes": "a new texture on every side of the seed, on its own UVs, guided by "
                                                     "the hero picture and the brief (Tonetta's retexture, 2026-09-29)"},
    "nano": {"kind": "picture", "label": "Nano Banana 2", "endpoint": "fal-ai/nano-banana-2", "inputs": "single", "notes": "the default picture model"},
    "nano-pro": {"kind": "picture", "label": "Nano Banana Pro", "endpoint": "fal-ai/nano-banana-pro", "inputs": "single",
                 "notes": "better hero pictures"},
    "flux2-klein": {"kind": "picture", "label": "FLUX.2 klein (this PC)", "endpoint": config.LOCAL_PICTURE_MODEL, "inputs": "single",
                    "notes": "free, weak"},
}
ALIASES = {"local": "trellis2", "hitem3d3": "hi3d", "hitem3d3mv": "hi3d-mv", "local-picture": "flux2-klein"}
SEED_FACES = 200000
# the turn about the vertical (degrees) that brings a vendor's usual front onto the plan frame's +X (forward)
FRONT_YAW = {"+X": 0.0, "-Y": 90.0, "+Y": -90.0, "-X": 180.0}


# the forward end of the object relative to the side the picture shows: a front view faces the camera, a left-side
# view has the forward end on the picture's right (+Y when the pictured side faces +X), a back view faces away
VIEW_TURN = {"front": 0.0, "left": -90.0, "side": -90.0, "right": 90.0, "back": 180.0}


def front_yaw(front, view="front"):
    """Degrees to turn a seed whose PICTURED side faces `front` ("+X" for Tripo) so the object's forward end faces
    +X, given which standard view the picture was (`view`). None when the vendor's front or the view is not known
    (a three-quarter hero says nothing). 2026-10-04: the first draft turned the pictured side to +X and called the
    bullpup's side-view seed wrong: its muzzle lay on +Y, as a side view's must."""
    base = FRONT_YAW.get(str(front).upper()) if front else None
    turn = VIEW_TURN.get(str(view).lower()) if view else None
    if base is None or turn is None:
        return None
    yaw = (base + turn + 180.0) % 360.0 - 180.0
    return 180.0 if yaw == -180.0 else yaw


def registry_path():
    return os.environ.get("MASTERSMITH_MODELS_FILE") or str(config.DATA_DIR / "local_models.json")


def registered(path=None):
    path = path or registry_path()
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def all_models(path=None):
    """Every model: the built-in ones and the registered local ones (a registered key may not shadow a built-in)."""
    out = {k: dict(v, key=k, source="built in") for k, v in BUILTIN.items()}
    for k, v in registered(path).items():
        out[k] = dict(v, key=k, source="local command")
    return out


def resolve(key, kind=None, path=None):
    key = ALIASES.get(key, key)
    models = all_models(path)
    if key not in models:
        raise KeyError("no model %r; `ms models` lists them (%s)" % (key, ", ".join(sorted(k for k, m in models.items() if not kind or m["kind"] == kind))))
    m = models[key]
    if kind and m["kind"] != kind:
        raise KeyError("%s is a %s model, not a %s model" % (key, m["kind"], kind))
    return m


def add(key, kind, command, label="", inputs="single", notes="", path=None, front=None):
    """Register a local command model. -> the entry"""
    if front and str(front).upper() not in FRONT_YAW:
        raise ValueError("front is one of %s" % ", ".join(FRONT_YAW))
    if key in BUILTIN or key in ALIASES:
        raise ValueError("%s is a built-in model name; pick another" % key)
    if kind not in ("seed", "picture"):
        raise ValueError("kind is seed or picture")
    if inputs not in ("single", "multiview"):
        raise ValueError("inputs is single or multiview")
    if "{out}" not in command:
        raise ValueError("the command must write {out}")
    if kind == "seed" and "{image}" not in command and "{images}" not in command:
        raise ValueError("a seed command needs {image} or {images}")
    if kind == "picture" and "{prompt}" not in command and "{prompt_file}" not in command:
        raise ValueError("a picture command needs {prompt} or {prompt_file}")
    path = path or registry_path()
    reg = registered(path)
    reg[key] = {"kind": kind, "label": label or key, "command": command, "inputs": inputs, "notes": notes, "price": 0.0}
    if front:
        reg[key]["front"] = str(front).upper()
    json.dump(reg, open(path, "w", encoding="utf-8"), indent=1)
    return reg[key]


def remove(key, path=None):
    path = path or registry_path()
    reg = registered(path)
    if key not in reg:
        raise KeyError("no registered model %r" % key)
    del reg[key]
    json.dump(reg, open(path, "w", encoding="utf-8"), indent=1)


def fill(command, **values):
    """The command line with its placeholders filled (paths quoted), as an argument list."""
    quoted = {k: (" ".join('"%s"' % x for x in v) if isinstance(v, (list, tuple)) else ('"%s"' % v if k != "prompt" else v))
              for k, v in values.items()}
    text = command
    for k, v in quoted.items():
        text = text.replace("{%s}" % k, v)
    return shlex.split(text, posix=False)


def run_command(m, out, log=print, timeout=3600, **values):
    """Run a registered local model's command; its output file must appear. -> seconds"""
    work = tempfile.mkdtemp(prefix="ms_model_")
    argv = [a.strip('"') for a in fill(m["command"], out=out, work=work, **values)]
    t0 = time.time()
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace")
    secs = round(time.time() - t0, 1)
    if p.returncode != 0 or not os.path.exists(out):
        tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
        raise RuntimeError("%s failed (exit %s): %s" % (m["key"], p.returncode, " | ".join(tail)[:600]))
    log("  %s: %.0fs, $0 (local)" % (m["key"], secs))
    return secs


def seed_views(category, ref_dir, mirror_dir, mirror=False):
    """The approved pictures a whole-object seed is made from, by role: weapons have the side profile as their hero
    (ref_0) and a muzzle view; vehicles and aircraft a three-quarter hero and side, front, back and top views. The far
    side is the side view mirrored (written into mirror_dir) for weapons, or when `mirror` is asked: a vehicle's fuel
    door, hatch or ejection port is one-sided (Anvil's mirror_as_third_view, 2026-09-29).
    -> {"hero", "left", "right", "front", "back", "top"}"""
    from PIL import Image, ImageOps
    pic = lambda name: next((os.path.join(ref_dir, name + e) for e in (".png", ".jpg") if os.path.exists(os.path.join(ref_dir, name + e))), None)
    views = {"hero": pic("ref_0")}
    side = pic("ref_0") if category == "weapon" else (pic("ref_side") or None)
    if side:
        views["left"] = side
    if side and (mirror or category == "weapon"):
        right = os.path.join(mirror_dir, "view_right_mirrored.png")
        ImageOps.mirror(Image.open(side).convert("RGB")).save(right)
        views["right"] = right
    for role in ("front", "back", "top"):
        if pic("ref_" + role):
            views[role] = pic("ref_" + role)
    return {k: v for k, v in views.items() if v}


def seed_payload(m, urls, primary="hero"):
    """(endpoint, payload) for a built-in fal seed model from uploaded view URLs by role."""
    key, ep = m["key"], m["endpoint"]
    if key == "hi3d-mv":
        slots = {"%s_image_url" % r: urls[r] for r in ("front", "left", "back", "right") if r in urls}
        if len(slots) < 2:
            raise ValueError("hi3d-mv needs at least two of the front, side and back views")
        return ep, {**slots, "model": "hi3dv3.0", "resolution": "2048quality", "face_count": SEED_FACES, "enable_texture": True,
                    "enable_pbr": True, "export_format": "glb", "enable_safety_checker": False}
    if key == "tripo-mv":
        missing = [r for r in ("front", "left", "back", "right") if r not in urls]
        if missing:
            raise ValueError("tripo-mv needs front, side and back views; missing %s (ms view --which ...)" % ", ".join(missing))
        return ep, {"image_urls": [urls[r] for r in ("front", "left", "back", "right")], "geometry_quality": "detailed",
                    "texture_quality": "detailed", "pbr": True, "face_limit": 150000}
    if key == "meshy7-mv":
        return ep, {"image_urls": [urls[r] for r in ("hero", "left", "front", "back") if r in urls][:4], "topology": "triangle",
                    "target_polycount": 150000, "symmetry_mode": "auto", "should_remesh": True, "should_texture": True, "enable_pbr": True}
    one = urls.get(primary) or urls.get("hero")
    if key == "hi3d":
        return ep, {"image_url": one, "model": "hi3dv3.0", "resolution": "2048quality", "face_count": SEED_FACES,
                    "enable_texture": True, "enable_pbr": True, "export_format": "glb", "enable_safety_checker": False}
    if key == "tripo":
        return ep, {"image_url": one, "geometry_quality": "detailed", "texture_quality": "detailed", "pbr": True, "face_limit": 150000}
    if key == "meshy7":
        return ep, {"image_url": one, "model_type": "standard", "topology": "triangle", "target_polycount": 150000, "enable_pbr": True}
    if key == "trellis2":
        return ep, {"image_url": one}
    raise ValueError("no payload for %s" % key)


def price_of(m):
    """What one call costs, from the pricing table with the payload the pipeline sends; 0 for a local command."""
    if m.get("source") == "local command" or str(m.get("endpoint", "")).startswith("local/"):
        return 0.0
    if m["kind"] == "picture":
        return pricing.image_price(m["endpoint"])
    if m["kind"] in ("texture", "segment"):
        return pricing.price(m["endpoint"])
    fake = {r: "u" for r in ("hero", "left", "right", "front", "back", "top")}
    try:
        ep, payload = seed_payload(m, fake)
        return pricing.price(ep, payload)
    except Exception:  # noqa: BLE001 - a table row without a price shows as unknown
        return None

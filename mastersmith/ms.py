"""`ms`: Master Smith as a set of small tools for a coding-agent session in this folder. No server, no container, no
model calls of its own - the person (or the agent) looks at the pictures and decides; each command does one
deterministic thing and writes into a job folder under out/<Name>/:

    out/<Name>/brief.json                 what is being built
    out/<Name>/ref/                       reference pictures (ref_0.png the approved side or three-quarter view)
    out/<Name>/plan/                      side.png / front.png (silhouette-cropped), *_grid.png (percent grid), plan.json
    out/<Name>/parts/<Part>/              side.png, quarter.png, seed.glb, registered.blend, registration.json, seed_render.png
    out/<Name>/delivery/                  the assembled asset, previews, preview_views.png (six sides), zip

    python -m mastersmith.ms new BullpupCarbine --category weapon --size 0.68 --description "..."
    python -m mastersmith.ms picture out/BullpupCarbine --out ref/ref_0.png --prompt "..." [--ref photo.jpg] [--model nano|local]
    python -m mastersmith.ms view out/BullpupCarbine --which side|front|back|left --from ref/ref_0.png [--mirror]
    python -m mastersmith.ms grid out/BullpupCarbine --side ref/side.png [--front ref/front.png] [--mirror]
    python -m mastersmith.ms seed out/BullpupCarbine --model hi3d-mv            (the whole object in one request: the default)
    python -m mastersmith.ms models [add <key> --kind seed --command "..." | remove <key>]   (the models, their prices)
    python -m mastersmith.ms plan out/BullpupCarbine plan.json          (plan.json written by hand, see AGENTS.md)
    python -m mastersmith.ms part-pictures out/BullpupCarbine Handguard [--fixes "..."] [--erased] [--no-quarter]
    python -m mastersmith.ms build out/BullpupCarbine TopRail          (a "method": "code" part from parts/TopRail/build.py)
    python -m mastersmith.ms mesh out/BullpupCarbine Handguard [--vendor local|tripo|hitem3d3] [--from quarter|side]
    python -m mastersmith.ms register out/BullpupCarbine Magazine [--from quarter|side] [--yaw 180] [--pitch -30]
    python -m mastersmith.ms fit out/BullpupCarbine Magazine [--quarter]           (outline sculpted onto its pictures)
    python -m mastersmith.ms brush out/BullpupCarbine Grip --op inflate --at back+0,0,-0.02 --radius 12 --strength 2
    python -m mastersmith.ms sdf out/BullpupCarbine Barrel [sdf.py]                 (an exact part from a distance function)
    python -m mastersmith.ms cabin out/HavocGunship Cockpit [--hull Hull]           (the cockpit well measured: the interior's box, fit card)
    python -m mastersmith.ms assemble out/BullpupCarbine [--parts A,B] [--no-sharpen]
    python -m mastersmith.ms sheet path/to/any.glb [--out sheet.png]
    python -m mastersmith.ms refs out/BullpupCarbine out/Other [--no-open]  (reference pictures to approve, ref/review.json)
    python -m mastersmith.ms serve [--restart|--stop]                    (the one local site: every build and job, one port)
    python -m mastersmith.ms preview out/BullpupCarbine [--no-open]   (delivery/preview.html on the site, opened)
    python -m mastersmith.ms results [out/A out/B] [--no-open]     (every delivered job on one page, links to each preview)
    python -m mastersmith.ms package out/BullpupCarbine
    python -m mastersmith.ms status out/BullpupCarbine
    python -m mastersmith.ms mh-conform out/Dryad [--strip hair,lashes] [--extra parts/Head/seed.glb]   (a character seed as the
                                             combined mesh Unreal 5.8's MetaHuman conform takes, checked against the A-pose)
    python -m mastersmith.ms mh-bake out/Dryad --posed delivery/metahuman/in/Dryad_Posed.fbx   (the seed's colour and normal
                                             baked onto the posed MetaHuman mesh Unreal generated from the conformed DNA)
    python -m mastersmith.ms mh-attach out/Dryad Hair --built delivery/metahuman/in/SKM_Dryad_Body.fbx --bone head
"""
import argparse
import glob
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser

from PIL import Image, ImageOps

from . import config, glbcheck, jobs as jobtools, ledger, models, picturecheck, pricing, refs_review, results_page, site
from .fal import Fal, first_url
from .images import Images
from .spec import Spec
from .stages import plan as planmod
from .stages.assembly import THREE_QUARTER_PROMPT, _register, detail_map, erased_body_picture, is_body
from .stages.finish import _blender
from .stages.package import write_package
from .stages.review import six_view_sheet

PICTURE_MODELS = {"nano": "fal-ai/nano-banana-2", "nano-pro": "fal-ai/nano-banana-pro", "local": config.LOCAL_PICTURE_MODEL}
VIEW_TEXT = {
    "side": "the direct LEFT-side profile, camera level with the object, exactly side-on, the forward end (muzzle, nose) "
            "pointing to the RIGHT of the picture, strictly orthographic with no perspective",
    "front": "the direct FRONT view: camera exactly ahead of the forward end, level with the object, strictly orthographic, "
             "looking straight back at it",
    "back": "the direct REAR view: camera exactly behind the object, level with it, strictly orthographic",
    "left": "the direct LEFT-side profile, camera level with the object, exactly side-on, strictly orthographic",
    "top": "the direct TOP view: camera exactly above the object looking straight down, strictly orthographic",
    "quarter": "a three-quarter view: the camera about 35 degrees round from the left side towards the forward end and "
               "about 20 degrees above, so the side, the forward end and the top all show; a long telephoto lens from far "
               "away, almost no perspective",
}


class Pictures:
    """The picture client, plus the owner's registered local picture commands (ms models add): a model given as a
    registry entry is run as its command, anything else goes to Images as before."""

    def __init__(self, images, log):
        self.images, self.log = images, log

    def generate(self, prompt, path, model=None, references=(), aspect_ratio="4:3", **kw):
        if isinstance(model, dict):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            refs = [os.path.abspath(r) for r in (references or []) if r]
            pf = path + ".prompt.txt"
            open(pf, "w", encoding="utf-8").write(prompt)
            secs = models.run_command(model, os.path.abspath(path), log=self.log, prompt=prompt, prompt_file=pf, refs=refs,
                                      image=refs[0] if refs else "", images=refs)
            os.remove(pf)
            return secs
        return self.images.generate(prompt, path, model=model, references=references, aspect_ratio=aspect_ratio, **kw)

    def __getattr__(self, name):
        return getattr(self.images, name)


def _picture_model(key):
    """A picture model key (ms models) -> the id Images takes, or the registered local command's entry."""
    try:
        m = models.resolve(key, kind="picture")
    except KeyError:
        return PICTURE_MODELS.get(key, key)
    return m if m.get("source") == "local command" else m["endpoint"]


class Job:
    """What the stage functions need of a job: a folder, a fal client, a picture client, a log."""

    def __init__(self, folder):
        self.dir = os.path.abspath(folder)
        self.work_dir = self.dir
        self.fal = Fal(log=self.log)
        self.images = Pictures(Images(log=self.log), self.log)
        self.spec = Spec.from_dict(json.load(open(os.path.join(self.dir, "brief.json"))))

    def log(self, msg):
        print(msg, flush=True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


def _plan(job):
    p = json.load(open(job.path("plan", "plan.json")))
    p["side"] = job.path("plan", "side.png")
    p["front"] = job.path("plan", "front.png") if os.path.exists(job.path("plan", "front.png")) else None
    return p


def _part(plan, name):
    for p in plan["parts"]:
        if p["name"].lower() == name.lower():
            return p
    sys.exit("no part %s in the plan (have: %s)" % (name, ", ".join(p["name"] for p in plan["parts"])))


def keep_existing(path, redraw=False):
    """True when a picture is already there and must be kept. 2026-09-28: pictures cost money and were approved by the
    owner; the tools never draw over one. `--redraw` draws again, and only after the owner said so."""
    if redraw or not os.path.exists(path):
        return False
    print("kept: %s already exists (ask the owner; --redraw draws it again)" % path)
    return True


def existing_pictures(folder):
    """Every picture a job already has: the reference pictures and each part's side/quarter picture."""
    found = []
    ref = os.path.join(folder, "ref")
    if os.path.isdir(ref):
        found += [os.path.join("ref", f) for f in sorted(os.listdir(ref)) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    parts = os.path.join(folder, "parts")
    if os.path.isdir(parts):
        for part in sorted(os.listdir(parts)):
            for f in ("side.png", "quarter.png", "build.py"):
                if os.path.exists(os.path.join(parts, part, f)):
                    found.append(os.path.join("parts", part, f))
    return found


# ------------------------------------------------------------------ commands
def cmd_new(a):
    if a.from_file:
        # several briefs at once (the eight Proteus weapons were made by a script in another repo, 2026-09-30):
        # [{"name", "category", "size", "description", "tris"?, "style"?, "engine"?}]
        briefs = json.load(open(a.from_file, encoding="utf-8"))
        for b in briefs.get("briefs", briefs) if isinstance(briefs, dict) else briefs:
            ns = argparse.Namespace(name=b["name"], category=b.get("category", a.category), size=float(b["size"]),
                                    description=b["description"], style=b.get("style", a.style), engine=b.get("engine", a.engine),
                                    tris=int(b.get("tris") or 0), rebrief=a.rebrief, from_file=None)
            cmd_new(ns)
        return
    if not a.name or a.size is None or not a.description:
        sys.exit("ms new <Name> --size <m> --description \"...\" (or --from briefs.json)")
    folder = os.path.join(str(config.OUT_DIR), a.name)
    have = existing_pictures(folder) if os.path.isdir(folder) else []
    if have:
        print("job folder exists with %d pictures/builders already - they are kept; ask the owner before drawing any again:" % len(have))
        for f in have:
            print("  " + f)
        if os.path.exists(os.path.join(folder, "brief.json")) and not a.rebrief:
            print("brief.json kept too (--rebrief rewrites it)")
            return
    os.makedirs(os.path.join(folder, "ref"), exist_ok=True)
    brief = {"name": a.name, "description": a.description, "category": a.category, "style": a.style, "engine": a.engine,
             "tri_budget": a.tris or 0, "size_m": a.size, "multiview": True, "build_mode": "assembly"}
    json.dump(Spec.from_dict(brief).to_dict(), open(os.path.join(folder, "brief.json"), "w"), indent=1)
    print("job folder:", folder)


def cmd_picture(a):
    job = Job(a.job)
    out = job.path(a.out)
    if keep_existing(out, a.redraw):
        return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    refs = [os.path.abspath(r) if os.path.exists(r) else job.path(r) for r in (a.ref or [])]
    model = _picture_model(a.model)
    job.images.generate(a.prompt, out, model=model, references=refs, aspect_ratio=a.aspect)
    usd = job.images.spent() if hasattr(job.images, "spent") else None
    ledger.record(job.dir, "picture", model=a.model, usd=usd, out=a.out)
    print("picture:", out, "($%.2f)" % usd if usd is not None else "")


def cmd_view(a):
    """One standard view of the object in a picture, edited from it so it stays the same object."""
    job = Job(a.job)
    src = job.path(a.src)
    out = job.path(a.out or "ref/ref_%s.png" % a.which)
    if keep_existing(out, a.redraw):
        return
    prompt = ("Show this exact same object from %s. Same object, same design, same colours, markings and materials, same "
              "lighting, plain pure white background, sharp focus, nothing else in frame. %s" % (VIEW_TEXT[a.which], a.fixes or "")).strip()
    job.images.generate(prompt, out, model=_picture_model(a.model), references=[src], aspect_ratio="1:1")
    if a.mirror:
        ImageOps.mirror(Image.open(out).convert("RGB")).save(out)
    ledger.record(job.dir, "view", model=a.model, usd=job.images.spent() if hasattr(job.images, "spent") else None,
                  out=os.path.relpath(out, job.dir), which=a.which)
    print("view:", out)


def cmd_grid(a):
    job = Job(a.job)
    work = job.path("plan")
    os.makedirs(work, exist_ok=True)
    side_src = job.path(a.side)
    if a.mirror:
        m = job.path("plan", "side_mirrored_src.png")
        ImageOps.mirror(Image.open(side_src).convert("RGB")).save(m)
        side_src = m
    side = os.path.join(work, "side.png")
    side_px = planmod.crop_to_object(side_src, side)
    side_g = planmod.draw_grid(side, os.path.join(work, "side_grid.png"))
    if a.front:
        front = os.path.join(work, "front.png")
        front_px = planmod.crop_to_object(job.path(a.front), front)
        dims = planmod.object_dims(job.spec.size_m, side_px, front_px)
        planmod.draw_grid(front, os.path.join(work, "front_grid.png"))
    else:
        dims = (float(job.spec.size_m), float(a.width or job.spec.size_m * side_px[1] / side_px[0] * 0.3),
                float(job.spec.size_m) * side_px[1] / float(side_px[0]))
    if job.spec.category == "nature":
        dims = planmod.longest_side(dims, job.spec.size_m)
    json.dump({"dims_m": [round(v, 4) for v in dims]}, open(os.path.join(work, "dims.json"), "w"))
    print("gridded side view:", side_g)
    if a.front:
        print("gridded front view:", os.path.join(work, "front_grid.png"))
    print("dims L x W x H (m): %.3f x %.3f x %.3f" % dims)
    print("Now write plan.json (see CLAUDE.md) with side_box percents read off the grid, then: ms plan <job> plan.json")


def cmd_plan(a):
    job = Job(a.job)
    dims = json.load(open(job.path("plan", "dims.json")))["dims_m"]
    raw = json.load(open(a.plan if os.path.exists(a.plan) else job.path(a.plan)))
    plan = planmod.validate_plan(raw, dims)
    plan["side"] = job.path("plan", "side.png")
    plan["front"] = job.path("plan", "front.png") if os.path.exists(job.path("plan", "front.png")) else None
    for name, before, after in planmod.snap_to_silhouette(plan):
        print("  %s: thin part, box height read off the picture %.1f%% -> %.1f%%" % (name, before, after))
    for name, was, now in planmod.sample_colours(plan):
        print("  %s: colour read off the picture %s (was %s)" % (name, now, was))
    json.dump(plan, open(job.path("plan", "plan.json"), "w"), indent=1)
    print("plan: %d parts" % len(plan["parts"]))
    for p in plan["parts"]:
        print("  %-22s %-6s %s  %s mm  %s" % (p["name"], p["method"], p["material"]["finish"],
                                              [round((b - x) * 1000) for x, b in zip(p["box_min"], p["box_max"])],
                                              [z["name"] for z in p.get("zones") or []]))
    for d in plan.get("dropped") or []:
        print("  dropped %s: %s" % (d["name"], d["reason"]))
    for w in plan.get("ignored") or []:
        print("  IGNORED %s" % w)
    if plan.get("ignored"):
        print("  %d key(s) or value(s) above were NOT taken: fix the draft (AGENTS.md, The plan JSON) or they do nothing"
              % len(plan["ignored"]))


def cmd_build(a):
    """A code part: parts/<Part>/build.py holds `def build(kit, L, W, H)` (the hard-surface kit, see hskit.py); built in
    its box's own frame, exported as <Part>.blend beside its renders. 2026-09-28: the hybrid build."""
    job = Job(a.job)
    plan = _plan(job)
    part = _part(plan, a.part)
    d = job.path("parts", part["name"])
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "build.py")
    if not os.path.exists(src):
        sys.exit("no builder: write %s with `def build(kit, L, W, H)` (see mastersmith/blender/hskit.py)" % src)
    size = [part["box_max"][i] - part["box_min"][i] for i in range(3)]
    args = {"name": part["name"], "code": open(src, encoding="utf-8").read(), "size": size, "material": part["material"],
            "out_dir": d, "render_size": 512}
    _blender(job, "build_part.py", args, "build_%s" % part["name"])
    res = json.load(open(os.path.join(d, part["name"] + ".json")))
    if not res.get("ok"):
        sys.exit("build failed: %s" % res.get("error"))
    print("built: %s  box %s mm  fill %s  %s tris" % (res["blend"], [round(v * 1000) for v in size], res.get("fill"), res.get("triangles")))
    print("renders: " + ", ".join(os.path.join(d, r) for r in res.get("renders", {}).values()))
    print("Look at the renders next to side.png; edit build.py and build again if it is off.")


def cmd_models(a):
    """The models the pipeline can call, with what one call costs; `add` registers a local model by its command line,
    `remove` drops one (owner, 2026-09-29: the owner picks the seeding and picture models; local ones like TRELLIS.2
    are registered, not coded)."""
    if a.action == "add":
        if not a.key or not a.command:
            sys.exit('usage: ms models add <key> --kind seed|picture --command "exe {image} {out} ..." [--inputs multiview] [--label ...]')
        m = models.add(a.key, a.kind, a.command, label=a.label or "", inputs=a.inputs, notes=a.notes or "", front=a.front)
        print("registered %s (%s, %s): %s -> %s" % (a.key, m["kind"], m["inputs"], m["command"], models.registry_path()))
        return
    if a.action == "remove":
        models.remove(a.key)
        print("removed %s from %s" % (a.key, models.registry_path()))
        return
    rows = sorted(models.all_models().values(), key=lambda m: (m["kind"], m["source"], m["key"]))
    for kind in ("seed", "texture", "segment", "picture"):
        print("%s models (ms %s --model <key>):" % (kind, {"seed": "seed", "texture": "retexture", "segment": "segment"}.get(
            kind, "picture/view/views/part-pictures")))
        for m in (r for r in rows if r["kind"] == kind):
            usd = models.price_of(m)
            front = ("faces %s; " % m["front"]) if m.get("front") else ""
            print("  %-13s %-30s %-9s %-10s %s%s" % (m["key"], m["label"], "free" if usd == 0 else ("$%.2f" % usd if usd else "unpriced"),
                                                     m["inputs"], front, m.get("notes") or m.get("command", "")))
    print("aliases: " + ", ".join("%s = %s" % kv for kv in sorted(models.ALIASES.items())))
    print('register a local model: ms models add <key> --kind seed --command "<exe> {image} {out} ..."')


def cmd_retexture(a):
    """A new texture for the whole seed from a mesh-to-texture model (the owner picks it; Meshy v5 retexture by default),
    painted onto the seed's own UVs and guided by the approved hero picture and the brief: every side gets texture,
    not only the sides the pictures saw (Tonetta's retexture pass, 2026-09-29). The registered mesh goes out with one
    UV layer and no maps, comes back fitted onto its own bounds; registered_before_retexture.blend is the undo."""
    job = Job(a.job)
    m = models.resolve(a.model, kind="texture")
    d = job.path("parts", a.part)
    blend = os.path.join(d, "registered.blend")
    if not os.path.exists(blend):
        sys.exit("no registered seed for %s: ms seed first" % a.part)
    geo = os.path.join(d, "retexture_input.glb")
    _blender(job, "swap_seed.py", {"mode": "export", "blend": blend, "out_glb": geo}, "retexture_export_%s" % a.part)
    if os.path.getsize(geo) > 18 * 1024 * 1024:
        sys.exit("the seed's geometry is %.0f MB; the retexture model takes 18 MB at most" % (os.path.getsize(geo) / 1e6))
    os.environ["MASTERSMITH_NO_SPEND"] = "0"
    config.NO_SPEND = False
    hero = job.path("ref", "ref_0.png")
    payload = {"model_url": job.fal.upload(geo), "text_style_prompt": (a.prompt or job.spec.description)[:600],
               "enable_original_uv": True, "enable_pbr": True, "enable_safety_checker": False}
    if os.path.exists(hero) and not a.no_picture:
        payload["image_style_url"] = job.fal.upload(hero)
    out = job.fal.run(m["endpoint"], payload)
    glb = os.path.join(d, "retextured.glb")
    job.fal.download(first_url(out, (".glb",)), glb)
    ledger.record(job.dir, "retexture", model=a.model, usd=job.fal.spent(), part=a.part)
    print("retextured: %s (%s, $%.2f)" % (glb, m["label"], job.fal.spent()))
    backup = os.path.join(d, "registered_before_retexture.blend")
    if not os.path.exists(backup):
        shutil.copy2(blend, backup)
    res = os.path.join(d, "retexture.json")
    _blender(job, "swap_seed.py", {"mode": "import", "blend": backup, "glb": glb, "out_blend": blend,
                                   "out_render": os.path.join(d, "seed_render.png"), "out_json": res}, "retexture_import_%s" % a.part)
    print("in place: %s (%s); the old mesh is %s. Read seed_render.png, then ms assemble." % (blend, json.load(open(res)), backup))


def cmd_seed(a):
    """The whole object in ONE request (the default since 2026-09-29: one Hi3D v3 multi-view seed of the M4A1 scored
    6.5 against 4.5 for the same model part by part): the approved views go to the model the owner picked, the mesh
    is registered to the gridded side view, and a one-part plan is written when there is none. Zones on that part
    then carry the other materials (glass, bare steel, rubber) and the Blender passes improve it."""
    job = Job(a.job)
    if not os.path.exists(job.path("plan", "side.png")) or not os.path.exists(job.path("plan", "dims.json")):
        sys.exit("grid the approved views first: ms grid %s --side ref/ref_side.png --front ref/ref_front.png" % a.job)
    m = models.resolve(a.model, kind="seed")
    d = job.path("parts", a.part)
    os.makedirs(d, exist_ok=True)
    glb = os.path.join(d, "seed.glb")
    if os.path.exists(glb) and not a.reseed:
        sys.exit("%s already has a seed (%s); --reseed makes a new one (it costs again)" % (a.part, glb))
    views = models.seed_views(job.spec.category, job.path("ref"), d, mirror=a.mirror_far_side)
    primary = a.view or ("left" if job.spec.category == "weapon" else "hero")
    if m.get("source") == "local command":
        pics = [views[r] for r in ("hero", "left", "front", "back", "right", "top") if r in views]
        pics = pics if m["inputs"] == "multiview" else [views.get(primary) or views["hero"]]
        models.run_command(m, glb, image=pics[0], images=pics)
        ledger.record(job.dir, "seed", model=a.model, usd=0.0, part=a.part)
        print("seed: %s (%s, free)" % (glb, m["label"]))
    else:
        if not str(m["endpoint"]).startswith("local/"):
            os.environ["MASTERSMITH_NO_SPEND"] = "0"
            config.NO_SPEND = False
        urls = {r: job.fal.upload(p) for r, p in views.items()}
        ep, payload = models.seed_payload(m, urls, primary)
        used = [k for k in payload if k.endswith("_image_url")] or (["%d views" % len(payload["image_urls"])] if payload.get("image_urls") else [primary])
        out = job.fal.run(ep, payload)
        job.fal.download(first_url(out, (".glb",)), glb)
        ledger.record(job.dir, "seed", model=a.model, usd=job.fal.spent(), part=a.part, views=used)
        print("seed: %s (%s from %s, $%.2f)" % (glb, m["label"], ", ".join(used), job.fal.spent()))
    plan_path = job.path("plan", "plan.json")
    if a.replan or not os.path.exists(plan_path):
        dims = json.load(open(job.path("plan", "dims.json")))["dims_m"]
        finish = {"weapon": "metal", "prop": "painted"}.get(job.spec.category, "painted")
        mat = {"color": "#808080", "finish": finish, "keep_texture": True}
        if job.spec.category == "nature":
            mat.update(metal=False, roughness=0.7)      # skin, leaf, shell and stone: never Tripo's glaze or chrome
        raw = {"parts": [{"name": a.part, "what": job.spec.description[:400], "method": "vendor", "side_box": [0, 100, 0, 100],
                          "front_span": [0, 100], "material": mat}],
               "notes": "one seed for the whole object (%s)" % m["label"]}
        plan = planmod.validate_plan(raw, dims)
        # the pictures, as `ms plan` records them: without them `assemble` straight after a seed stopped on a KeyError
        # and every Training Pool job ran `ms plan` first (2026-10-02)
        plan["side"] = job.path("plan", "side.png")
        plan["front"] = job.path("plan", "front.png") if os.path.exists(job.path("plan", "front.png")) else None
        json.dump(plan, open(plan_path, "w"), indent=1)
        if not os.path.exists(job.path("plan", "plan_draft.json")) or a.replan:
            json.dump(raw, open(job.path("plan", "plan_draft.json"), "w"), indent=1)
        print("plan: one part, %s, keeping the seed's own texture (plan/plan_draft.json)" % a.part)
    shutil.copy2(job.path("plan", "side.png"), os.path.join(d, "side.png"))
    part = _part(_plan(job), a.part)
    seed_view = "front" if m["inputs"] == "multiview" else primary     # a multi-view seed faces its front picture
    _do_register(job, part, d, False, 0, 0, front_yaw=models.front_yaw(m.get("front"), seed_view))
    json.dump({"keep_depth": True}, open(os.path.join(d, "fit.json"), "w"))       # the model saw the depth from its views
    print("Next: Read seed_render.png; add zones to plan/plan_draft.json for the regions in another material (glass, "
          "bare steel, rubber), ms plan, then ms assemble.")


def cmd_part_pictures(a):
    job = Job(a.job)
    plan = _plan(job)
    part = _part(plan, a.part)
    d = job.path("parts", part["name"])
    os.makedirs(d, exist_ok=True)
    side = os.path.join(d, "side.png")
    model = _picture_model(a.model)
    if a.no_side or keep_existing(side, a.redraw):
        print("side picture kept:", side)
    elif a.erased or (is_body(part, plan) and not a.drawn):
        _, erased = erased_body_picture(plan, part, side)
        print("side picture: the approved side view with %s erased -> %s" % (", ".join(erased) or "nothing", side))
    else:
        others = [q["name"] for q in plan["parts"] if q["name"] != part["name"]
                  and all(min(q["box_max"][i], part["box_max"][i]) - max(q["box_min"][i], part["box_min"][i]) > 0 for i in range(3))]
        leave = (" Leave out, they are separate parts: %s." % ", ".join(others)) if others else ""
        if part.get("interior"):
            # a cockpit is drawn as the insert that fills its measured box (ms cabin), from the side view and the hero
            mm = [round((part["box_max"][i] - part["box_min"][i]) * 1000) for i in range(3)]
            hero = job.path("ref", "ref_0.png")
            job.images.generate((INTERIOR_SIDE_PROMPT % (part["what"], mm[0], mm[1], mm[2])) + " " + (a.fixes or ""), side,
                                model=model, references=[plan["side"]] + ([hero] if os.path.exists(hero) else []), aspect_ratio="4:3")
        else:
            job.images.generate("Show ONLY %s from this exact object, whole and complete, exactly as it looks here (same shape, "
                                "colours and materials), seen from exactly the same side angle as this picture with the forward "
                                "end to the right, isolated on a plain pure white background, nothing else in frame, sharp product "
                                "photograph.%s %s" % (part["what"], leave, a.fixes or ""), side, model=model,
                                references=[plan["side"]], aspect_ratio="1:1")
        print("side picture:", side)
        facing = picturecheck.side_facing(plan["side"], part["side_box"], side)
        if facing["mirrored"]:
            # the M4A1's grip was drawn facing backwards and assembled backwards (2026-09-29): turned round here
            os.makedirs(os.path.join(d, "unused"), exist_ok=True)
            shutil.copy2(side, os.path.join(d, "unused", "side_drawn_mirrored.png"))
            ImageOps.mirror(Image.open(side).convert("RGB")).save(side)
            print("  the side picture was drawn facing the other way (match %.2f, mirrored %.2f): turned round; the "
                  "drawing is kept in unused/side_drawn_mirrored.png" % (facing["ncc"], facing["ncc_mirrored"]))
    quarter = os.path.join(d, "quarter.png")
    if not a.no_quarter and not keep_existing(quarter, a.redraw):
        # The whole-object front view makes the model draw the whole object round a part (8 of 13 carbine parts came
        # back as the whole rifle, 2026-09-28; the tank's hull came back with its turret, 2026-09-29): only the body
        # gets it, unless --with-front; and the prompt names the part and says it is drawn alone.
        body = is_body(part, plan)
        front = plan.get("front") if ((body and not a.no_front) or a.with_front) else None
        refs = [side] + ([front] if front else [])
        alone = "" if body else (" Picture 1 shows ONE PART of a larger object, drawn alone: %s. Draw only this part, "
                                 "exactly as picture 1 shows it, and nothing of the object it belongs to (no body, hull, "
                                 "frame, barrel or neighbouring part), its forward end still towards the right." % part["what"])
        job.images.generate(THREE_QUARTER_PROMPT % (alone + (" Picture 2 shows its front end." if front else "")
                                                    + (" " + a.fixes if a.fixes else "")), quarter,
                            model=model, references=refs, aspect_ratio="4:3")
        print("three-quarter picture:", quarter)
    if part.get("interior"):
        box = (part["box_min"], part["box_max"])
        mm = [round((box[1][i] - box[0][i]) * 1000) for i in range(3)]
        print("fit card: %s" % fit_card(plan, part, box, os.path.join(d, "fit_card.png"),
                                        "%s: %d x %d x %d mm (L x W x H) in its box" % (part["name"], mm[0], mm[1], mm[2])))
    if hasattr(job.images, "spent") and job.images.spent():
        ledger.record(job.dir, "part-pictures", model=a.model, usd=job.images.spent(), part=part["name"])
    print("Look at both (Read them). Redraw with --redraw --fixes '...' if the design drifted (ask the owner first).")


def _vendor_payload(vendor, url):
    if vendor.startswith("hitem3d3"):
        return "hitem3d/hi3d/v3.0/image-to-3d", {"image_url": url, "model": "hi3dv3.0", "resolution": "2048quality",
                                                "face_count": 200000, "enable_texture": True, "enable_pbr": True,
                                                "export_format": "glb", "enable_safety_checker": False}
    if vendor == "local":
        return config.LOCAL_SEED_MODEL, {"image_url": url}
    return config.SEED_MODEL, {"image_url": url, "geometry_quality": "detailed", "texture_quality": "detailed", "pbr": True,
                               "face_limit": 150000}


def cmd_mesh(a):
    job = Job(a.job)
    plan = _plan(job)
    part = _part(plan, a.part)
    d = job.path("parts", part["name"])
    pic = os.path.join(d, "quarter.png" if a.src == "quarter" else "side.png")
    if not os.path.exists(pic):
        pic = os.path.join(d, "side.png")
    if not os.path.exists(pic):
        sys.exit("no picture for %s: run part-pictures first" % part["name"])
    if a.vendor != "local":
        os.environ["MASTERSMITH_NO_SPEND"] = "0"
        config.NO_SPEND = False
    model, payload = _vendor_payload(a.vendor, job.fal.upload(pic))
    out = job.fal.run(model, payload)
    mesh_url = first_url(out, (".glb",))
    glb = os.path.join(d, "seed.glb")
    job.fal.download(mesh_url, glb)
    ledger.record(job.dir, "mesh", model=a.vendor, usd=job.fal.spent(), part=part["name"])
    print("mesh: %s (%s, $%.2f)" % (glb, model, job.fal.spent()))
    _do_register(job, part, d, a.src == "quarter" and os.path.exists(os.path.join(d, "quarter.png")), 0, 0)


def _do_register(job, part, d, sweep, yaw, pitch, front_yaw=None):
    side = os.path.join(d, "side.png")
    reg = _register(job, part["name"], os.path.join(d, "seed.glb"), side, d, yaw_sweep=sweep, extra_yaw=yaw, extra_pitch=pitch,
                    front_yaw=front_yaw)
    if not reg:
        print("registration failed (silhouette too different); try --from side or a manual --yaw/--pitch")
        return
    meta = {"keep_depth": bool(sweep)}                       # _register wrote registered.blend into the part folder
    json.dump(meta, open(os.path.join(d, "fit.json"), "w"))
    print("registered: mode %s, silhouette overlap %.2f (runner-up %.2f); render: %s" % (
        reg["mode"], reg["iou"], reg["runner_up_iou"], reg.get("render")))
    if reg.get("prior"):
        # the vendor's usual front (models.py "front", 2026-10-04): a tie-breaker, recorded either way
        pr = reg["prior"]
        verdict = ("agrees" if pr.get("agrees") else "APPLIED to break a tie between the two ends" if pr.get("applied")
                   else "DISAGREES: the silhouette chose the other end; check seed_render.png against side.png")
        print("  vendor front prior (yaw %.0f): %s (IoU %.2f against the best %.2f)" % (pr["front_yaw"], verdict, pr["iou"], pr["best_iou"]))
    print("Look at seed_render.png next to side.png; re-run register with --yaw/--pitch if it sits wrong.")


def cmd_register(a):
    job = Job(a.job)
    part = _part(_plan(job), a.part)
    d = job.path("parts", part["name"])
    _do_register(job, part, d, a.src == "quarter", a.yaw, a.pitch,
                 front_yaw=models.front_yaw(a.front, "left" if a.src == "side" else None))


# ---------------------------------------------------------------- sculpting: fit (#11), sdf (#12), brush (#13)
def _mask_npz(picture, out):
    """The picture's object mask (anything unlike the border), cropped tight, as a signed distance field in pixels
    (+ outside) with its gradient, for blender/fit_part.py. -> path or None when the picture is empty"""
    import numpy as np
    from scipy import ndimage
    a = np.asarray(Image.open(picture).convert("RGB")).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > 0.1
    if fg.mean() < 0.01:
        return None
    fg = ndimage.binary_fill_holes(fg)
    ys, xs = np.nonzero(fg)
    fg = np.pad(fg[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 1, constant_values=False)   # the crop's edge is outside too
    sdf = (ndimage.distance_transform_edt(~fg) - ndimage.distance_transform_edt(fg))[1:-1, 1:-1]
    gy, gx = np.gradient(sdf)
    np.savez(out, sdf=sdf.astype(np.float32), gx=gx.astype(np.float32), gy=gy.astype(np.float32))
    return out


def cmd_fit(a):
    """Deform the registered seed until its outline lies on the part's side picture (and, with --quarter, its
    three-quarter picture at the assumed camera): the sculpting an artist does by eye, done by the picture."""
    job = Job(a.job)
    part = _part(_plan(job), a.part)
    d = job.path("parts", part["name"])
    blend = os.path.join(d, "registered.blend")
    if not os.path.exists(blend):
        sys.exit("no registered mesh for %s: mesh it first" % part["name"])
    views = []
    side = _mask_npz(os.path.join(d, "side.png"), os.path.join(d, "fit_side.npz"))
    if side:
        views.append({"name": "side", "npz": side, "yaw": 0.0, "pitch": 0.0, "weight": 1.0})
    if a.quarter and os.path.exists(os.path.join(d, "quarter.png")):
        q = _mask_npz(os.path.join(d, "quarter.png"), os.path.join(d, "fit_quarter.npz"))
        if q:
            views.append({"name": "quarter", "npz": q, "yaw": 35.0, "pitch": 20.0, "weight": 0.5})
    if not views:
        sys.exit("no picture with an object in it to fit to")
    if not a.no_backup and not os.path.exists(os.path.join(d, "registered_unfitted.blend")):
        shutil.copy2(blend, os.path.join(d, "registered_unfitted.blend"))
    out_json = os.path.join(d, "fit_report.json")
    box_size = [part["box_max"][i] - part["box_min"][i] for i in range(3)]
    _blender(job, "fit_part.py", {"blend": blend, "views": views, "iters": a.iters, "step": a.step, "out_blend": blend, "box_size": box_size,
                                  "mode": "free" if a.free else "lattice",
                                  "out_render": os.path.join(d, "seed_render.png"), "out_json": out_json},
             "fit_%s" % part["name"], timeout=1800)
    rep = json.load(open(out_json))
    for name in rep["iou_before"]:
        print("  %s silhouette overlap %.3f -> %.3f" % (name, rep["iou_before"][name], rep["iou_after"][name]))
    if rep.get("refused"):
        print("fit REFUSED for %s: the surface would turn %.1f deg on average or the outline got no better; the mesh is "
              "unchanged. Re-register, or redraw and re-mesh the part instead." % (part["name"], rep["normal_change_deg"]))
        return
    print("fitted %s (%s): moved up to %.1f mm (mean %.2f), surface turned %.1f deg; render: %s" % (
        part["name"], rep["mode"], rep["max_move_mm"], rep["mean_move_mm"], rep["normal_change_deg"], os.path.join(d, "seed_render.png")))
    print("Look at seed_render.png; registered_unfitted.blend is the mesh before (copy it back to undo).")


def _pct_box(lo, hi, dims):
    """A box in metres -> the plan's percent side_box [x0, x1, z_top, z_bottom] and front_span [y0, y1]."""
    L, W, H = dims
    return ([round((lo[0] + L / 2) / L * 100, 1), round((hi[0] + L / 2) / L * 100, 1),
             round((H / 2 - hi[2]) / H * 100, 1), round((H / 2 - lo[2]) / H * 100, 1)],
            [round((lo[1] + W / 2) / W * 100, 1), round((hi[1] + W / 2) / W * 100, 1)])


def fit_card(plan, part, box, dst, title):
    """The interior's box drawn on the approved side and front views with its size in mm, beside the part's own
    picture: what the cabin looks like and that it fits (owner, 2026-09-29)."""
    from PIL import ImageDraw
    lo, hi = box
    side_box, span = _pct_box(lo, hi, plan["dims_m"])
    mm = [round((hi[i] - lo[i]) * 1000) for i in range(3)]
    panels = []
    for pic, rect, label in ((plan["side"], (side_box[0], side_box[2], side_box[1], side_box[3]), "side: %d x %d mm (L x H)" % (mm[0], mm[2])),
                             (plan.get("front"), (span[0], side_box[2], span[1], side_box[3]), "front: %d x %d mm (W x H)" % (mm[1], mm[2]))):
        if not pic or not os.path.exists(pic):
            continue
        im = Image.open(pic).convert("RGB")
        im.thumbnail((720, 480))
        w, h = im.size
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = (rect[0] / 100 * w, rect[1] / 100 * h, rect[2] / 100 * w, rect[3] / 100 * h)
        for k in range(3):
            d.rectangle((x0 - k, y0 - k, x1 + k, y1 + k), outline=(220, 30, 30))
        d.rectangle((0, h - 22, w, h), fill=(255, 255, 255))
        d.text((6, h - 18), label, fill=(160, 0, 0))
        panels.append(im)
    own = os.path.join(os.path.dirname(dst), "side.png")
    if os.path.exists(own):
        im = Image.open(own).convert("RGB")
        im.thumbnail((480, 480))
        d = ImageDraw.Draw(im)
        d.rectangle((0, im.size[1] - 22, im.size[0], im.size[1]), fill=(255, 255, 255))
        d.text((6, im.size[1] - 18), "%s as drawn" % part["name"], fill=(0, 0, 0))
        panels.append(im)
    width = sum(q.size[0] for q in panels) + 10 * (len(panels) + 1)
    height = max(q.size[1] for q in panels) + 50
    card = Image.new("RGB", (width, height), (245, 246, 248))
    ImageDraw.Draw(card).text((10, 12), title, fill=(0, 0, 0))
    x = 10
    for q in panels:
        card.paste(q, (x, 40))
        x += q.size[0] + 10
    card.save(dst)
    return dst


def cmd_cabin(a):
    """Measure the body's open cockpit well and give the interior part the box that fits it: floor, side walls and
    sill found by rays on the body's registered seed placed as the assembler places it (blender/cabin.py). Prints the
    box in mm and in plan percents and draws parts/<Part>/fit_card.png (owner, 2026-09-29: the cabin's pictures and
    dimensions, so we know it fits)."""
    job = Job(a.job)
    plan = _plan(job)
    part = _part(plan, a.part)
    vendors = [q for q in plan["parts"] if q.get("method") == "vendor" and not q.get("interior")]
    hull = _part(plan, a.hull) if a.hull else max(vendors, key=lambda q: q["box_max"][0] - q["box_min"][0])
    blend = job.path("parts", hull["name"], "registered.blend")
    if not os.path.exists(blend):
        sys.exit("the body %s is not meshed yet (ms mesh %s %s)" % (hull["name"], a.job, hull["name"]))
    fitj = job.path("parts", hull["name"], "fit.json")
    fit = json.load(open(fitj)) if os.path.exists(fitj) else {}
    d = job.path("parts", part["name"])
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "cabin.json")
    # a whole-object seed's canopy is a glass zone on the hull: the assembler carves the seed's own cockpit out under
    # it for an interior part, so the well is measured carved (2026-09-29)
    hm = hull.get("material") or {}
    zones = [dict(z, pick=z.get("pick") or ("auto" if hm.get("keep_texture") else "box")) for z in hull.get("zones") or []
             if ((z.get("material") or {}).get("glass") or (z.get("material") or {}).get("finish") == "glass") and z.get("pick") != "atlas"]
    carve = {"zones": zones, "box_min": part["box_min"], "box_max": part["box_max"]} if zones else None
    _blender(job, "cabin.py", {"hull_blend": blend, "box_min": hull["box_min"], "box_max": hull["box_max"],
                               "keep_depth": bool(fit.get("keep_depth")), "x_range": [part["box_min"][0], part["box_max"][0]],
                               "z_top": part["box_max"][2] if carve else None, "out_json": out, "carve": carve}, "cabin_%s" % part["name"])
    res = json.load(open(out))
    if res.get("carved"):
        print("the seed's own cockpit carved out first (as the assembler will): %s" % res["carved"])
    well = res.get("well")
    if not well:
        sys.exit("no open cockpit well found in %s between x %.2f and %.2f m: the body was meshed closed (redraw its "
                 "picture with the cockpit open) or the interior's box is not over the cockpit"
                 % (hull["name"], part["box_min"][0], part["box_max"][0]))
    glass = [q for q in plan["parts"] if (q.get("material") or {}).get("glass")
             and q["box_min"][0] < well["x"][1] and q["box_max"][0] > well["x"][0]]
    depth = well["sill_z"] - well["floor_z"]
    # seat backs and panel hoods rise above the sill under the glass: the planned top (read off the picture, where the
    # seats show) is kept when it is higher; the rays only know the floor, the walls and the sill
    top = max(well["sill_z"] + 0.6 * depth, part["box_max"][2])
    if glass:
        top = min(top, max(q["box_max"][2] for q in glass) - 0.03 * plan["dims_m"][2])
    margin = 0.04 * well["half_width"]
    lo = [well["x"][0], -well["half_width"] + margin, well["floor_z"] + 0.005 * plan["dims_m"][2]]
    hi = [well["x"][1], well["half_width"] - margin, top]
    side_box, span = _pct_box(lo, hi, plan["dims_m"])
    mm = [round((hi[i] - lo[i]) * 1000) for i in range(3)]
    res["suggested"] = {"box_min": [round(v, 4) for v in lo], "box_max": [round(v, 4) for v in hi], "side_box": side_box,
                        "front_span": span, "size_mm": mm}
    json.dump(res, open(out, "w"), indent=1)
    print("cockpit well in %s: %d mm long, %d mm wide between the walls, %d mm deep (floor to sill)" % (
        hull["name"], round((well["x"][1] - well["x"][0]) * 1000), round(2 * well["half_width"] * 1000), round(depth * 1000)))
    print('%s fits a box of %d x %d x %d mm (L x W x H): "side_box": %s, "front_span": %s' % (part["name"], mm[0], mm[1], mm[2], side_box, span))
    print("  (now: side_box %s, front_span %s). Put the suggested box in plan_draft.json, ms plan, then draw the part." % (
        part["side_box"], part["front_span"]))
    card = fit_card(plan, part, (lo, hi), os.path.join(d, "fit_card.png"),
                    "%s: fits the %s cockpit well, %d x %d x %d mm (L x W x H)" % (part["name"], hull["name"], mm[0], mm[1], mm[2]))
    print("fit card: %s" % card)


INTERIOR_SIDE_PROMPT = ("Show ONLY the cockpit interior of this object as one separate insert: %s. Everything around it - the "
                        "hull, the canopy and its glass and frame - is removed. Draw the tub floor, the seats, the instrument "
                        "panels, the side consoles and the control sticks exactly where they sit in this picture, seen from "
                        "exactly the same side angle with the forward end to the right, isolated on a plain pure white "
                        "background, sharp product photograph. It fills a space %d mm long, %d mm wide and %d mm high.")


ANCHORS = {"centre": (0, 0, 0), "center": (0, 0, 0), "front": (0.5, 0, 0), "back": (-0.5, 0, 0), "top": (0, 0, 0.5),
           "bottom": (0, 0, -0.5), "left": (0, 0.5, 0), "right": (0, -0.5, 0)}


def _point(text, size):
    """x,y,z in metres in the part's frame, or an anchor name (front/back/top/bottom/left/right/centre, at the
    part's box faces), or anchor+dx,dy,dz."""
    base, delta = text, (0.0, 0.0, 0.0)
    if "+" in text:
        base, rest = text.split("+", 1)
        delta = tuple(float(v) for v in rest.split(","))
    if base in ANCHORS:
        p = [ANCHORS[base][i] * size[i] for i in range(3)]
    else:
        p = [float(v) for v in base.split(",")]
    return [p[i] + delta[i] for i in range(3)]


def cmd_brush(a):
    """One brush stroke on the registered mesh, headless: the fix the agent can name after looking at the views.
    Strokes are logged in brush_log.json and replay with --replay after a re-mesh."""
    job = Job(a.job)
    part = _part(_plan(job), a.part)
    d = job.path("parts", part["name"])
    blend = os.path.join(d, "registered.blend")
    if not os.path.exists(blend):
        sys.exit("no registered mesh for %s: mesh it first" % part["name"])
    log_path = os.path.join(d, "brush_log.json")
    log = json.load(open(log_path)) if os.path.exists(log_path) else []
    imported = json.load(open(os.path.join(d, "import.json"))) if os.path.exists(os.path.join(d, "import.json")) else None
    size = (imported or {}).get("size_m") or [part["box_max"][i] - part["box_min"][i] for i in range(3)]
    if a.replay:
        strokes = log
        if not strokes:
            sys.exit("nothing to replay")
    else:
        if not a.op:
            sys.exit("--op is required (one of inflate, move, smooth, flatten, crease)")
        op = {"op": a.op, "at": _point(a.at, size), "radius": a.radius / 1000.0, "strength": a.strength}
        if a.op == "inflate":
            op["strength"] = a.strength / 1000.0                  # mm at the centre
        if a.op == "move":
            op["delta"] = [float(v) / 1000.0 for v in (a.delta or "0,0,0").split(",")]
        if a.op == "crease":
            op["to"] = _point(a.to or a.at, size)
        if a.op == "flatten" and a.normal:
            op["normal"] = [float(v) for v in a.normal.split(",")]
        strokes = [op]
    if not os.path.exists(os.path.join(d, "registered_unbrushed.blend")):
        shutil.copy2(blend, os.path.join(d, "registered_unbrushed.blend"))
    res_path = os.path.join(d, "brush_report.json")
    box_size = [part["box_max"][i] - part["box_min"][i] for i in range(3)]
    _blender(job, "brush.py", {"blend": blend, "strokes": strokes, "out_blend": blend, "box_size": box_size,
                               "out_render": os.path.join(d, "seed_render.png"), "out_json": res_path}, "brush_%s" % part["name"])
    rep = json.load(open(res_path))
    if not a.replay:
        log.extend(strokes)
        json.dump(log, open(log_path, "w"), indent=1)
    print("brushed %s: %d stroke(s) moved %d of %d vertices, up to %.2f mm; render: %s" % (
        part["name"], rep["strokes"], rep["vertices_moved"], rep["vertices"], rep["max_move_mm"], os.path.join(d, "seed_render.png")))
    print("Log: %s (%d strokes). registered_unbrushed.blend is the mesh before the first stroke." % (log_path, len(log)))


def cmd_sdf(a):
    """An exact part from a signed distance function: parts/<Part>/sdf.py defines `part(kit, L, W, H)` (see
    mastersmith/sdfkit.py); meshed inside the part's box, imported as registered.blend with the planned material."""
    from . import sdfkit
    job = Job(a.job)
    plan = _plan(job)
    part = _part(plan, a.part)
    d = job.path("parts", part["name"])
    os.makedirs(d, exist_ok=True)
    src = a.script if a.script and os.path.exists(a.script) else os.path.join(d, "sdf.py")
    if not os.path.exists(src):
        sys.exit("no script: write %s with `def part(kit, L, W, H)` returning a kit shape (see mastersmith/sdfkit.py)" % src)
    L, W, H = [part["box_max"][i] - part["box_min"][i] for i in range(3)]
    shape = sdfkit.run_part_script(open(src, encoding="utf-8").read(), L, W, H)
    voxel = (a.voxel / 1000.0) if a.voxel else min(max(max(L, W, H) / 320.0, 0.00015), 0.001)
    half = [L / 2, W / 2, H / 2]
    verts, faces = sdfkit.mesh(shape, [-h for h in half], half, voxel)
    glb = os.path.join(d, "seed.glb")
    sdfkit.write_glb(verts, faces, glb)
    print("sdf mesh: %d tris at %.2f mm voxels -> %s" % (len(faces), voxel * 1000, glb))
    _blender(job, "import_part.py", {"glb": glb, "material": part["material"], "name": part["name"],
                                     "out_blend": os.path.join(d, "registered.blend"),
                                     "out_render": os.path.join(d, "seed_render.png"), "out_json": os.path.join(d, "import.json")},
             "import_%s" % part["name"])
    rep = json.load(open(os.path.join(d, "import.json")))
    json.dump({"keep_depth": False}, open(os.path.join(d, "fit.json"), "w"))
    if os.path.abspath(src) != os.path.abspath(os.path.join(d, "sdf.py")):
        shutil.copy2(src, os.path.join(d, "sdf.py"))
    for p in plan["parts"]:
        if p["name"] == part["name"]:
            p["method"] = "sdf"
    plan_out = {k: v for k, v in plan.items() if k not in ("side", "front")}
    json.dump(plan_out, open(job.path("plan", "plan.json"), "w"), indent=1)
    print("imported: %d tris, %s mm (box %s mm); render: %s" % (rep["triangles"], [round(v * 1000, 1) for v in rep["size_m"]],
                                                                [round(v * 1000) for v in (L, W, H)], os.path.join(d, "seed_render.png")))
    print("Look at seed_render.png next to side.png; edit sdf.py and run again if it is off.")


def fill_small_holes(fg, max_frac=0.002):
    """An object mask with its specks of noise filled but its real openings kept: every enclosed background region
    bigger than `max_frac` of the object stays a hole. Filling every hole printed the picture's white background as a
    pale patch inside a trigger guard and a front-sight window (the shotgun, the M4A1, 2026-09-29)."""
    import numpy as np
    from scipy import ndimage
    fg = np.asarray(fg, bool)
    holes = ndimage.binary_fill_holes(fg) & ~fg
    lab, n = ndimage.label(holes)
    if not n:
        return fg
    sizes = ndimage.sum(holes, lab, np.arange(1, n + 1))
    small = np.concatenate([[False], sizes <= max_frac * max(int(fg.sum()), 1)])
    return fg | small[lab]


def _proj_picture(src, dst, crop=True):
    """A picture as the projection wants it: cropped to its object (unless it already is), its alpha the object's
    mask (specks filled, openings kept, a pixel eroded so the white fringe never lands on the mesh). -> (dst, (w, h)) or None"""
    import numpy as np
    from scipy import ndimage
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255.0
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    fg = np.abs(a - np.median(border, axis=0)).max(axis=2) > 0.1
    if fg.mean() < 0.005:
        return None
    fg = fill_small_holes(fg)
    if crop:
        ys, xs = np.nonzero(fg)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        a, fg = a[y0:y1, x0:x1], fg[y0:y1, x0:x1]
    fg = ndimage.binary_erosion(fg, iterations=max(1, min(a.shape[:2]) // 400))
    # a product shot is lit: its shadowed lower half projected as a dark blotch on the part (2026-09-28). The
    # low-frequency luminance is flattened towards the object's mean (half strength, so a real dark panel stays
    # darker than a light one); hue, colour breaks and fine detail are untouched.
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    sigma = max(a.shape[:2]) * 0.08
    m = fg.astype(np.float32)
    low = ndimage.gaussian_filter(lum * m, sigma) / np.maximum(ndimage.gaussian_filter(m, sigma), 1e-3)
    mean = float(lum[fg].mean()) if fg.any() else 0.5
    gain = np.clip((mean / np.maximum(low, 1e-3)) ** 0.5, 0.6, 1.6)
    a = np.clip(a * gain[:, :, None], 0, 1)
    rgba = np.dstack([a, fg.astype(np.float32)])
    Image.fromarray((rgba * 255).astype("uint8"), "RGBA").save(dst)
    return dst, (a.shape[1], a.shape[0])


def _mean_linear(rgba_path):
    """The mean colour (linear RGB) of a projection picture's object pixels (its alpha is the object's mask)."""
    import numpy as np
    a = np.asarray(Image.open(rgba_path).convert("RGBA")).astype(np.float32) / 255.0
    m = a[:, :, 3] > 0.5
    if m.sum() < 100:
        return None
    rgb = a[:, :, :3][m]
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    # and its mean chroma (max - min of the sRGB values): how colourful the object is, for the saturation match
    return [round(float(v), 5) for v in lin.mean(axis=0)] + [round(float((rgb.max(axis=1) - rgb.min(axis=1)).mean()), 5)]


def _projection_inputs(job, plan, parts):
    """What assemble.py projects (#14): the approved side and front views for every part (with their high-pass
    detail maps), and each part's own side picture when it has one, in its own frame - or the asset's frame when
    it is the erased body picture (same size as the plan's side view)."""
    side_size = Image.open(plan["side"]).size
    out = {"strength": 0.85, "mode": "full"}
    ps = _proj_picture(plan["side"], job.path("plan", "proj_side.png"), crop=False)
    if ps:
        out["side"] = ps[0]
        out["side_detail"] = detail_map(plan["side"], job.path("plan", "detail_side.png"))
        out["side_mean_linear"] = _mean_linear(ps[0])
    if plan.get("front"):
        pf = _proj_picture(plan["front"], job.path("plan", "proj_front.png"), crop=False)
        if pf:
            out["front"] = pf[0]
            out["front_detail"] = detail_map(plan["front"], job.path("plan", "detail_front.png"))
    for entry in parts:
        d = job.path("parts", entry["name"])
        side = os.path.join(d, "side.png")
        if not os.path.exists(side) or (entry.get("material") or {}).get("glass"):
            continue
        whole = Image.open(side).size == side_size
        pp = _proj_picture(side, os.path.join(d, "proj_side.png"), crop=not whole)
        if pp:
            entry["projection"] = {"picture": pp[0], "frame": "asset" if whole else "part",
                                   "detail": detail_map(pp[0], os.path.join(d, "detail_side.png"))}
    return out


def cmd_assemble(a):
    job = Job(a.job)
    plan = _plan(job)
    nature = job.spec.category == "nature"
    if nature:
        # a fish, a kelp, a coral or a rock is no machined part: the sharpening, the baked bevel, the code edge break, the
        # metal and polymer smart materials and the cast-surface grain each damaged one of the Training Pool pilots
        # (2026-10-02: glossy creases on the fish, grain on the leaves); its size is its longest side
        # nor the picture projection and its colour grade: a plant on white read as a pale blue picture and the grade
        # washed the gold-olive kelp to grey (saturation x0.69, blue x1.36, 2026-10-03)
        a.no_sharpen = a.no_bevel = a.no_edge_break = a.no_materials = a.no_surface_detail = a.no_projection = True
        print("nature: no sharpening, bevel, edge break, smart materials, surface grain or picture projection; sized by "
              "its longest side")
    want = [p.strip().lower() for p in a.parts.split(",")] if a.parts else None
    # the body is the biggest box by volume: by length alone an all-diffused rifle's barrel (334 mm, 17 mm across) was
    # taken for the body, kept in its short seed's proportions and vanished inside the handguard (2026-09-29)
    largest = max(plan["parts"], key=lambda q: (q["box_max"][0] - q["box_min"][0]) * (q["box_max"][1] - q["box_min"][1])
                  * (q["box_max"][2] - q["box_min"][2]))
    parts = []
    for p in plan["parts"]:
        if want and p["name"].lower() not in want:
            continue
        d = job.path("parts", p["name"])
        if p.get("method") == "code":
            blend = os.path.join(d, p["name"] + ".blend")
            if not os.path.exists(blend):
                print("  %s: not built yet (ms build), left out" % p["name"])
                continue
            skin = os.path.join(d, "registered.blend")
            if p.get("skin") and not os.path.exists(skin):
                print("  %s: \"skin\" asked for but not meshed yet (ms part-pictures, then ms mesh); built as is" % p["name"])
            parts.append({"name": p["name"], "kind": "code", "box_min": p["box_min"], "box_max": p["box_max"], "material": p["material"],
                          "centreline": bool(p.get("centreline")), "zones": [], "blend": blend, "yaw": 0,
                          "reference_detail": bool(p.get("reference_detail", True)), "edge_break": bool(p.get("edge_break", True)),
                          "skin": skin if p.get("skin") and os.path.exists(skin) else None})
            continue
        blend = os.path.join(d, "registered.blend")
        if not os.path.exists(blend):
            print("  %s: not meshed yet, left out" % p["name"])
            continue
        fit = json.load(open(os.path.join(d, "fit.json"))) if os.path.exists(os.path.join(d, "fit.json")) else {}
        is_largest = p["name"] == largest["name"]
        parts.append({"name": p["name"], "kind": "vendor", "box_min": p["box_min"], "box_max": p["box_max"], "material": p["material"],
                      "fitted": os.path.exists(os.path.join(d, "fit_report.json")), "interior": bool(p.get("interior")), "body": is_largest,
                      "centreline": bool(p.get("centreline")), "zones": p.get("zones") or [], "blend": blend, "yaw": 0,
                      "carve": bool(p.get("carve")) and not is_largest, "no_projection": bool(p.get("no_projection")),
                      "keep_depth": bool(fit.get("keep_depth")) and is_largest, "fill_box": not is_largest,
                      "lettering": p.get("lettering") or []})
    if not parts:
        sys.exit("nothing to assemble")
    delivery = job.path("delivery")
    os.makedirs(delivery, exist_ok=True)
    det = {"side": detail_map(plan["side"], job.path("plan", "detail_side.png")), "front": None, "dims": plan["dims_m"], "strength": 0.5}
    if plan.get("front"):
        det["front"] = detail_map(plan["front"], job.path("plan", "detail_front.png"))
    ref = job.path("ref", "ref_0.png")
    mode = "off" if a.no_projection else a.projection
    projection = None if mode == "off" else dict(_projection_inputs(job, plan, parts), mode=mode)
    pbr_library = {}
    if not a.no_materials:
        from . import materials
        pbr_library = materials.library_for(plan["parts"], log=print)      # names each part's and zone's set
        by_name = {p["name"]: p for p in plan["parts"]}
        for entry in parts:
            entry["pbr_set"] = by_name[entry["name"]].get("pbr_set")
            entry["zones"] = by_name[entry["name"]].get("zones") or []
    args = {"name": job.spec.name, "out_dir": delivery, "tri_budget": job.spec.tri_budget or 100000, "engine": job.spec.engine,
            "projection": projection, "pbr_library": pbr_library, "length_m": plan["dims_m"][0],
            "atlas_size": 4096 if (job.spec.tri_budget or 0) >= 100000 else 2048, "render_size": 768, "spec": job.spec.to_dict(),
            "reference": ref if os.path.exists(ref) else None, "parts": parts, "detail": det, "sharpen": not a.no_sharpen,
            # a machined edge's break: 0.08% of the asset's length (0.7 mm on a rifle, 12 mm on a helicopter), capped per part
            "edge_break_m": 0.0 if a.no_edge_break else 0.0008 * float(plan["dims_m"][0]),
            # every edge's small round, baked into the normal map from the Bevel shader (Tonetta: a razor edge reads
            # as fake, 2026-09-29): 0.2% of the asset's length
            # 2026-09-30: the restrained profile is the default (0.05% of the length, at most 1.5 mm): 0.2% grew to
            # 28 mm on the 14 m Havoc and, with the stacked 1 mm bumps and glossy edge wear, read as melted ("gooey")
            "bevel_m": 0.0 if a.no_bevel else (min(0.0015, 0.0005 * float(plan["dims_m"][0]))
                if a.finish_profile == "restrained" else 0.002 * float(plan["dims_m"][0])),
            "finish_profile": a.finish_profile, "drop_floaters": bool(a.drop_floaters), "origin": a.origin,
            "draft": bool(a.draft), "tubes": a.tubes, "surface_detail": not a.no_surface_detail, "size_longest": nature,
            "wind_masks": nature}
    _blender(job, "assemble.py", args, "assemble_draft" if a.draft else "assemble")
    if a.draft:
        d = os.path.join(delivery, "draft")
        rep = json.load(open(os.path.join(d, "report.json")))
        print("draft (no bake, LODs or exports; the delivery is untouched) -> %s" % d)
        for z in rep.get("glass_zones") or []:
            print("  glass %s: %s" % (z.get("zone"), {k: z.get(k) for k in ("mode", "faces", "coverage", "share_of_part", "ok")}))
        for r in rep.get("parts") or []:
            for k in ("pokes_out", "pokes_into_body", "islands"):
                if k in r:
                    print("  %s %s: %s" % (r["name"], k, r[k]))
        if rep.get("muzzle") is not None:
            print("  muzzle: %s; sockets %s" % (rep["muzzle"], [s["name"] for s in rep.get("sockets") or []]))
        print("  renders: " + ", ".join(os.path.join(d, r) for r in rep.get("renders") or []))
        print("Read the renders; run the full assemble (no --draft) once the boxes and picks are right.")
        return
    rep = json.load(open(os.path.join(delivery, "report.json")))
    _glb_gate(job, delivery, rep)
    sheet = six_view_sheet(job, delivery)
    print("assembled %d parts -> %s" % (len(parts), delivery))
    print("  size %s m, LOD0 %s tris, origin %s" % (rep.get("dimensions_m"), (rep.get("lods") or [{}])[0].get("triangles"),
                                                    (rep.get("origin") or {}).get("mode", "centre")))
    if rep.get("texel_density"):
        td = rep["texel_density"]
        print("  texel density: %s px/cm mean (10th percentile %s), %.0f%% of the %s px atlas used" % (
            td.get("px_per_cm"), td.get("p10_px_per_cm"), (td.get("atlas_used") or 0) * 100, td.get("atlas_px")))
    if rep.get("glb_check"):
        print("  GLB read back: %s" % _glb_line(rep["glb_check"]))
    if rep.get("sockets"):
        print("  sockets (SOCKET_ in the FBX, metres): " + ", ".join("%s %s" % (s["name"], s["location"]) for s in rep["sockets"]))
    if rep.get("muzzle") is not None:
        print("  muzzle: %s" % rep["muzzle"])
    for w in (rep.get("gate") or {}).get("warnings") or []:
        print("  gate: " + w)
    print("  previews: " + ", ".join(os.path.join(delivery, r) for r in rep["renders"] + (rep.get("detail_renders") or [])))
    print("  six views: %s" % sheet)
    write_preview(job)
    url = _preview_url(job)
    print("  preview: %s" % url)
    print("Now LOOK at the six views and the previews (Read them) before calling it good, and put the preview link in "
          "the message.")


PREVIEW_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>%(name)s</title>
<script type="module" src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
 body{margin:0;font:14px/1.4 system-ui,sans-serif;background:#1c1d20;color:#ddd}
 h1{font-size:20px;margin:0 0 4px} h2{font-size:15px;margin:24px 0 8px;color:#9ab} small{color:#999}
 header,section{padding:16px 24px} header{background:#26272b;border-bottom:1px solid #333}
 model-viewer{width:100%%;height:70vh;background:#5d6066;border-radius:6px}
 .row{display:flex;flex-wrap:wrap;gap:12px} .row img{max-width:360px;background:#fff;border-radius:4px}
 .sheet{width:100%%;max-width:1536px}
 table{border-collapse:collapse;width:100%%} td,th{padding:6px 8px;border-bottom:1px solid #333;vertical-align:top;text-align:left}
 td img{height:150px;background:#fff;border-radius:4px;margin-right:4px} .lod button{margin-right:6px}
</style></head><body>
%(nav)s<header><h1>%(name)s</h1><small>%(desc)s</small><br><small>%(dims)s m &middot; LOD0 %(tris)s tris &middot; %(nparts)d parts &middot; %(engine)s</small></header>
<section>
<model-viewer id="mv" src="%(glb)s" camera-controls camera-orbit="-35deg 78deg 110%%" exposure="1.3" shadow-intensity="0.6" environment-image="neutral" alt="%(name)s"></model-viewer>
<div class="lod" style="margin-top:8px">%(lods)s <button onclick="mv.autoRotate=!mv.autoRotate">rotate</button></div>
</section>
<section><h2>Six views</h2>%(sheet)s</section>
<section><h2>Previews</h2><div class="row">%(previews)s</div></section>
<section><h2>Reference and plan</h2><div class="row">%(refs)s</div></section>
<section><h2>Parts: picture the mesher got, side picture it was registered to, the seed as registered</h2>
<table><tr><th>part</th><th>pictures</th><th>seed</th><th>registration</th></tr>%(parts)s</table></section>
<script>const mv=document.getElementById('mv');function lod(f){mv.src=f}</script>
</body></html>"""


def write_preview(job):
    """delivery/preview.html: the GLB in a <model-viewer>, the six views, the previews, the reference pictures and
    every part's pictures beside its registered seed. Relative links, so the page needs the job folder served
    (`ms preview`): a browser will not fetch a GLB from file://."""
    delivery = job.path("delivery")
    rep = json.load(open(os.path.join(delivery, "report.json")))
    name = job.spec.name
    lods = [g for g in sorted(glob.glob(os.path.join(delivery, "SM_%s*.glb" % name)))]
    # every file link carries its mtime: a tab left open on an earlier preview kept showing the old GLB after a
    # re-assemble, and the owner reviewed a fix that was not on screen (2026-09-29)
    lod_buttons = "".join("<button onclick=\"lod('%s')\">%s</button>" % (os.path.basename(g) + "?v=%d" % int(os.path.getmtime(g)),
                                                                          os.path.basename(g)[len("SM_%s" % name):-4].strip("_") or "LOD0")
                          for g in lods)
    rel = lambda path: os.path.relpath(path, delivery).replace(os.sep, "/")
    imgs = lambda paths: "".join('<a href="%s"><img src="%s" title="%s"></a>' % (rel(p), rel(p) + "?v=%d" % int(os.path.getmtime(p)), os.path.basename(p)) for p in paths if os.path.exists(p))
    previews = [os.path.join(delivery, r) for r in (rep.get("renders") or []) + (rep.get("detail_renders") or [])]
    refs = sorted(glob.glob(job.path("ref", "*.png"))) + [job.path("plan", "side_grid.png"), job.path("plan", "front_grid.png")]
    rows = []
    plan = _plan(job) if os.path.exists(job.path("plan", "plan.json")) else {"parts": []}
    for p in plan["parts"]:
        d = job.path("parts", p["name"])
        reg = json.load(open(os.path.join(d, "registration.json"))) if os.path.exists(os.path.join(d, "registration.json")) else {}
        mm = [round((b - x) * 1000) for x, b in zip(p["box_min"], p["box_max"])]
        rows.append("<tr><td><b>%s</b><br><small>%s<br>%s mm, %s %s</small></td><td>%s</td><td>%s</td><td><small>%s</small></td></tr>" % (
            p["name"], p["what"][:160], mm, p["material"]["finish"], p["material"]["color"],
            imgs([os.path.join(d, "quarter.png"), os.path.join(d, "side.png")]), imgs([os.path.join(d, "seed_render.png")]),
            ("%s, IoU %.2f" % (reg.get("mode"), reg.get("iou", 0))) if reg else "not meshed"))
    sheet = os.path.join(delivery, "preview_views.png")
    folder = os.path.basename(job.dir)
    html = PREVIEW_HTML % {
        "nav": site.nav("", '<a href="/refs?jobs=%s" style="color:#bcd3ec">%s references</a>' % (folder, folder)),
        "name": name, "desc": job.spec.description, "dims": " x ".join("%.3f" % v for v in rep.get("dimensions_m") or []),
        "tris": format((rep.get("lods") or [{}])[0].get("triangles", 0), ","), "nparts": len(plan["parts"]), "engine": job.spec.engine,
        "glb": (os.path.basename(lods[0]) + "?v=%d" % int(os.path.getmtime(lods[0]))) if lods else "", "lods": lod_buttons,
        "sheet": '<a href="preview_views.png"><img class="sheet" src="preview_views.png?v=%d"></a>' % int(os.path.getmtime(sheet)) if os.path.exists(sheet) else "<small>not rendered</small>",
        "previews": imgs(previews), "refs": imgs(refs), "parts": "".join(rows)}
    out = os.path.join(delivery, "preview.html")
    open(out, "w", encoding="utf-8").write(html)
    return out


def _preview_url(job):
    """The job's live preview on the one site (started when it is not running): every delivery message carries it
    (owner, 2026-09-29: "where's my preview link?"; `assemble` printed only a file path)."""
    out_dir = os.path.abspath(str(config.OUT_DIR))
    if os.path.normcase(os.path.dirname(job.dir)) == os.path.normcase(out_dir):
        # every job on the one site and port (owner, 2026-09-29), with its nav bar back to all the builds
        return _serve_out(out_dir) + "/%s/delivery/preview.html" % os.path.basename(job.dir)
    # a job outside out/ (a scratch copy) gets a small static server of its own
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", job.dir],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return "http://127.0.0.1:%d/delivery/preview.html" % port


def cmd_preview(a):
    job = Job(a.job)
    if not os.path.exists(job.path("delivery", "report.json")):
        sys.exit("nothing assembled yet: ms assemble %s first" % a.job)
    page = write_preview(job)
    url = _preview_url(job)
    print("preview: %s  (%s)" % (url, page))
    if not a.no_open:
        webbrowser.open(url)


def cmd_refs(a):
    """Several jobs' reference pictures on one local page with Approve / Redraw and a note per picture, kept in each
    job's ref/review.json (2026-09-29: the owner approves a batch of references in one sitting)."""
    out_dir = str(config.OUT_DIR)
    jobs = [os.path.basename(os.path.normpath(j)) for j in a.jobs] or refs_review.all_jobs(out_dir)
    for j in jobs:
        if not os.path.isfile(os.path.join(out_dir, j, "brief.json")):
            sys.exit("no job %s in %s" % (j, out_dir))
    if a.sheet:
        # the agent's own look before the owner's: one picture per job it can Read (2026-10-01: 9 of 38 redrawn)
        for j in jobs:
            cat = json.load(open(os.path.join(out_dir, j, "brief.json"), encoding="utf-8")).get("category")
            path, warns = picturecheck.contact_sheet(os.path.join(out_dir, j), cat, os.path.join(out_dir, j, "ref_sheet.png"))
            print("sheet: %s" % path)
            for w in warns:
                print("  check: %s" % w)
        print(picturecheck.REF_CHECKLIST)
        if a.no_open:
            return
    url = _serve_out(out_dir) + "/refs" + (("?jobs=" + ",".join(jobs)) if a.jobs else "")
    print("reference review: %s  (%d jobs)" % (url, len(jobs)))
    print("choices land in out/<Name>/ref/review.json; read them before building")
    if not a.no_open:
        webbrowser.open(url)


def cmd_results(a):
    """Every delivered job on one local page: six views, score and defects (delivery/scorecard.json), cost, and links
    to its 3D preview, GLB and zip (2026-09-29: the owner reviews a batch of builds from one page)."""
    out_dir = str(config.OUT_DIR)
    jobs = [os.path.basename(os.path.normpath(j)) for j in a.jobs] or results_page.delivered_jobs(out_dir)
    for j in jobs:
        if not os.path.isfile(os.path.join(out_dir, j, "delivery", "report.json")):
            sys.exit("nothing assembled yet in %s" % j)
    url = _serve_out(out_dir) + "/results" + (("?jobs=" + ",".join(jobs)) if a.jobs else "")
    print("builds: %s  (%d jobs; the home page %s lists them all)" % (url, len(jobs), _serve_out(out_dir) + "/"))
    if not a.no_open:
        webbrowser.open(url)


def _serve_out(out_dir, restart=False):
    """The one local site (site.py) on config.PREVIEW_PORT, serving out/: started when it is not running, restarted
    when its code changed. Every preview, the builds page and the reference review are on it (owner, 2026-09-29: "all
    previews always on same port"). Returns the base URL."""
    return site.ensure(out_dir, config.PREVIEW_PORT, config.ROOT, restart=restart)


def cmd_serve(a):
    """The site's home page: every build and job with links (the one port for everything)."""
    out_dir = str(config.OUT_DIR)
    if a.stop:
        p = site._ping(config.PREVIEW_PORT)
        if p:
            try:
                import urllib.request
                urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/stop" % config.PREVIEW_PORT, data=b"{}",
                                                              method="POST"), timeout=2)
            except Exception:  # noqa: BLE001 - it exits while answering
                pass
        print("stopped" if p else "not running")
        return
    url = _serve_out(out_dir, restart=a.restart) + "/"
    print("site: %s  (builds %sresults, references %srefs)" % (url, url, url))
    if not a.no_open:
        webbrowser.open(url)


def cmd_views(a):
    """Several standard views from ONE picture call (2026-10-04, Mixar's turnaround sheet as the prompt): a sheet of
    panels drawn from the hero and split into ref/ref_<view>.png. One call instead of one per view keeps every
    view the same object and costs a quarter. A panel with nothing in it, or whose object bleeds into its
    neighbour, is refused by name and left to `ms view`, never cropped as if it were fine (Mixar: a multi-view
    submit refuses loudly rather than degrading to one picture)."""
    job = Job(a.job)
    src = job.path(a.src)
    which = [w.strip().lower() for w in a.which.split(",") if w.strip()]
    bad = [w for w in which if w not in VIEW_TEXT or w == "quarter"]
    if bad or not which:
        sys.exit("--which takes a comma list of %s" % ", ".join(sorted(k for k in VIEW_TEXT if k != "quarter")))
    outs = {w: job.path("ref", "ref_%s.png" % w) for w in which}
    todo = {w: p for w, p in outs.items() if not keep_existing(p, a.redraw)}
    if not todo:
        return
    n = len(todo)
    rows, cols = (1, n) if n <= 2 else ((2, 2) if n <= 4 else (2, 3))
    aspect = {(1, 1): "1:1", (1, 2): "16:9", (2, 2): "1:1", (2, 3): "4:3"}[(rows, cols)]
    order = list(todo)
    panels = "; ".join("panel %d (row %d, column %d): %s" % (i + 1, i // cols + 1, i % cols + 1, VIEW_TEXT[w])
                       for i, w in enumerate(order))
    prompt = ("A turnaround reference sheet of this exact same object: %d panels in a grid of %d row%s and %d column%s on "
              "one plain pure white background, wide empty white gutters between the panels, the whole object inside each "
              "panel touching nothing, no labels, no text, no frames, no lines, no shadows. Same object, same design, same "
              "colours, markings and materials in every panel; each panel strictly orthographic with no perspective. %s. %s"
              % (n, rows, "s" if rows > 1 else "", cols, "s" if cols > 1 else "", panels, a.fixes or "")).strip()
    if a.sheet:
        # a sheet that exists: the one a refused run kept, or a turnaround the owner dropped in (the Kestrel's concept
        # sheet, 2026-10-04); its panels are read in the order of --which, nothing is drawn
        sheet, usd = job.path(a.sheet), None
    else:
        sheet = job.path("ref", "sheet_%s.png" % "_".join(order))
        job.images.generate(prompt, sheet, model=_picture_model(a.model), references=[src], aspect_ratio=aspect)
        usd = job.images.spent() if hasattr(job.images, "spent") else None
    cells = picturecheck.sheet_cells(sheet, len(order))
    im = Image.open(sheet).convert("RGB")
    written, refused = [], []
    for w, cell in zip(order, cells):
        if cell["box"] is None:
            refused.append("%s: %s" % (w, cell["reason"]))
            continue
        x0, y0, x1, y1 = cell["box"]
        mx, my = int(0.05 * (x1 - x0)) + 2, int(0.05 * (y1 - y0)) + 2
        crop = im.crop((x0, y0, x1, y1))
        out = Image.new("RGB", (crop.width + 2 * mx, crop.height + 2 * my), (255, 255, 255))
        out.paste(crop, (mx, my))
        if a.mirror and w in ("side", "left"):
            out = ImageOps.mirror(out)
        out.save(outs[w])
        written.append(w)
    # a panel that is the hero drawn again, mirrored or not (the bullpup's "top" came back as its side, 2026-10-04):
    # the hero's own proportions and a high correlation; two end-on views correlate at 0.86 but are four times
    # narrower than the hero, so the proportions carry the test
    same = [(p, q, picturecheck.same_picture(outs[p], outs[q])) for i, p in enumerate(written) for q in written[i + 1:]]
    same = [s for s in same if s[2] > 0.95]
    hero_aspect = picturecheck.object_aspect(src)
    for w in written:
        asp = picturecheck.object_aspect(outs[w])
        if hero_aspect and asp and abs(math.log(asp / hero_aspect)) < math.log(1.15):
            s = picturecheck.same_picture(outs[w], src)
            if s > 0.8:
                same.append((w, "the hero", s))
    if not a.sheet:
        ledger.record(job.dir, "views", model=a.model, usd=usd, out=os.path.relpath(sheet, job.dir), which=written,
                      refused=refused or None)
    for w in written:
        print("view %s: %s" % (w, outs[w]))
    for p, q, s in same:
        print("  WARNING: %s and %s look like the same picture (%.2f): a view drawn again; redraw it with ms view --fixes" % (p, q, s))
    print("sheet: %s (Read it; a weapon's side view must point right: --mirror when it does not)" % sheet)
    if refused:
        sys.exit("not written: %s. Crop them by hand from the sheet, or draw them one at a time: ms view %s --which <view> --from %s"
                 % ("; ".join(refused), a.job, a.src))


def cmd_segment(a):
    """The registered seed split into labelled parts by a segmentation model (2026-10-04; Mixar wires Tripo's and
    Hunyuan's segmenters, and Hunyuan3D-Part is on fal): the seed goes out welded and decimated under the service's
    face limit (the seed file's geometry is untouched), the parts come back as meshes, every seed face takes the
    nearest part's label (`parts/<Part>/segments.json`, the ms_segment face attribute in registered.blend,
    segments.png and segments_side.png), and a zone in the plan can name labels instead of a box: "segment": 3 or
    [3, 5]. Material zones and glass picks then follow the seed's own part lines instead of percent boxes."""
    job = Job(a.job)
    m = models.resolve(a.model, kind="segment")
    part = _part(_plan(job), a.part)
    d = job.path("parts", part["name"])
    blend = os.path.join(d, "registered.blend")
    if not os.path.exists(blend):
        sys.exit("%s is not seeded and registered yet (ms seed)" % part["name"])
    out_json = os.path.join(d, "segments.json")
    if os.path.exists(out_json) and not a.redo:
        sys.exit("%s is segmented already (%s); --redo spends again" % (part["name"], out_json))
    seg_dir = os.path.join(d, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    print("segmenting %s with %s: $%.2f" % (part["name"], m["label"], models.price_of(m) or 0))
    fbx = os.path.join(seg_dir, "input.fbx")
    _blender(job, "segment_export.py", {"blend": blend, "out": fbx, "max_faces": a.max_faces},
             "segment_export_%s" % part["name"], timeout=900)
    os.environ["MASTERSMITH_NO_SPEND"] = "0"
    config.NO_SPEND = False
    url = job.fal.upload(fbx, mime="application/octet-stream")
    out = job.fal.run(m["endpoint"], {"input_file_url": url}, timeout=1800)
    files = [f.get("url") for f in (out.get("result_files") or []) if isinstance(f, dict) and f.get("url")]
    if not files:
        sys.exit("%s returned no parts: %s" % (m["label"], str(out)[:300]))
    for stale in os.listdir(seg_dir):                     # an older run's parts never mix with these
        if stale.startswith("part_"):
            os.remove(os.path.join(seg_dir, stale))
    paths = [job.fal.download(u, os.path.join(seg_dir, "part_%d.fbx" % i)) for i, u in enumerate(files)]
    if os.path.exists(out_json):
        os.remove(out_json)
    ledger.record(job.dir, "segment", model=a.model, usd=job.fal.spent(), part=part["name"], parts=len(paths))
    _blender(job, "segment_apply.py", {"blend": blend, "parts": paths, "out_json": out_json,
                                       "out_render": os.path.join(d, "segments.png"),
                                       "out_side_render": os.path.join(d, "segments_side.png")},
             "segment_apply_%s" % part["name"], timeout=900)
    if not os.path.exists(out_json):
        sys.exit("segment_apply wrote no %s; see %s" % (out_json, job.path("segment_apply_%s.log" % part["name"])))
    seg = json.load(open(out_json))
    print("%d labels on %d faces ($%.2f)%s:" % (len(seg["labels"]), seg["faces"], job.fal.spent(),
                                                "; the parts came back re-centred and were fitted to the seed's box" if seg.get("parts_refitted") else ""))
    for lab in seg["labels"]:
        print("  label %-3d %5.1f%%  side_box %-24s front_span %-14s %s" % (lab["label"], lab["share"] * 100, lab["side_box"],
                                                                           lab["front_span"], lab["colour"]))
    print("Read %s and %s, name each label, then give zones \"segment\": <label> in plan/plan_draft.json and ms plan."
          % (os.path.join(d, "segments.png"), os.path.join(d, "segments_side.png")))


def cmd_sheet(a):
    class J:
        pass
    j = J()
    j.work_dir = os.path.dirname(os.path.abspath(a.glb))
    j.log = print
    folder = j.work_dir
    tmp = os.path.join(folder, "_sheet_src")
    os.makedirs(tmp, exist_ok=True)
    shutil.copy2(a.glb, os.path.join(tmp, "SM_sheet.glb"))
    sheet = six_view_sheet(j, tmp)
    out = a.out or os.path.splitext(a.glb)[0] + "_views.png"
    shutil.move(os.path.join(tmp, "preview_views.png"), out)
    shutil.rmtree(tmp, ignore_errors=True)
    print("six views:", out)


def _glb_line(chk):
    return "%s tris, %s m, %d socket(s), %d texture(s)%s, %s" % (
        chk.get("triangles"), chk.get("dimensions_m"), len(chk.get("sockets") or {}), chk.get("images") or 0,
        " embedded" if chk.get("images_embedded") else "", "ok" if chk.get("passed") else "; ".join(chk.get("issues") or ["not checked"]))


def _glb_gate(job, delivery, rep):
    """The delivered GLB read back without Blender (mastersmith/glbcheck.py, 2026-10-04, from Mixar's export
    verification): its size, triangles, sockets and textures against report.json, its findings added to the gate
    and the report written again. The FBX was read back at the end of assemble; the GLB never was."""
    glb = os.path.join(delivery, "SM_%s.glb" % job.spec.name)
    if not os.path.exists(glb):
        return None
    chk = glbcheck.check(glb, rep)
    rep["glb_check"] = chk
    gate = rep.setdefault("gate", {"ok": True, "warnings": []})
    gate["warnings"] = [w for w in gate.get("warnings") or [] if not w.startswith("GLB: ")] + ["GLB: " + w for w in chk["issues"]]
    gate["ok"] = not gate["warnings"]
    with open(os.path.join(delivery, "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    return chk


def cmd_package(a):
    job = Job(a.job)
    rep = json.load(open(job.path("delivery", "report.json")))
    chk = _glb_gate(job, job.path("delivery"), rep)
    if chk:
        print("  GLB read back: %s" % _glb_line(chk))
    review = json.load(open(job.path("delivery", "review.json"))) if os.path.exists(job.path("delivery", "review.json")) else None
    gate = rep.get("gate") or {"ok": True, "warnings": ["assembled before the delivery gate existed"]}
    for w in gate.get("warnings") or []:
        print("  gate: " + w)
    print(write_package(job.spec, rep, {"review": review, "gate": gate, "rig": {}}, job.path("delivery")))


def cmd_status(a):
    job = Job(a.job)
    print("brief:", job.spec.name, job.spec.category, "%.3f m" % job.spec.size_m)
    print("ref:", sorted(os.listdir(job.path("ref"))) if os.path.isdir(job.path("ref")) else "none")
    review = refs_review.load_review(job.dir)
    if review:
        print("ref review (ms refs):", ", ".join("%s %s%s" % (f, r["status"], (": " + r["note"]) if r.get("note") else "")
                                                 for f, r in sorted(review.items())))
    have = [f for f in existing_pictures(job.dir) if f.startswith("parts")]
    if have:
        print("part pictures/builders on disk (%d): reuse them; ask the owner before drawing any again" % len(have))
    if os.path.exists(job.path("plan", "plan.json")):
        plan = _plan(job)
        for p in plan["parts"]:
            d = job.path("parts", p["name"])
            have = [f for f in ("side.png", "quarter.png", "seed.glb", "registered.blend", "segments.json") if os.path.exists(os.path.join(d, f))]
            reg = json.load(open(os.path.join(d, "registration.json"))) if os.path.exists(os.path.join(d, "registration.json")) else {}
            print("  %-22s %s %s" % (p["name"], have, ("iou %.2f" % reg["iou"]) if reg else ""))
    else:
        print("plan: none yet (ms grid, then write plan.json, then ms plan)")
    print("delivery:", "yes" if os.path.exists(job.path("delivery", "report.json")) else "none")
    sc_path = job.path("delivery", "scorecard.json")
    if os.path.exists(sc_path):
        sc = json.load(open(sc_path, encoding="utf-8"))
        print("score: %s%s" % (sc.get("score"), " (owner: %s)" % sc["owner_score"] if sc.get("owner_score") is not None
                                 else " (self-scored, not confirmed by the owner)"))
    # the owner's choices and the money, which a compacted context forgets (2026-09-30/10-01)
    s = ledger.summary(ledger.load(job.dir))
    if s["calls"] or s["notes"]:
        print("models used: %s" % ("; ".join("%s %s" % (k, ", ".join(v)) for k, v in s["models"].items()) or "none recorded"))
        print("spent on this job: $%.2f in %d paid call(s) recorded" % (s["spent_usd"], s["calls"]))
        for n in s["notes"][-12:]:
            print("  note: %s" % n)


def cmd_closeup(a):
    """One close-up of the delivery the way a reviewer needs it: a box off the side grid, a view, glass or lining hidden
    or shown bright red, a zone's faces in red, lit or unlit (base colour only), clay, or cut open (2026-09-29: ~17
    throwaway Blender probe scripts on the Havoc's glass and cockpit). Renders delivery/closeups/<name>.png."""
    job = Job(a.job)
    d = job.path("delivery")
    blend = os.path.join(d, "SM_%s.blend" % job.spec.name)
    if not os.path.exists(blend):
        sys.exit("nothing assembled yet: ms assemble %s first" % a.job)
    rep = json.load(open(os.path.join(d, "report.json")))
    pivot = (rep.get("origin") or {}).get("at_in_plan_frame_m") or [0.0, 0.0, 0.0]
    plan = _plan(job)
    shift = lambda v: [round(v[i] - pivot[i], 5) for i in range(3)]
    args = {"blend": blend, "name": job.spec.name, "view": a.view, "unlit": a.unlit, "clay": a.clay, "size": a.size,
            "hide": [h for h in (a.hide or "").split(",") if h], "highlight": [h for h in (a.highlight or "").split(",") if h]}
    if a.box:
        x0, x1, zt, zb = (float(v) for v in a.box.split(","))
        lo, hi = planmod.to_metres([x0, x1, zt, zb], [0, 100], plan["dims_m"])
        args["focus_min"], args["focus_max"] = shift(lo), shift(hi)
    boxes = {}
    for p in plan["parts"]:
        boxes[p["name"]] = [shift(p["box_min"]), shift(p["box_max"])]
        for z in p.get("zones") or []:
            boxes[z["name"]] = [shift(z["box_min"]), shift(z["box_max"])]
    args["boxes"] = boxes
    if a.section:
        axis, value = a.section.split("=")
        k = "xyz".index(axis.strip().lower())
        args["section"] = [axis.strip().lower(), float(value) - pivot[k]]
    tags = [a.view] + (["unlit"] if a.unlit else []) + (["clay"] if a.clay else []) + ["no-" + h for h in args["hide"]] + \
        ["red-" + h for h in args["highlight"]] + (["cut-" + a.section.replace("=", "")] if a.section else []) + \
        (["box-" + a.box.replace(",", "-")] if a.box else [])
    out = os.path.join(d, "closeups", (a.out or "_".join(tags)) + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    args["out"] = out
    _blender(job, "closeup.py", args, "closeup", timeout=900)
    res = json.load(open(os.path.splitext(out)[0] + ".json"))
    print("close-up: %s  (%s)" % (out, "; ".join(res.get("done") or []) or "as delivered"))
    print("Read it.")


def cmd_rig(a):
    """The delivered weapon rigged for an engine: Root/Body/(Barrel)/Muzzle bones at the measured muzzles, rigid skin,
    Idle/Fire/Equip (and FiringLoop) clips, all in centimetres with no node scale, read back to prove it (ported from
    Proteus's rig script, 2026-10-01: an FBX left in metres became a x100 root bone in Unreal). -> delivery/rig/"""
    job = Job(a.job)
    d = job.path("delivery")
    blend = os.path.join(d, "SM_%s.blend" % job.spec.name)
    if not os.path.exists(blend):
        sys.exit("nothing assembled yet: ms assemble %s first" % a.job)
    rep = json.load(open(os.path.join(d, "report.json")))
    if job.spec.category != "weapon":
        print("note: %s is a %s; the rig is a weapon's (recoil, equip slide, muzzle bones)" % (job.spec.name, job.spec.category))
    if not any(s["name"].startswith("Muzzle") for s in rep.get("sockets") or []):
        print("note: the delivery has no measured muzzle (assembled before 2026-10-02?): re-assemble for muzzle bones at the bores")
    out = os.path.join(d, "rig")
    args = {"blend": blend, "name": job.spec.name, "out_dir": out, "maps_dir": d, "sockets": rep.get("sockets") or [],
            "origin": a.origin, "barrel": [float(v) for v in a.barrel.split(",")] if a.barrel else None,
            "recoil": a.recoil, "kick": a.kick, "equip": a.equip, "loop": a.loop, "idle": a.idle, "glow": not a.no_glow}
    _blender(job, "rig_weapon.py", args, "rig", timeout=1200)
    res = json.load(open(os.path.join(out, "rig.json")))
    print("rigged -> %s: %s" % (out, ", ".join(res["files"])))
    print("  bones %s; clips %s; muzzles %s" % (res["bones"], res["clips"], res["muzzles_m"]))
    print("  read back: %s" % res["fbx_check"])
    print("  renders: " + ", ".join(os.path.join(out, r) for r in res["renders"]))
    if not res["fbx_check"].get("ok"):
        sys.exit("the skeletal FBX does not read back at the weapon's size with a unit root: do not hand it to the engine")
    print("Read the renders. In Unreal: import SK_%s.fbx as a skeletal mesh, then the A_ clips onto its skeleton; the "
          "Muzzle bones are the sockets." % job.spec.name)


def _mh_dir(job):
    d = job.path("delivery", "metahuman")
    os.makedirs(os.path.join(d, "in"), exist_ok=True)
    return d


def cmd_mh_conform(a):
    """A character seed as the ONE combined mesh Unreal 5.8's "custom mesh to MetaHuman" conform takes (the owner's
    video, 2026-10-04): Z up, facing -Y, feet on the floor, the brief's height, transforms applied, hair / lashes /
    accessories stripped by name; the A-pose measured off its silhouette and judged against the MetaHuman template
    (mastersmith/metahuman), front and side overlays on the template -> delivery/metahuman/<Name>_conform.glb"""
    from .metahuman import template as mh
    job = Job(a.job)
    if job.spec.category != "character":
        print("note: %s is a %s; the conform is for a humanoid character" % (job.spec.name, job.spec.category))
    src = a.source
    if not src:
        for cand in (job.path("parts", a.part, "registered.blend"), job.path("parts", a.part, "seed.glb")):
            if os.path.exists(cand):
                src = cand
                break
    if not src or not os.path.exists(src):
        sys.exit("no seed for %s (ms seed first, or --source <mesh>)" % a.part)
    out = _mh_dir(job)
    height = a.height if a.height is not None else job.spec.size_m
    head = a.head
    if head and not os.path.isabs(head) and not os.path.exists(head):
        head = job.path(head)
    if head and not os.path.exists(head):
        sys.exit("no head mesh at %s" % head)
    args = {"source": src, "extra": [p for p in (a.extra or "").split(",") if p], "name": job.spec.name, "height_m": height,
            "out_dir": out, "template_glb": os.path.join(mh.TEMPLATES, "MH_Template.glb"),
            "template_json": os.path.join(mh.TEMPLATES, "template.json"),
            "strip": [s for s in (a.strip or "").split(",") if s], "head": head, "head_yaw": a.head_yaw}
    _blender(job, "mh_conform.py", args, "mh_conform", timeout=1200)
    rep = json.load(open(os.path.join(out, "conform_report.json"), encoding="utf-8"))
    verdict = mh.check_pose(rep)
    rep["pose_check"] = verdict
    json.dump(rep, open(os.path.join(out, "conform_report.json"), "w", encoding="utf-8"), indent=1)
    print("conform mesh -> %s (%.2f m, %d tris)" % (os.path.join(out, rep["glb"]), rep["height_m"], rep["triangles"]))
    if rep.get("head"):
        h = rep["head"]
        print("  head mesh -> %s (x%.3f onto the body's %.0f mm skull, cut below %.2f m, %s): the solver's HeadAndBody conform; "
              "its renders conform_head_front/side.png" % (os.path.join(out, h["glb"]), h["scale"], h["skull_width_m"] * 1000,
                                                             h["cut_below_m"], "textured" if h.get("textured") else "NO texture"))
    print("  A-pose: arms %s / %s deg (template %.0f), armpit gap %.0f mm, knee gap %.0f mm, finger tips %s, head %s%s" % (
        rep.get("arm_angle_deg_l"), rep.get("arm_angle_deg_r"), mh.load()["apose"]["arm_angle_deg"], rep.get("armpit_gap_m", 0) * 1000,
        rep.get("leg_gap_m", 0) * 1000, rep.get("finger_tips"), rep.get("head_present"), ", hair suspected" if rep.get("hair_suspected") else ""))
    for p in verdict["problems"]:
        print("  PROBLEM " + p)
    for n in verdict["notes"]:
        print("  note " + n)
    print("  overlays: " + ", ".join(os.path.join(out, r) for r in rep["renders"].values()) + "  (white: the seed; red: the template where the seed does not cover it)")
    print("Read both overlays. Then in Unreal 5.8 (the metahuman skill): import the GLB, MetaHuman Character > Import > from custom "
          "mesh > Combined, Auto Solve, Manual Solve > Save Pose (the posed DNA), then the rig and the texture sources.")
    ledger.record(job.dir, "mh-conform", glb=rep["glb"], height_m=rep["height_m"], ok=verdict["ok"], problems=verdict["problems"])


def cmd_mh_bake(a):
    """The seed's colour and surface detail baked onto the POSED MetaHuman mesh Unreal generated from the conformed DNA
    (Mesh to MetaHuman > Save Pose > Generate Skeletal Mesh > Asset Actions > Export), head on UDIM 1001 and body on
    1002 moved onto 0-1 -> delivery/metahuman/T_<Name>_<Head|Body>_<BC|N>.png and a preview."""
    job = Job(a.job)
    out = _mh_dir(job)
    src = a.source or os.path.join(out, "%s_conform.glb" % job.spec.name)
    if not os.path.exists(src):
        sys.exit("no conform mesh at %s: ms mh-conform first, or --source <the textured seed>" % src)
    posed = a.posed if os.path.isabs(a.posed) else job.path(a.posed)
    if not os.path.exists(posed):
        sys.exit("no posed FBX at %s: export the skeletal mesh Unreal generated from the posed DNA into delivery/metahuman/in/" % posed)
    head_src = a.head_source
    if head_src is None:
        cand = os.path.join(out, "%s_head.glb" % job.spec.name)
        head_src = cand if os.path.exists(cand) else ""
    elif head_src and not os.path.isabs(head_src) and not os.path.exists(head_src):
        head_src = job.path(head_src)
    args = {"source": src, "posed_fbx": posed, "name": job.spec.name, "out_dir": out, "resolution": a.resolution,
            "cage_m": a.cage / 1000.0, "maps": ["color", "normal"] if not a.color_only else ["color"],
            "head_source": head_src or None, "far_pass": bool(a.far_pass), "skin_color": a.skin_color,
            "skin_parts": [p for p in (a.skin_parts or "Body").split(",") if p], "align": not a.no_align}
    if head_src:
        print("the head bakes from %s" % head_src)
    _blender(job, "mh_bake.py", args, "mh_bake", timeout=3600)
    rep = json.load(open(os.path.join(out, "bake_report.json"), encoding="utf-8"))
    al = rep["alignment"]
    print("baked -> %s" % out)
    for name, m in rep["maps"].items():
        print("  %s: %dpx, %.0f%% of the texels written, %.1f%% far pass, %d nearest-point, %d skin-tinted (%s)" % (
            name, m["resolution"], m["coverage"] * 100, m.get("far_pass_share", 0) * 100, m.get("nearest_seed_point", 0), m.get("skin_tinted", 0), m["convention"]))
    print("  alignment: seed %.3f m, posed mesh %.3f m, centres off by %s m%s" % (al["source_height_m"], al["posed_height_m"], al["centre_offset_m"],
          " (moved onto the seed before baking)" if al.get("shifted_onto_seed") else ""))
    print("  faces: %s" % rep["face_split"])
    print("  previews: " + ", ".join(os.path.join(out, r) for r in rep["renders"].values()))
    print("  " + rep["unreal"])
    ledger.record(job.dir, "mh-bake", maps=sorted(rep["maps"]), alignment=al)


def cmd_mh_attach(a):
    """An accessory (hair, horns, ears, armour) weighted onto the built MetaHuman's skeleton and exported as a skeletal
    mesh in centimetres, no leaf bones, read back -> delivery/metahuman/SK_<Name>_<Part>.fbx. Drop it onto the
    MetaHuman Blueprint's Body component in Unreal."""
    job = Job(a.job)
    out = _mh_dir(job)
    built = a.built if os.path.isabs(a.built) else job.path(a.built)
    if not os.path.exists(built):
        sys.exit("no built MetaHuman FBX at %s: export the built body (or face) skeletal mesh into delivery/metahuman/in/" % built)
    acc = a.source
    if not acc:
        for cand in (job.path("parts", a.part, "registered.blend"), job.path("parts", a.part, "seed.glb")):
            if os.path.exists(cand):
                acc = cand
                break
    if not acc or not os.path.exists(acc):
        sys.exit("no mesh for %s (a part with a seed, or --source <mesh in the conform's frame>)" % a.part)
    args = {"built_fbx": built, "accessory": acc, "name": job.spec.name, "part": a.part, "out_dir": out, "bone": a.bone,
            "offset_m": [float(v) for v in a.offset.split(",")] if a.offset else [0, 0, 0], "decimate_to": a.decimate_to}
    _blender(job, "mh_attach.py", args, "mh_attach_%s" % a.part, timeout=1200)
    rep = json.load(open(os.path.join(out, "attach_report.json"), encoding="utf-8"))
    print("attached %s -> %s (%d tris, weights %s)" % (a.part, os.path.join(out, rep["fbx"]), rep["triangles"], rep["weights"]))
    print("  read back: %s" % rep["fbx_check"])
    print("  renders: " + ", ".join(os.path.join(out, r) for r in rep["renders"].values()))
    if not rep["fbx_check"].get("ok"):
        sys.exit("the FBX does not read back at size with a unit root: do not hand it to the engine")
    print("In Unreal: import %s as a skeletal mesh ON the MetaHuman's body skeleton (pick it in the import dialog), then drag it "
          "onto the MetaHuman Blueprint's Body component." % rep["fbx"])
    ledger.record(job.dir, "mh-attach", part=a.part, fbx=rep["fbx"], weights=rep["weights"])


def cmd_open(a):
    """A job's Blender file opened in Blender's own window, the user's preferences and add-ons on (the BlenderMCP
    add-on included), for work by hand or through a live Blender MCP session (2026-09-29: the session that asked for
    this had no way in but a headless script). The headless runs keep factory settings. A part's registered.blend is
    the seed the assembler reads: a copy is kept first (rule 10)."""
    job = Job(a.job)
    if a.part:
        path = job.path("parts", a.part, "registered.blend")
        backup = job.path("parts", a.part, "registered_before_open.blend")
        if os.path.exists(path) and not os.path.exists(backup):
            shutil.copy2(path, backup)
            print("kept a copy of the seed: %s (copy it back to undo what you change by hand)" % backup)
    elif a.rig:
        path = job.path("delivery", "rig", "SK_%s.blend" % job.spec.name)
    else:
        path = job.path("delivery", "SM_%s.blend" % job.spec.name)
    if not os.path.exists(path):
        sys.exit("no %s yet" % path)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([config.BLENDER_BIN, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    print("opened in Blender: %s" % path)
    if a.part:
        print("Save over registered.blend only for a change you mean the assembler to use; then ms assemble.")


def cmd_note(a):
    """The owner's decision in their words, kept with the job (ms status prints it): models picked, references
    approved, what to change. A compacted context loses the conversation; the job folder keeps this."""
    job = Job(a.job)
    ledger.record(job.dir, "note", text=" ".join(a.text))
    print("noted in %s" % os.path.join(job.dir, ledger.FILE))


def cmd_clone(a):
    """A copy of a job to rebuild from: its pictures, its tuned plan and every part but the one re-seeded (2026-09-30:
    a re-run that started from a generic plan lost the Havoc's cockpit insert and canopy shell, 9/10 -> 5/10)."""
    src = a.src if os.path.isdir(a.src) else os.path.join(str(config.OUT_DIR), a.src)
    dst = os.path.join(str(config.OUT_DIR), os.path.basename(os.path.normpath(a.name)))
    try:
        res = jobtools.clone_job(src, dst, reseed=[p.strip() for p in a.reseed.split(",") if p.strip()], keep_seed=a.keep_seed)
    except ValueError as exc:
        sys.exit(str(exc))
    print("cloned %s -> %s (%d files): seeds kept %s; to seed again %s" % (src, dst, res["copied"], res["seeds_kept"] or "none",
                                                                             res["reseed"] or "none"))
    rel = os.path.relpath(dst, str(config.ROOT))
    if res["reseed"]:
        print("Next: ms seed %s --model <the owner's pick> (keeps the plan), then ms assemble %s" % (rel, rel))
    else:
        print("Next: ms assemble %s (free: the same seeds with the current code)" % rel)


def _price(model_key):
    try:
        return models.price_of(models.resolve(model_key, kind="seed")) or 0.0
    except KeyError:
        sys.exit("no seed model %s (ms models)" % model_key)


def cmd_batch(a):
    """One command over several jobs, a few at a time, a log per job and one line each (the Proteus weapons were seeded
    and assembled by shell loops in another repo, 2026-09-30). A command that spends asks for --yes."""
    jobs = [j if os.path.isdir(j) else os.path.join(str(config.OUT_DIR), j) for j in a.jobs]
    for j in jobs:
        if not os.path.isfile(os.path.join(j, "brief.json")):
            sys.exit("no job %s" % j)
    extra = jobtools.split_args(a.args)
    if a.command in jobtools.SPENDING and not a.yes:
        est = ""
        if a.command == "seed" and "--model" in extra:
            est = " (%d x $%.2f = $%.2f)" % (len(jobs), _price(extra[extra.index("--model") + 1]),
                                             len(jobs) * _price(extra[extra.index("--model") + 1]))
        sys.exit("ms %s spends money%s: say the estimate to the owner, then add --yes" % (a.command, est))
    print("ms %s on %d jobs, %d at a time (logs: <job>/batch_%s.log)" % (a.command, len(jobs), a.parallel, a.command))
    res = jobtools.run_batch(a.command, jobs, extra, parallel=a.parallel)
    bad = [r for r in res if r["exit"] != 0]
    if a.command == "assemble" and "--draft" not in extra:
        names = ",".join(os.path.basename(r["job"]) for r in res if r["exit"] == 0)
        if names:
            print("builds: %s/results?jobs=%s" % (_serve_out(str(config.OUT_DIR)), names))
    if bad:
        sys.exit("%d of %d failed: %s" % (len(bad), len(res), ", ".join("%s (%s)" % (os.path.basename(r["job"]), r["log"]) for r in bad)))


def cmd_bench(a):
    """The owner's standard test set (mastersmith/bench.json): each asset cloned from its best-tuned job, re-seeded with
    the model the owner picked (or, --keep-seed, the same seeds re-assembled with the current code for free), assembled,
    and summed up against its baseline score (2026-09-30: Codex scripted this by hand and lost the tuned plans)."""
    out_dir = str(config.OUT_DIR)
    assets = jobtools.bench_set()
    if a.only:
        want = {w.strip().lower() for w in a.only.split(",")}
        assets = [x for x in assets if x["name"].lower() in want]
    if not a.keep_seed and not a.model:
        sys.exit("--model <seed model the owner picked>, or --keep-seed for a free re-assemble of the same seeds")
    tag = a.tag or time.strftime("%Y%m%d")
    suffix = "rebuild" if a.keep_seed else a.model.replace("-", "")
    rows = []
    for x in assets:
        src = os.path.join(out_dir, x["source"])
        dst = os.path.join(out_dir, "%s_%s_%s" % (x["name"], suffix, tag))
        if not os.path.isdir(src):
            print("  %s: source %s is missing, skipped" % (x["name"], x["source"]))
            continue
        rows.append({**x, "job": dst, "needs_seed": not a.keep_seed and not os.path.exists(os.path.join(dst, "parts", "Body", "seed.glb"))})
    seeds = [r for r in rows if r["needs_seed"]]
    price = _price(a.model) if seeds else 0.0
    print("bench %s: %d assets -> %s" % (tag, len(rows), ", ".join(os.path.basename(r["job"]) for r in rows)))
    if seeds:
        print("  seeding %d with %s: %d x $%.2f = $%.2f" % (len(seeds), a.model, len(seeds), price, len(seeds) * price))
        if not a.yes:
            sys.exit("say this estimate to the owner; run again with --yes once they agree")
    for r in rows:
        if not os.path.isdir(r["job"]):
            res = jobtools.clone_job(os.path.join(out_dir, r["source"]), r["job"], keep_seed=a.keep_seed)
            print("  cloned %s from %s (seeds kept: %s)" % (os.path.basename(r["job"]), r["source"], res["seeds_kept"] or "none"))
    if seeds:
        jobtools.run_batch("seed", [r["job"] for r in seeds], ["--model", a.model], parallel=a.parallel)
    done = [r for r in rows if os.path.exists(os.path.join(r["job"], "parts", "Body", "registered.blend"))]
    res = jobtools.run_batch("assemble", [r["job"] for r in done], jobtools.split_args(a.args), parallel=a.assemble_parallel)
    summary = {"tag": tag, "model": None if a.keep_seed else a.model, "keep_seed": a.keep_seed, "assets": []}
    for r, x in zip(done, res):
        summary["assets"].append({"name": r["name"], "job": os.path.basename(r["job"]), "source": r["source"],
                                  "baseline": r.get("baseline"), "exit": x["exit"], "gate": x["gate"], "log": x["log"]})
    os.makedirs(os.path.join(out_dir, "_bench"), exist_ok=True)
    path = os.path.join(out_dir, "_bench", "%s_%s.json" % (suffix, tag))
    json.dump(summary, open(path, "w", encoding="utf-8"), indent=1)
    ok = ",".join(s["job"] for s in summary["assets"] if s["exit"] == 0)
    print("summary: %s" % path)
    if ok:
        print("builds: %s/results?jobs=%s" % (_serve_out(out_dir), ok))
    print("Now LOOK at each build's six views and close-ups, write delivery/scorecard.json against the baseline score "
          "(SKILL.md §6 anchors), and report the table with the results link.")


def main(argv=None):
    # line by line even into a file or a pipe: a background `ms seed > log` showed nothing until it ended (2026-09-29);
    # UTF-8 so a model's em dash does not stop a run on a cp1252 console
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="ms", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("name", nargs="?"); s.add_argument("--category", default="prop"); s.add_argument("--size", type=float)
    s.add_argument("--rebrief", action="store_true", help="rewrite brief.json of an existing job (its pictures are kept)")
    s.add_argument("--description"); s.add_argument("--style", default="realistic"); s.add_argument("--engine", default="unreal")
    s.add_argument("--from", dest="from_file", help='several jobs: a JSON list of {"name", "category", "size", "description"}')
    s.add_argument("--tris", type=int, default=0); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("clone", help="a job copied to rebuild from: pictures, tuned plan, other parts' seeds")
    s.add_argument("src"); s.add_argument("name"); s.add_argument("--reseed", default="Body", help="parts whose seed is NOT copied (comma list)")
    s.add_argument("--keep-seed", action="store_true", help="copy every seed too (a free re-assemble with the current code)")
    s.set_defaults(fn=cmd_clone)
    s = sub.add_parser("batch", help="one ms command over several jobs, a few at a time")
    s.add_argument("command"); s.add_argument("jobs", nargs="+"); s.add_argument("--parallel", type=int, default=2)
    s.add_argument("--args", default="", help='the rest of the command line for each job, e.g. "--model tripo" or "--draft"')
    s.add_argument("--yes", action="store_true", help="the owner agreed to what a spending command costs"); s.set_defaults(fn=cmd_batch)
    s = sub.add_parser("bench", help="the owner's standard test set (mastersmith/bench.json) re-seeded and assembled")
    s.add_argument("--model", help="the seed model the owner picked"); s.add_argument("--keep-seed", action="store_true")
    s.add_argument("--only", help="comma list of asset names"); s.add_argument("--tag", help="default: today, YYYYMMDD")
    s.add_argument("--parallel", type=int, default=3, help="seeds at a time"); s.add_argument("--assemble-parallel", type=int, default=2)
    s.add_argument("--args", default="", help="extra assemble arguments"); s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_bench)
    s = sub.add_parser("note", help="the owner's decision, kept with the job"); s.add_argument("job"); s.add_argument("text", nargs="+")
    s.set_defaults(fn=cmd_note)
    s = sub.add_parser("open", help="the delivery (or a part's seed, or the rig) in Blender's window, the user's add-ons on")
    s.add_argument("job"); s.add_argument("--part", help="a part's registered.blend (a copy is kept first)")
    s.add_argument("--rig", action="store_true", help="delivery/rig/SK_<Name>.blend"); s.set_defaults(fn=cmd_open)
    s = sub.add_parser("closeup", help="one close-up of the delivery: a box, a view, glass hidden or red, unlit, clay, a cut")
    s.add_argument("job"); s.add_argument("--box", help="x0,x1,z_top,z_bottom in side-grid percents")
    s.add_argument("--view", default="iso", choices=("iso", "iso_rear", "iso_low", "left", "right", "front", "back", "top", "bottom"))
    s.add_argument("--unlit", action="store_true", help="base colour only, no shading"); s.add_argument("--clay", action="store_true")
    s.add_argument("--hide", help="glass,lining,frame"); s.add_argument("--highlight", help="glass, lining, frame, or a part or zone name")
    s.add_argument("--section", help="x=, y= or z= metres in the plan frame: the near side cut away")
    s.add_argument("--size", type=int, default=1024); s.add_argument("--out", help="file name (no extension)")
    s.set_defaults(fn=cmd_closeup)
    s = sub.add_parser("rig", help="a delivered weapon rigged and animated for an engine, in centimetres")
    s.add_argument("job"); s.add_argument("--origin", default="keep", choices=("keep", "mount", "centre", "bottom", "rear", "grip"))
    s.add_argument("--barrel", help="from,to: the window (fractions of the length from the rear) where the barrel splits off")
    s.add_argument("--recoil", type=float, default=0.05, help="fraction of the length the body slides back")
    s.add_argument("--kick", type=float, default=0.0, help="fraction of the length the barrel kicks back")
    s.add_argument("--equip", type=float, default=0.12, help="fraction of the length the equip slide starts back")
    s.add_argument("--loop", choices=("jet", "coil"), help="a FiringLoop clip: a flame jet's buzz or a coil's pump")
    s.add_argument("--idle", choices=("coil",), help="a coil's slow pulse at idle")
    s.add_argument("--no-glow", action="store_true", help="leave the emissive map out (a muzzle that must not glow)")
    s.set_defaults(fn=cmd_rig)
    s = sub.add_parser("mh-conform", help="a character seed as the combined mesh Unreal 5.8's MetaHuman conform takes, A-pose checked")
    s.add_argument("job"); s.add_argument("--part", default="Body", help="the part whose seed is the body (default Body)")
    s.add_argument("--source", help="a mesh file instead of the part's seed (.glb/.fbx/.obj/.blend)")
    s.add_argument("--extra", help="more meshes to join, comma-separated (a separate high-poly head)")
    s.add_argument("--strip", help="object-name substrings to drop before joining: hair,lash,weapon")
    s.add_argument("--height", type=float, help="the character's height in metres (default: the brief's size)")
    s.add_argument("--head", help="a separate head seed (parts/Head/seed.glb): placed on the body's head, exported alone as <Name>_head.glb for a HeadAndBody conform")
    s.add_argument("--head-yaw", type=float, default=0.0, help="degrees about the vertical to turn the head seed so its face points -Y (read its renders)")
    s.set_defaults(fn=cmd_mh_conform)
    s = sub.add_parser("mh-bake", help="the seed's colour and normal baked onto the posed MetaHuman mesh exported from Unreal")
    s.add_argument("job"); s.add_argument("--posed", required=True, help="the skeletal mesh FBX Unreal generated from the POSED DNA")
    s.add_argument("--source", help="the textured seed (default delivery/metahuman/<Name>_conform.glb)")
    s.add_argument("--resolution", type=int, default=4096); s.add_argument("--cage", type=float, default=12.0, help="ray cage in mm")
    s.add_argument("--color-only", action="store_true")
    s.add_argument("--head-source", help="a textured head mesh in the conform's frame for the head part (default delivery/metahuman/<Name>_head.glb when it exists; '' for none)")
    s.add_argument("--far-pass", action="store_true", help="a second bake with a 4x cage for texels the near pass missed (off: the nearest seed point fills them)")
    s.add_argument("--skin-color", help="#rrggbb: pale texels on --skin-parts take this colour (washed-out hands and feet)")
    s.add_argument("--skin-parts", default="Body", help="comma-separated parts the skin colour applies to (default Body)")
    s.add_argument("--no-align", action="store_true", help="do not move the posed mesh onto the seed's bounds centre before baking")
    s.set_defaults(fn=cmd_mh_bake)
    s = sub.add_parser("mh-attach", help="an accessory weighted onto the built MetaHuman's skeleton, exported as a skeletal mesh")
    s.add_argument("job"); s.add_argument("part", help="the part (its seed is the accessory) and the FBX's name")
    s.add_argument("--built", required=True, help="the built MetaHuman's body or face skeletal mesh FBX exported from Unreal")
    s.add_argument("--source", help="a mesh file instead of the part's seed, in the conform's frame")
    s.add_argument("--bone", default="head", help="head | <bone> | transfer (the MetaHuman mesh's own weights)")
    s.add_argument("--offset", help="x,y,z metres to move the accessory first")
    s.add_argument("--decimate-to", type=int, default=0, help="triangles to decimate the accessory to (0 = keep)")
    s.set_defaults(fn=cmd_mh_attach)
    s = sub.add_parser("picture"); s.add_argument("job"); s.add_argument("--out", required=True); s.add_argument("--prompt", required=True)
    s.add_argument("--ref", action="append"); s.add_argument("--model", default="nano"); s.add_argument("--aspect", default="4:3")
    s.add_argument("--redraw", action="store_true", help="draw over an existing picture (ask the owner first)"); s.set_defaults(fn=cmd_picture)
    s = sub.add_parser("view"); s.add_argument("job"); s.add_argument("--which", choices=sorted(VIEW_TEXT), required=True)
    s.add_argument("--from", dest="src", required=True); s.add_argument("--out"); s.add_argument("--fixes"); s.add_argument("--mirror", action="store_true")
    s.add_argument("--model", default="nano"); s.add_argument("--redraw", action="store_true"); s.set_defaults(fn=cmd_view)
    s = sub.add_parser("grid"); s.add_argument("job"); s.add_argument("--side", required=True); s.add_argument("--front")
    s.add_argument("--mirror", action="store_true", help="the side picture has the forward end on the left"); s.add_argument("--width", type=float); s.set_defaults(fn=cmd_grid)
    s = sub.add_parser("plan"); s.add_argument("job"); s.add_argument("plan"); s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("build"); s.add_argument("job"); s.add_argument("part"); s.set_defaults(fn=cmd_build)
    s = sub.add_parser("part-pictures"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--fixes"); s.add_argument("--erased", action="store_true")
    s.add_argument("--drawn", action="store_true", help="draw the body alone instead of erasing the approved picture")
    s.add_argument("--no-quarter", action="store_true"); s.add_argument("--no-side", action="store_true", help="keep the side picture")
    s.add_argument("--no-front", action="store_true", help="the body's three-quarter picture without the front-view reference")
    s.add_argument("--with-front", action="store_true", help="give a non-body part's three-quarter picture the front view too")
    s.add_argument("--model", default="nano"); s.add_argument("--redraw", action="store_true", help="draw over existing pictures (ask the owner first)")
    s.set_defaults(fn=cmd_part_pictures)
    s = sub.add_parser("mesh"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--vendor", default="local")
    s.add_argument("--from", dest="src", default="quarter", choices=("quarter", "side")); s.set_defaults(fn=cmd_mesh)
    s = sub.add_parser("register"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--from", dest="src", default="quarter", choices=("quarter", "side"))
    s.add_argument("--front", choices=sorted(models.FRONT_YAW), help="the axis the pictured side faces on the vendor's seeds (+X for Tripo); "
                   "with --from side it is a tie-breaker between the two ends")
    s.add_argument("--yaw", type=float, default=0.0); s.add_argument("--pitch", type=float, default=0.0); s.set_defaults(fn=cmd_register)
    s = sub.add_parser("fit"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--quarter", action="store_true")
    s.add_argument("--iters", type=int, default=8); s.add_argument("--step", type=float, default=0.6); s.add_argument("--no-backup", action="store_true")
    s.add_argument("--free", action="store_true", help="move vertices one by one (the old fit) instead of bending a lattice"); s.set_defaults(fn=cmd_fit)
    s = sub.add_parser("brush"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--op", choices=("inflate", "move", "smooth", "flatten", "crease"))
    s.add_argument("--at", default="centre", help="x,y,z metres in the part frame, or front/back/top/bottom/left/right/centre[+dx,dy,dz]")
    s.add_argument("--radius", type=float, default=10.0, help="mm"); s.add_argument("--strength", type=float, default=1.0, help="inflate: mm at the centre; others: 0-1")
    s.add_argument("--delta", help="move: dx,dy,dz in mm"); s.add_argument("--to", help="crease: the line's other end"); s.add_argument("--normal", help="flatten: nx,ny,nz")
    s.add_argument("--replay", action="store_true", help="re-apply brush_log.json to a fresh mesh"); s.set_defaults(fn=cmd_brush)
    s = sub.add_parser("cabin"); s.add_argument("job"); s.add_argument("part"); s.add_argument("--hull", help="the body part (default: the longest vendor part)")
    s.set_defaults(fn=cmd_cabin)
    s = sub.add_parser("sdf"); s.add_argument("job"); s.add_argument("part"); s.add_argument("script", nargs="?"); s.add_argument("--voxel", type=float, help="mm")
    s.set_defaults(fn=cmd_sdf)
    s = sub.add_parser("assemble"); s.add_argument("job"); s.add_argument("--parts"); s.add_argument("--no-sharpen", action="store_true")
    s.add_argument("--projection", choices=("auto", "full", "letters", "off"), default="auto",
                   help="auto: a kept-texture seed takes the pictures only in its lettering boxes, other parts all over; "
                        "full: everywhere (the old way); letters: lettering boxes only; off: none")
    s.add_argument("--no-projection", action="store_true", help="the same as --projection off")
    s.add_argument("--origin", choices=("centre", "bottom", "top", "rear", "front", "mount", "grip"), default="centre",
                   help="the exported pivot: centre (default), bottom (a vehicle on the ground), mount (a pylon weapon's "
                        "plate top), grip (the Grip socket), ...")
    s.add_argument("--draft", action="store_true", help="stop before the bake: renders of the placed parts with their glass, "
                   "lining and muzzle into delivery/draft/ in a fraction of the time; the delivery is untouched")
    s.add_argument("--tubes", type=int, default=0, help="a launcher's tube count: Muzzle_0..N-1 from the front vertices when "
                   "the tubes are loaded or capped and show no open bore")
    s.add_argument("--no-materials", action="store_true", help="skip the CC0 smart-material pass (#15), for comparison")
    s.add_argument("--no-edge-break", action="store_true", help="leave code parts' edges razor sharp (no small round)")
    s.add_argument("--no-bevel", action="store_true", help="no small round baked into the normal map")
    s.add_argument("--finish-profile", choices=("standard", "restrained"), default="restrained",
                   help="restrained (default since 2026-10-02): bevel 0.05%% of the length up to 1.5 mm, weaker relief, "
                        "matte floors by finish; standard: the 0.2%% bevel and full relief of before")
    s.add_argument("--drop-floaters", action="store_true", help="delete the far, small loose islands of a seed (they are reported anyway)")
    s.add_argument("--no-surface-detail", action="store_true", help="no procedural cast-surface wear and grain on a seed (always "
                   "off for a nature brief)")
    s.set_defaults(fn=cmd_assemble)
    s = sub.add_parser("views", help="several standard views from ONE turnaround-sheet picture call, split into ref/ref_<view>.png")
    s.add_argument("job"); s.add_argument("--from", dest="src", required=True, help="the hero picture")
    s.add_argument("--which", default="front,left,back,top", help="comma list of %s (a weapon's hero is its side: front,back,top)"
                   % ", ".join(sorted(k for k in VIEW_TEXT if k != "quarter")))
    s.add_argument("--fixes"); s.add_argument("--mirror", action="store_true", help="mirror the side view (its forward end must point right)")
    s.add_argument("--sheet", help="split this sheet (a kept one, or the owner's) in the order of --which; nothing is drawn")
    s.add_argument("--model", default="nano"); s.add_argument("--redraw", action="store_true", help="draw over existing views (ask the owner first)")
    s.set_defaults(fn=cmd_views)
    s = sub.add_parser("segment", help="the registered seed split into labelled parts that zones can name (ms models: segment models)")
    s.add_argument("job"); s.add_argument("--part", default="Body"); s.add_argument("--model", default="hunyuan-part")
    s.add_argument("--max-faces", type=int, default=28000, help="the decimated copy that is sent (Hunyuan takes 30k at most)")
    s.add_argument("--redo", action="store_true", help="segment again (it costs again)"); s.set_defaults(fn=cmd_segment)
    s = sub.add_parser("sheet"); s.add_argument("glb"); s.add_argument("--out"); s.set_defaults(fn=cmd_sheet)
    s = sub.add_parser("models"); s.add_argument("action", nargs="?", default="list", choices=("list", "add", "remove"))
    s.add_argument("key", nargs="?"); s.add_argument("--kind", default="seed", choices=("seed", "picture")); s.add_argument("--command")
    s.add_argument("--inputs", default="single", choices=("single", "multiview")); s.add_argument("--label"); s.add_argument("--notes")
    s.add_argument("--front", choices=sorted(models.FRONT_YAW), help="the axis its seeds usually face after import")
    s.set_defaults(fn=cmd_models)
    s = sub.add_parser("seed"); s.add_argument("job"); s.add_argument("--model", required=True, help="a seed model from ms models")
    s.add_argument("--part", default="Body"); s.add_argument("--view", choices=("hero", "left", "front", "back", "top"),
                                                             help="the picture a single-image model gets (default: the hero; a weapon's side)")
    s.add_argument("--replan", action="store_true", help="write the one-part plan again"); s.add_argument("--reseed", action="store_true")
    s.add_argument("--mirror-far-side", action="store_true", help="give a multi-view model the side view mirrored as the far side (weapons get it anyway)")
    s.set_defaults(fn=cmd_seed)
    s = sub.add_parser("retexture"); s.add_argument("job"); s.add_argument("--model", default="meshy-retexture")
    s.add_argument("--part", default="Body"); s.add_argument("--prompt", help="the texture described (default: the brief)")
    s.add_argument("--no-picture", action="store_true", help="text only, no hero picture as the style guide")
    s.set_defaults(fn=cmd_retexture)
    s = sub.add_parser("refs"); s.add_argument("jobs", nargs="*"); s.add_argument("--no-open", action="store_true")
    s.add_argument("--sheet", action="store_true", help="also write <job>/ref_sheet.png per job (every picture, labelled, with warnings) to Read")
    s.set_defaults(fn=cmd_refs)
    s = sub.add_parser("results"); s.add_argument("jobs", nargs="*"); s.add_argument("--no-open", action="store_true"); s.set_defaults(fn=cmd_results)
    s = sub.add_parser("serve"); s.add_argument("--restart", action="store_true"); s.add_argument("--stop", action="store_true")
    s.add_argument("--no-open", action="store_true"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("preview"); s.add_argument("job"); s.add_argument("--no-open", action="store_true"); s.set_defaults(fn=cmd_preview)
    s = sub.add_parser("package"); s.add_argument("job"); s.set_defaults(fn=cmd_package)
    s = sub.add_parser("status"); s.add_argument("job"); s.set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

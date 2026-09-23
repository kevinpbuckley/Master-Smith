"""Stage 3: headless Blender in two passes around a Python decision step.
    prepare.py  -> work.blend + probe renders (known cameras)
    probe.run   -> which end is the front (vision), glass / wheel masks (SAM 3)
    finish.py   -> yaw, glass slot, maps, LODs, collision, renders, FBX/GLB
Deterministic where it can be; the only judgement calls are the two vision answers."""
import json
import os
import subprocess

from .. import config
from .cockpit import make_cockpit
from .parts import make_part_seed
from .tiles import make_tiles
from .probe import run_probe

BLENDER_DIR = config.ROOT / "mastersmith" / "blender"


def _blender(job, script, args, tag):
    if not os.path.exists(config.BLENDER_BIN):
        raise RuntimeError("Blender not found at %s (set BLENDER_BIN)" % config.BLENDER_BIN)
    args_path = os.path.join(job.work_dir, "%s_args.json" % tag)
    with open(args_path, "w") as f:
        json.dump(args, f, indent=1)
    cmd = [config.BLENDER_BIN, "-b", "--python", str(BLENDER_DIR / script), "--", args_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    log_path = os.path.join(job.work_dir, "%s.log" % tag)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout or "")
        f.write("\n--- stderr ---\n")
        f.write(proc.stderr or "")
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-12:])
        err = "\n".join((proc.stderr or "").splitlines()[-6:])
        raise RuntimeError("Blender %s failed (exit %s); see %s\n%s\n%s" % (script, proc.returncode, log_path, tail, err))


def run_finish(job, skill, seed_glb, reference=None, retexture_maps=None, recolor=None):
    spec = job.spec
    common = {"name": spec.name, "work_dir": job.work_dir, "out_dir": os.path.join(job.dir, "delivery"),
              "tri_budget": spec.tri_budget, "size_m": spec.size_m, "engine": spec.engine,
              "forward_axis": skill["meta"].get("forward_axis", "long"), "origin": skill["meta"].get("origin", "bottom"),
              "spec": spec.portable(), "reference": reference}
    job.log("  Blender pass 1: orient, scale to %.2f m, probe renders" % spec.size_m)
    _blender(job, "prepare.py", {**common, "glb": seed_glb, "probe_size": 896, "retexture_maps": retexture_maps,
                                 "keep_old_maps": bool(retexture_maps)}, "prepare")
    job.log("  deciding: facing%s%s" % (", glass" if spec.glass and skill["meta"].get("glass_prompt") else "",
                                        ", wheels" if spec.rig and skill["meta"].get("rig_parts_prompt") else ""))
    decision = run_probe(job, skill)
    cockpit = None
    if spec.cockpit and (decision.get("regions") or {}).get("glass"):
        job.log("  cockpit: a second model for the space under the canopy")
        try:
            cockpit = make_cockpit(job, spec, reference)
        except Exception as exc:  # noqa: BLE001 - no cockpit is better than no aircraft
            job.log("  cockpit skipped: %s" % str(exc)[:160])
    part_seeds = []
    seed_defs = skill["meta"].get("part_seeds") if isinstance(skill["meta"].get("part_seeds"), list) else []
    regions = decision.get("regions") or {}
    for i, sd in enumerate(seed_defs[:3]):
        if not regions.get("seed%d" % i):
            continue
        job.log("  part seed: %s" % sd.get("phrase"))
        try:
            ps = make_part_seed(job, spec, sd, reference) if reference else None
            if ps:
                part_seeds.append({**ps, "index": i})
        except Exception as exc:  # noqa: BLE001 - the body ships without the part seed
            job.log("  part seed %s skipped: %s" % (sd.get("name"), str(exc)[:160]))
    job.log("  Blender pass 2: glass slot%s, maps, LODs to %s tris, collision, export" % (
        " + cockpit" if cockpit else "", format(spec.tri_budget, ",")))
    _blender(job, "finish.py", {**common, "render_size": 768, "cockpit_glb": (cockpit or {}).get("glb"),
                                "cockpit_parametric": bool(spec.cockpit and regions.get("glass") and not cockpit),
                                "cockpit_seats": 2 if "two-seat" in (spec.description or "").lower() or "tandem" in (spec.description or "").lower() else 1,
                                "retexture_parts": spec.retexture_parts if retexture_maps else None,
                                "recolor_parts": recolor, "protect_parts": spec.protect_parts,
                                "remove_parts": list(spec.remove_parts or []) or None,
                                "material_families": skill["meta"].get("material_families") if isinstance(skill["meta"].get("material_families"), list) else None,
                                "bake_detail": True, "reproject": bool(skill["meta"].get("reproject", False)),
                                "repair_cylinders": skill["meta"].get("repair_cylinders") if isinstance(skill["meta"].get("repair_cylinders"), list) else None,
                                "part_seeds": part_seeds or None}, "finish")
    report_path = os.path.join(common["out_dir"], "report.json")
    if not os.path.exists(report_path):
        log_path = os.path.join(job.work_dir, "finish.log")
        tail = ""
        if os.path.exists(log_path):
            lines = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
            tail = "\n".join(l for l in lines[-25:] if l.strip())
        raise RuntimeError("Blender finish wrote no report (exit 0). Log tail:\n%s" % tail)
    with open(report_path) as f:
        report = json.load(f)
    report["decision"] = decision
    if spec.category == "environment" and spec.style == "realistic" and reference and os.path.exists(reference):
        try:
            job.log("  tiling PBR material from the reference (Patina)")
            tiles = make_tiles(job, reference, common["out_dir"])
            if tiles:
                report["tiles"] = [os.path.basename(t) for t in tiles]
        except Exception as exc:  # noqa: BLE001 - the asset ships without tiles
            job.log("  tiles skipped: %s" % str(exc)[:160])
    for note in report.get("notes", []):
        if any(w in note for w in ("recolour", "repaint", "protected", "dropped", "WARNING", "cockpit", "canopy", "glass:", "material family", "baked",
                                  "bake ", "removed", "part seed", "cylinder", "reproject")):
            job.log("  blender: %s" % note[:220])
    job.log("  finished: %s tris LOD0, %d maps, %d files%s" % (
        format(report["lods"][0]["triangles"], ","), len(report["maps"]), len(report["files"]),
        (", glass %d faces" % report["glass"]["faces"]) if report.get("glass") else ""))
    return report

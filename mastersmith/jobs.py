"""Whole-job tools: clone a job, run one command over several jobs, and the owner's standard benchmark set.

2026-09-30: Codex re-ran "the test we have been running" (the bullpup, M4A1, tank, Apache, shotgun and seeded Havoc)
by hand - dated copies, its own run_seeds.py and finalize.py - and rebuilt the Havoc from a generic plan: the cockpit
insert and the clean canopy shell of the 9/10 build were not carried, and the same pictures and model scored 5/10.
A clone carries the tuned plan and every other part, so a re-seed changes only the seed. The Proteus weapons were
seeded and assembled four at a time by shell scripts in another repo (2026-10-01): `ms batch` does that here."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, ledger

# what a part folder holds besides its seed: its pictures and builders are the asset's source (AGENTS.md rule 6)
PART_SOURCES = ("side.png", "quarter.png", "build.py", "sdf.py", "fit_card.png", "cabin.json", "brush_log.json")
# a seed and what was made from it
SEED_FILES = ("seed.glb", "registered.blend", "registered_unfitted.blend", "registered_unbrushed.blend",
              "registered_before_retexture.blend", "retextured.glb", "registration.json", "seed_render.png",
              "seed_views.png", "fit.json", "fit_report.json", "import.json", "brush_report.json", "retexture.json")
SPENDING = ("seed", "picture", "view", "views", "mesh", "part-pictures", "retexture", "segment")
BENCH_FILE = config.ROOT / "mastersmith" / "bench.json"


def _swap_paths(value, old, new):
    """Every string in a JSON value with the old job folder replaced by the new one (both slash styles)."""
    if isinstance(value, dict):
        return {k: _swap_paths(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap_paths(v, old, new) for v in value]
    if isinstance(value, str):
        for o, n in ((old, new), (old.replace("\\", "/"), new.replace("\\", "/"))):
            value = value.replace(o, n)
    return value


def _copy(src, dst, old, new):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if src.endswith(".json"):
        try:
            data = json.load(open(src, encoding="utf-8"))
        except ValueError:
            shutil.copy2(src, dst)
            return
        json.dump(_swap_paths(data, old, new), open(dst, "w", encoding="utf-8"), indent=1)
    else:
        shutil.copy2(src, dst)


def clone_job(src, dst, reseed=("Body",), keep_seed=False):
    """out/<src> -> out/<dst>: the brief (renamed), every reference picture, the plan (draft, validated plan, grids,
    dims), and every part's pictures and builders; every part's seed too except the parts in `reseed` (all of them
    with `keep_seed`). No delivery, logs or args files. -> {"copied": n, "seeds_kept": [...], "reseed": [...]}"""
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if not os.path.isfile(os.path.join(src, "brief.json")):
        raise ValueError("%s is not a job (no brief.json)" % src)
    if os.path.exists(dst):
        raise ValueError("%s exists already; pick another name" % dst)
    name = os.path.basename(dst)
    copied, kept, left = 0, [], []
    for rel in ("ref", "plan"):
        for root, _dirs, files in os.walk(os.path.join(src, rel)):
            for f in files:
                if f.endswith((".log", "_args.json")):
                    continue
                s = os.path.join(root, f)
                _copy(s, os.path.join(dst, os.path.relpath(s, src)), src, dst)
                copied += 1
    reseed = {r.lower() for r in reseed or ()}
    parts = os.path.join(src, "parts")
    for part in sorted(os.listdir(parts)) if os.path.isdir(parts) else []:
        pdir = os.path.join(parts, part)
        if not os.path.isdir(pdir):
            continue
        take_seed = keep_seed or part.lower() not in reseed
        for f in sorted(os.listdir(pdir)):
            s = os.path.join(pdir, f)
            if not os.path.isfile(s) or f.endswith((".log", "_args.json")):
                continue
            if f in SEED_FILES and not take_seed:
                continue
            _copy(s, os.path.join(dst, "parts", part, f), src, dst)
            copied += 1
        (kept if take_seed and os.path.exists(os.path.join(pdir, "seed.glb")) else left).append(part)
    brief = json.load(open(os.path.join(src, "brief.json"), encoding="utf-8"))
    brief["name"] = name
    json.dump(brief, open(os.path.join(dst, "brief.json"), "w", encoding="utf-8"), indent=1)
    ledger.record(dst, "clone", **{"from": os.path.basename(src), "seeds_kept": kept, "reseed": left})
    return {"copied": copied + 1, "seeds_kept": kept, "reseed": left}


def bench_set(path=None):
    """The owner's standard benchmark: [{"name", "source", "baseline": {"job", "score"}}] (mastersmith/bench.json)."""
    return json.load(open(path or BENCH_FILE, encoding="utf-8"))["assets"]


def run_one(command, job, extra, log_path):
    """`ms <command> <job> <extra...>` in its own process, its output in log_path. -> (exit code, seconds, last line)"""
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        log.write("# ms %s %s %s (%s)\n" % (command, job, " ".join(extra), time.strftime("%Y-%m-%d %H:%M:%S")))
        log.flush()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        code = subprocess.call([sys.executable, "-m", "mastersmith.ms", command, job, *extra], stdout=log,
                               stderr=subprocess.STDOUT, cwd=str(config.ROOT), env=env)
    lines = [l for l in open(log_path, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    return code, time.time() - t0, (lines[-1] if lines else "")


def run_batch(command, jobs, extra=(), parallel=2, log=print):
    """One command over several jobs, `parallel` at a time, a log per job (out/<Name>/batch_<command>.log) and one
    summary line each as they finish. -> [{"job", "exit", "seconds", "last", "log", "gate"}]"""
    extra = list(extra)
    results = []

    def one(job):
        log_path = os.path.join(job, "batch_%s.log" % command)
        code, secs, last = run_one(command, job, extra, log_path)
        gate = None
        rep = os.path.join(job, "delivery", "report.json")
        if command == "assemble" and code == 0 and "--draft" not in extra and os.path.exists(rep):
            gate = (json.load(open(rep, encoding="utf-8")).get("gate") or {}).get("warnings")
        r = {"job": job, "exit": code, "seconds": round(secs), "last": last[:200], "log": log_path, "gate": gate}
        log("  %-40s %s in %4ds  %s" % (os.path.basename(job), "ok  " if code == 0 else "FAIL", secs,
                                        ("gate: %s" % "; ".join(gate)) if gate else "gate ok" if gate == [] else last[:110]))
        return r

    with ThreadPoolExecutor(max_workers=max(1, int(parallel))) as pool:
        results = list(pool.map(one, jobs))
    return results


def split_args(text):
    """--args "..." -> argv list (Windows paths keep their backslashes)."""
    return shlex.split(text or "", posix=os.name != "nt") if text else []

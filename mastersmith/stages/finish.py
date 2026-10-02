"""Running a headless Blender script with a JSON argument file. The one-seed finish (prepare.py / finish.py)
that lived here went with the service (2026-09-28); assemblies run blender/assemble.py through _blender()."""
import json
import os
import subprocess
import time

from .. import config

BLENDER_DIR = config.ROOT / "mastersmith" / "blender"


def _blender(job, script, args, tag, timeout=2400):
    """Run blender/<script> headless and stream its output into <tag>.log as it runs. The log used to be written only
    when Blender exited, so a run in progress showed the PREVIOUS run's log and its traceback was read as current
    (three times on 2026-09-29); now the old log goes first and a header says which run the file is."""
    if not os.path.exists(config.BLENDER_BIN):
        raise RuntimeError("Blender not found at %s (set BLENDER_BIN)" % config.BLENDER_BIN)
    args_path = os.path.join(job.work_dir, "%s_args.json" % tag)
    with open(args_path, "w") as f:
        json.dump(args, f, indent=1)
    cmd = [config.BLENDER_BIN, *config.BLENDER_FLAGS, "--python", str(BLENDER_DIR / script), "--", args_path]
    log_path = os.path.join(job.work_dir, "%s.log" % tag)
    if os.path.exists(log_path):
        os.remove(log_path)
    started = time.time()
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        log.write("# %s started %s (pid of ms %d); this file fills while Blender runs\n" % (
            script, time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            log.write("\n# stopped after %d s (timeout)\n" % timeout)
            raise RuntimeError("Blender %s ran past %d s and was stopped; see %s" % (script, timeout, log_path))
        log.write("\n# %s finished in %.0f s, exit %s\n" % (script, time.time() - started, code))
    if code != 0:
        lines = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
        tail = "\n".join(lines[-18:])
        raise RuntimeError("Blender %s failed (exit %s); see %s\n%s" % (script, code, log_path, tail))

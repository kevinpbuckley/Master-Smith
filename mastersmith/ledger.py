"""out/<Name>/decisions.json: what the owner decided for a job and what it has cost, one entry per paid call or note.
After a context compaction the agent no longer knew which picture and seed models the owner had picked or how much
had been spent (2026-09-30/10-01); `ms status` prints this, the commands that spend append to it, `ms note` records
the owner's words."""
import json
import os
import time

FILE = "decisions.json"


def load(job_dir):
    path = os.path.join(job_dir, FILE)
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []


def record(job_dir, kind, **fields):
    """Append one entry {"when", "kind", ...}; a ledger that cannot be written never stops the command."""
    try:
        entries = load(job_dir)
        entries.append({"when": time.strftime("%Y-%m-%d %H:%M"), "kind": kind,
                        **{k: v for k, v in fields.items() if v is not None}})
        with open(os.path.join(job_dir, FILE), "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=1)
    except OSError:
        pass


def summary(entries):
    """-> {"spent_usd", "models": {kind: [models in order of first use]}, "notes": [...], "calls": n}"""
    spent, models, notes = 0.0, {}, []
    for e in entries:
        spent += float(e.get("usd") or 0)
        if e.get("model"):
            seen = models.setdefault(e["kind"], [])
            if e["model"] not in seen:
                seen.append(e["model"])
        if e["kind"] in ("note", "clone"):
            notes.append("%s %s" % (e["when"], e.get("text") or e.get("from") or ""))
    return {"spent_usd": round(spent, 2), "models": models, "notes": notes,
            "calls": sum(1 for e in entries if e["kind"] not in ("note", "clone"))}

"""delivery/scorecard.json from a round's review.json (the median of the independent reviewers), and the round's
files kept beside it (2026-10-23, the local run of the Mk II after the cloud test).
    python cloud/scorecard.py <job dir> <round dir> <fal spent so far>
Copies preview_views.png, report.json, plan.json, plan_draft.json and the package output into the round folder,
writes <round>/scorecard.json and <job>/delivery/scorecard.json ({"score", "spent", "defects", "scorer"})."""
import json
import os
import shutil
import sys


def main(job, rnd, spent):
    rev = json.load(open(os.path.join(rnd, "review.json"), encoding="utf-8"))
    defects = []
    for c in rev.get("top_changes", []):
        line = "%s/%s: %s" % (c.get("view", "?"), c.get("part", "?"), c.get("wrong", ""))
        if line not in defects:
            defects.append(line)
    card = {"score": rev["overall"], "owner_score": None, "scorer": "median of %d reviewers" % len(rev["reviewers"]),
            "spent": float(spent), "gates_pass": rev["all_gates_pass"], "criteria": rev["scores"], "defects": defects[:8]}
    for src in ("delivery/preview_views.png", "delivery/report.json", "plan/plan.json", "plan/plan_draft.json",
                "delivery/package.txt"):
        p = os.path.join(job, src)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(rnd, os.path.basename(src)))
    for p in (os.path.join(rnd, "scorecard.json"), os.path.join(job, "delivery", "scorecard.json")):
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(card, f, indent=1)
    print("scorecard %.2f (%s), %d defects -> %s" % (card["score"], "gates pass" if card["gates_pass"] else "a gate FAILS",
                                                     len(defects), rnd))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 0)

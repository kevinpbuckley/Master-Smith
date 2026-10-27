"""Combine the independent reviews of one round into a median score.
    python output/median_review.py output/rounds/NN
Reads review_r*.json in that folder and writes review.json:
- the median overall (used for the stop condition and for regression decisions),
- the median per criterion,
- the gates (a gate passes only if every reviewer passed it),
- all reviewers' top_changes, in reviewer order.
It also prints a one-line summary for REVIEW_LOG.md."""
import glob, json, os, statistics, sys

W = {"silhouette": 25, "cockpit": 20, "pods": 15, "control_surfaces": 10, "surface_detail": 15, "materials": 15}


def main(folder):
    paths = sorted(glob.glob(os.path.join(folder, "review_r*.json")))
    revs = [json.load(open(p)) for p in paths]
    if not revs:
        sys.exit("no review_r*.json in " + folder)
    overall = [float(r["overall"]) for r in revs]
    med = {k: statistics.median(float(r["scores"][k]) for r in revs) for k in W}
    gates = {}
    for g in ("1", "2", "3", "4", "5"):
        ok = all(r["gates"][g]["pass"] for r in revs)
        gates[g] = {"pass": ok, "notes": [r["gates"][g]["note"] for r in revs]}
    out = {
        "reviewers": [os.path.basename(p) for p in paths],
        "overall_each": overall,
        "overall": statistics.median(overall),
        "scores": med,
        "weighted_mean_of_median_scores": round(sum(med[k] * W[k] for k in W) / 100.0, 3),
        "gates": gates,
        "all_gates_pass": all(v["pass"] for v in gates.values()),
        "summaries": [r.get("summary", "") for r in revs],
        "top_changes": [dict(c, reviewer=i + 1) for i, r in enumerate(revs) for c in r.get("top_changes", [])],
    }
    json.dump(out, open(os.path.join(folder, "review.json"), "w"), indent=1)
    print("overall each %s -> median %.3f | median criteria %s | gates %s" % (
        overall, out["overall"], {k: med[k] for k in W}, "all pass" if out["all_gates_pass"] else "FAIL"))


if __name__ == "__main__":
    main(sys.argv[1])

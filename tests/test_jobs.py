"""Clone, the decisions ledger, the batch guard and the bench set (2026-10-02, from the logs of 2026-09-29 to 10-01: a
re-run lost a tuned plan, a compacted context lost the owner's model picks, batches were shell loops elsewhere)."""
import argparse
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastersmith import jobs, ledger  # noqa: E402


def _job(root, name):
    d = os.path.join(root, name)
    for sub in ("ref", "plan", "parts/Body", "parts/Cockpit", "delivery"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    json.dump({"name": name, "description": "x", "category": "aircraft", "size_m": 14}, open(os.path.join(d, "brief.json"), "w"))
    open(os.path.join(d, "ref", "ref_0.png"), "wb").write(b"png")
    json.dump({"parts": [{"name": "Body", "zones": [{"name": "Canopy", "shell": True}]}],
               "side": os.path.join(d, "plan", "side.png")}, open(os.path.join(d, "plan", "plan.json"), "w"))
    for part in ("Body", "Cockpit"):
        for f in ("side.png", "seed.glb", "registered.blend", "registration.json", "seed_render.png"):
            open(os.path.join(d, "parts", part, f), "wb").write(b"x")
    open(os.path.join(d, "delivery", "SM_x.glb"), "wb").write(b"x")
    open(os.path.join(d, "assemble.log"), "w").write("old")
    return d


def test_clone_carries_the_plan_and_the_other_parts_not_the_reseeded_seed():
    with tempfile.TemporaryDirectory() as root:
        src = _job(root, "Havoc")
        dst = os.path.join(root, "Havoc_tripo_20261002")
        res = jobs.clone_job(src, dst)
        assert res["seeds_kept"] == ["Cockpit"] and res["reseed"] == ["Body"]
        assert os.path.exists(os.path.join(dst, "parts", "Body", "side.png"))          # its picture: the source
        assert not os.path.exists(os.path.join(dst, "parts", "Body", "seed.glb"))     # its seed: made again
        assert os.path.exists(os.path.join(dst, "parts", "Cockpit", "registered.blend"))
        assert not os.path.exists(os.path.join(dst, "delivery")) and not os.path.exists(os.path.join(dst, "assemble.log"))
        plan = json.load(open(os.path.join(dst, "plan", "plan.json")))
        assert plan["parts"][0]["zones"][0]["shell"] is True                          # the tuned plan came along
        assert plan["side"].startswith(dst)                                            # its paths point at the clone
        assert json.load(open(os.path.join(dst, "brief.json")))["name"] == "Havoc_tripo_20261002"
        assert ledger.load(dst)[0]["kind"] == "clone"
        with pytest.raises(ValueError):
            jobs.clone_job(src, dst)                                                   # never over an existing job
        keep = jobs.clone_job(src, os.path.join(root, "Havoc_rebuild"), keep_seed=True)
        assert sorted(keep["seeds_kept"]) == ["Body", "Cockpit"]


def test_ledger_keeps_models_money_and_notes():
    with tempfile.TemporaryDirectory() as d:
        ledger.record(d, "picture", model="nano-pro", usd=0.15)
        ledger.record(d, "seed", model="tripo", usd=0.6)
        ledger.record(d, "seed", model="tripo", usd=0.6)
        ledger.record(d, "note", text="owner: use tripo, references approved")
        s = ledger.summary(ledger.load(d))
        assert s["spent_usd"] == 1.35 and s["calls"] == 3
        assert s["models"] == {"picture": ["nano-pro"], "seed": ["tripo"]}
        assert "use tripo" in s["notes"][0]


def test_batch_refuses_to_spend_without_yes(monkeypatch):
    from mastersmith import ms
    with tempfile.TemporaryDirectory() as root:
        _job(root, "A")
        a = argparse.Namespace(command="seed", jobs=[os.path.join(root, "A")], parallel=2, args="--model meshy7", yes=False)
        with pytest.raises(SystemExit) as e:
            ms.cmd_batch(a)
        assert "spends money" in str(e.value) and "--yes" in str(e.value)


def test_bench_set_names_existing_kinds_of_source():
    assets = jobs.bench_set()
    names = {a["name"] for a in assets}
    assert {"BullpupCarbineMk2", "M4A1", "MainBattleTank", "AH64Apache", "PumpShotgun", "HavocGunship"} <= names
    assert all(a["source"] and a["baseline"]["score"] for a in assets)

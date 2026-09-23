"""Pure tests: no network, no Blender. python -m pytest -q"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from mastersmith import config, pricing, skills  # noqa: E402
from mastersmith.spec import Spec  # noqa: E402
from mastersmith.stages.seed import seed_payload  # noqa: E402
from mastersmith.wallet import InsufficientCredits, Wallet  # noqa: E402


def test_spec_defaults_by_category():
    s = Spec(name="my sniper rifle", description="x", category="weapon")
    assert s.name == "MySniperRifle"
    assert s.tri_budget == 60000 and s.size_m == 1.0 and s.multiview
    c = Spec(name="Orc", description="x", category="character")
    assert c.multiview is False and c.size_m == 1.8
    assert Spec(name="RustyOilDrum", description="x").name == "RustyOilDrum"
    assert Spec(name="rusty oil-drum", description="x").name == "Rusty_oil-drum" or Spec(name="rusty oil-drum", description="x").name == "RustyOilDrum"
    assert Spec(name="QA_Smith_Crate", description="x").name == "QA_Smith_Crate"
    assert Spec(name="Crate", description="x", category="prop").multiview is False
    assert Spec(name="Crate", description="x", category="prop", multiview=True).multiview is True
    assert Spec(name="J", description="x", category="vehicle").glass is True and Spec(name="J", description="x", category="vehicle").rig is False
    assert Spec(name="J", description="x", category="vehicle").multiview is True   # issue #8: guarded orthographic views since 2026-09-18
    assert Spec(name="O", description="x", category="character").rig is True
    assert Spec(name="C", description="x", category="prop").glass is False


def test_estimate_prices_rig_and_glass():
    veh = pricing.estimate(Spec(name="J", description="x", category="vehicle"))
    veh_rig = pricing.estimate(Spec(name="J", description="x", category="vehicle", rig=True))
    assert veh_rig["usd"] - veh["usd"] >= pricing.price("fal-ai/hunyuan-3d/v3.1/part")
    chara = pricing.estimate(Spec(name="O", description="x", category="character"))
    assert any("Meshy" in name for name, _ in chara["steps"])
    assert any("glass masks" in name for name, _ in veh["steps"])
    junk = Spec.from_dict({"name": "", "description": "", "category": "spaceship", "engine": "cryengine", "bogus": 1})
    assert junk.category == "prop" and junk.engine == "unreal" and junk.name == "Asset"


def test_tripo_prices_carry_the_surcharges():
    assert pricing.price("tripo3d/h3.1/image-to-3d") == 0.30
    assert pricing.price("tripo3d/h3.1/image-to-3d", {"geometry_quality": "detailed", "texture_quality": "detailed"}) == 0.60
    assert pricing.price("tripo3d/h3.1/multiview-to-3d", {"geometry_quality": "detailed", "texture_quality": "detailed", "quad": True}) == 0.65
    with pytest.raises(pricing.Unpriced):
        pricing.price("fal-ai/some/new/thing")


def test_estimate_is_the_worst_case_and_multiview_costs_more():
    single = pricing.estimate(Spec(name="A", description="x", category="prop", multiview=False))
    multi = pricing.estimate(Spec(name="A", description="x", category="weapon"))
    assert multi["usd"] > single["usd"] >= 0.60
    assert multi["credits"] == config.credits_for_usd(multi["usd"])


def test_seed_payload_switches_to_multiview_with_two_views():
    s = Spec(name="A", description="x", category="weapon")
    model, p = seed_payload(s, ["u1"])
    assert model == config.SEED_MODEL and p["image_url"] == "u1" and p["face_limit"] == 360000
    h = Spec(name="A", description="x", category="weapon", hybrid=True)      # the hybrid seed is opt-in (2026-09-18)
    assert seed_payload(h, ["u1", "u2"])[0] == "fal-ai/meshy/v7/multi-image-to-3d"
    model, p = seed_payload(s, ["u1", "u2", "u3"])
    assert model == config.SEED_MULTIVIEW_MODEL and p["image_urls"] == ["u1", "u2", "u3"]
    tiny = Spec(name="A", description="x", category="prop", tri_budget=2000)
    assert seed_payload(tiny, ["u"])[1]["face_limit"] == 150000


def test_wallet_keeps_score_without_refusing_by_default(monkeypatch):
    monkeypatch.setattr(config, "ENFORCE_CREDITS", False)
    with tempfile.TemporaryDirectory() as d:
        w = Wallet(os.path.join(d, "w.db"))
        hold = w.reserve("kev", 200, "job")          # nothing topped up: the ledger only keeps score
        assert w.balance("kev") == -200
        bill = w.settle(hold, 0.5, "done")
        assert bill["charged"] == 50 and w.balance("kev") == -50
        hold2 = w.reserve("kev", 12, "import")
        bill2 = w.settle(hold2, 0.76, "an imported jet that bought a cockpit")   # past the hold: the true cost is kept
        assert bill2["charged"] == 76 and bill2["refunded"] == -64 and w.balance("kev") == -126
        w.close()      # Windows cannot remove the temp dir while sqlite holds the file


def test_rework_estimate_drops_the_seed_but_keeps_the_cockpit():
    jet = Spec(name="Jet", description="grey attack jet", category="aircraft", size_m=-1)
    full = pricing.estimate(jet)
    re = pricing.estimate_rework(jet, "refinish")
    names = [n for n, _ in re["steps"]]
    assert not any(n.startswith("3D seed") for n in names)
    assert not any(n.startswith(pricing.PICTURE_STEPS) for n in names)
    assert any(n.startswith("cockpit") for n in names)
    assert 0 < re["usd"] < full["usd"]
    rt = pricing.estimate_rework(Spec(name="R", description="rifle", category="weapon", retexture=True), "retexture")
    assert any("repaint of the existing mesh" in n for n, _ in rt["steps"])


def test_wallet_reserve_settle_refund_and_refusal(monkeypatch):
    monkeypatch.setattr(config, "ENFORCE_CREDITS", True)
    monkeypatch.setattr(config, "MARKUP", 1.5)
    with tempfile.TemporaryDirectory() as d:
        w = Wallet(os.path.join(d, "w.db"))
        assert w.balance("kev") == 0
        w.add("kev", 300)
        with pytest.raises(InsufficientCredits):
            w.reserve("kev", 301, "too much")
        hold = w.reserve("kev", 200, "job")
        assert w.balance("kev") == 100
        bill = w.settle(hold, 0.70)          # $0.70 x 1.5 markup = 105 credits
        assert bill["charged"] == config.credits_for_usd(0.70) == 105
        assert bill["refunded"] == 95 and w.balance("kev") == 195
        with pytest.raises(ValueError):
            w.settle(hold, 0.1)
        hold2 = w.reserve("kev", 50, "cancelled")
        assert w.release(hold2)["refunded"] == 50 and w.balance("kev") == 195
        w.close()      # Windows cannot remove the temp dir while sqlite holds the file


def test_reference_lists_and_research_defaults():
    s = Spec(name="Jeep", description="x", category="vehicle", reference_image="a.png", reference_images=["b.png", "a.png"])
    assert s.reference_images == ["a.png", "b.png"] and s.reference_image == "a.png" and s.research is False
    r = Spec(name="Jeep", description="x", category="vehicle", search_query="  Willys   MB  jeep ")
    assert r.search_query == "Willys MB jeep" and r.research is True
    assert Spec(name="X", description="x", search_query="Willys MB", reference_images=["p.png"]).research is False
    from mastersmith.stages.research import query_words, relevant_to
    assert query_words("G-Police Havoc gunship side view") == {"police", "havoc", "gunship"}
    assert relevant_to("Willys MB jeep", {"title": "1943 Willys MB", "image": "https://x/y.jpg"})
    assert not relevant_to("Willys MB jeep", {"title": "letter W wallpaper", "image": "https://x/w.jpg"})


def test_skills_load_front_matter():
    for cat in ("weapon", "vehicle", "aircraft", "helicopter", "character", "prop", "environment"):
        s = skills.load(cat)
        assert s["meta"]["reference_view"] and s["meta"]["origin"] in ("bottom", "center")
        assert s["meta"]["forward_axis"] in ("long", "up") and len(s["body"]) > 200
    assert skills.load("nonsense")["meta"]["default_size_m"] == 1.0


def test_gate_and_package_on_a_synthetic_delivery():
    from mastersmith.stages.gate import check
    from mastersmith.stages.package import write_package
    spec = Spec(name="Crate", description="a crate", category="prop", size_m=0.6, tri_budget=30000)
    with tempfile.TemporaryDirectory() as d:
        for fn in ("SM_Crate.fbx", "T_Crate_BC.png"):
            open(os.path.join(d, fn), "wb").write(b"x")
        report = {"lods": [{"lod": 0, "triangles": 29990}], "maps": [{"role": "BC"}, {"role": "N"}, {"role": "ORM"}],
                  "dimensions_m": [0.6, 0.4, 0.5], "collision": {"triangles": 72}, "files": ["SM_Crate.fbx", "T_Crate_BC.png"],
                  "roughness_mean": 0.55}
        g = check(spec, report, {"score": 7, "issues": []}, d)
        assert g["ok"], g
        bad = check(spec, {**report, "maps": [{"role": "BC"}], "dimensions_m": [1.2, 0.4, 0.5]}, {"score": 3, "issues": ["melted"]}, d)
        assert not bad["ok"] and any("normal map" in w for w in bad["warnings"]) and any("size" in w for w in bad["warnings"])
        pkg = write_package(spec, report, {"review": {"score": 7, "verdict": "ship", "issues": []}, "gate": g}, d)
        assert os.path.exists(os.path.join(d, pkg["zip"])) and os.path.exists(os.path.join(d, "README.txt"))
        assert "Unreal Engine import" in open(os.path.join(d, "README.txt")).read()


def test_brief_fix_category():
    from mastersmith.brief import fix_category
    assert fix_category("vehicle", "F-16C Fighting Falcon fighter jet, grey") == "aircraft"
    assert fix_category("vehicle", "AH-64 Apache attack helicopter") == "helicopter"
    assert fix_category("vehicle", "M1A2 Abrams main battle tank") == "vehicle"
    assert fix_category("weapon", "jet black rifle") == "weapon"


def test_edit_prompt_keeps_unmentioned_design():
    from mastersmith import skills
    from mastersmith.spec import Spec
    from mastersmith.stages.reference import edit_prompt
    spec = Spec(name="Raven", description="bullpup rifle, amber magazine", category="weapon",
                edit_instructions="seat the magazine like an SA80 magazine")
    p = edit_prompt(spec, skills.load("weapon"))
    assert "Change ONLY this: seat the magazine like an SA80 magazine" in p
    assert "Keep every other detail" in p
    plain = edit_prompt(Spec(name="Raven", description="bullpup rifle", category="weapon"), skills.load("weapon"))
    assert "Recreate this exact object" in plain


def test_portable_spec_drops_local_pictures():
    from mastersmith.spec import Spec
    sp = Spec(name="R", description="rifle", category="weapon", reference_images=["/job/abc/previous_reference.png", "https://cdn/x.png"])
    d = sp.portable()
    assert d["reference_images"] == ["https://cdn/x.png"] and d["reference_image"] == "https://cdn/x.png"
    sp2 = Spec.from_dict({**sp.to_dict(), "reference_images": ["/job/abc/previous_reference.png"]}).drop_local_pictures()
    assert sp2.reference_images == [] and sp2.reference_image == ""
    # an override that names a URL wins over a stale stored primary
    sp3 = Spec.from_dict({**sp.to_dict(), "reference_image": "https://cdn/v1.png", "reference_images": ["https://cdn/v1.png"]})
    assert sp3.reference_images[0] == "https://cdn/v1.png"


def test_image_client_and_cost_breakdown():
    import base64
    import io
    import json as _json

    from PIL import Image

    from mastersmith import images as im_mod
    from mastersmith.images import ImageRefused, Images
    from mastersmith.pipeline import Job
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, format="PNG")
    good = {"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode(), "media_type": "image/png"}], "usage": {"cost": 0.0123}}

    class Resp:
        def __init__(self, status, body, text=""):
            self.status_code, self._body, self.text = status, body, text or _json.dumps(body)

        def json(self):
            return self._body

    class Http:
        def __init__(self, answers):
            self.answers, self.sent = list(answers), []

        def post(self, url, headers=None, data=None, timeout=None):
            self.sent.append(_json.loads(data))
            return self.answers.pop(0)
    monkeypatch_sleep = im_mod.time.sleep
    im_mod.time.sleep = lambda s: None
    try:
        cl = Images(key="k", log=lambda m: None)
        with tempfile.TemporaryDirectory() as d:
            cl.http = Http([Resp(200, good)])
            cl.stage = "reference"
            out = cl.generate("a crate", os.path.join(d, "a.png"), model="google/gemini-3.1-flash-image", references=[])
            assert Image.open(out).size == (8, 8) and cl.spent() == 0.0123 and cl.calls[0]["stage"] == "reference"
            cl.http = Http([Resp(200, good)])
            cl.generate("edit", os.path.join(d, "b.png"), model="google/gemini-3.1-flash-image", references=[out, "https://x/y.png"])
            refs = cl.http.sent[-1]["input_references"]
            assert refs[0]["image_url"]["url"].startswith("data:image/png;base64,") and refs[1]["image_url"]["url"] == "https://x/y.png"
            cl.http = Http([Resp(400, {"error": {"message": "Gemini could not generate an image (STOP)"}}, "could not generate")])
            with pytest.raises(ImageRefused):
                cl.generate("gore", os.path.join(d, "c.png"), model="google/gemini-3.1-flash-image")
            with pytest.raises(pricing.Unpriced):
                cl.generate("x", os.path.join(d, "f.png"), model="nobody/unknown-image")
    finally:
        im_mod.time.sleep = monkeypatch_sleep

    class Calls:
        def __init__(self):
            self.calls, self.stage = [], ""

        def spent(self):
            return sum(c["usd"] for c in self.calls)
    with tempfile.TemporaryDirectory() as d:
        old = config.OUT_DIR
        config.OUT_DIR = __import__("pathlib").Path(d)
        try:
            job = Job(Spec(name="X", description="x"), "u", None, log=lambda m: None, llm=Calls(), fal=Calls(), images=Calls(), job_id="t")
        finally:
            config.OUT_DIR = old
        job.stage("seed")
        job.fal.calls.append({"usd": 0.6, "stage": job.fal.stage})
        job.stage("repaint")
        job.images.calls.append({"usd": 0.07, "stage": job.images.stage})
        job.llm.calls.append({"usd": 0.01, "stage": job.llm.stage})
        bs = job.by_stage()
        assert bs["seed"]["usd"] == 0.6 and bs["seed"]["fal_calls"] == 1 and bs["repaint"] == {"usd": 0.08, "pictures": 1, "fal_calls": 0, "llm_calls": 1}
        assert job.breakdown_text().startswith("seed $0.60 (88%)") and abs(job.spent_usd() - 0.68) < 1e-9


def test_repaint_mode_and_estimate():
    from mastersmith.stages.repaint import fit_to_render
    import numpy as np
    from PIL import Image
    assert pricing.repaint_mode(Spec(name="A", description="x")) in ("meshy", "pictures")
    assert pricing.repaint_mode(Spec(name="A", description="x", repaint="pictures")) == "pictures"
    a = pricing.estimate(Spec(name="A", description="x", category="weapon", hybrid=True, repaint="meshy"))
    b = pricing.estimate(Spec(name="A", description="x", category="weapon", hybrid=True, repaint="pictures"))
    assert any("Meshy retexture" in n for n, _ in a["steps"]) and any("picture model" in n for n, _ in b["steps"])
    with tempfile.TemporaryDirectory() as d:
        ren = np.full((200, 200, 3), 140, np.uint8)
        ren[40:160, 30:170] = 30
        pic = np.full((200, 200, 3), 250, np.uint8)
        pic[70:150, 60:140] = (90, 120, 60)
        rp, pp, out = [os.path.join(d, n) for n in ("r.png", "p.png", "o.png")]
        Image.fromarray(ren).save(rp)
        Image.fromarray(pic).save(pp)
        path, box, ov = fit_to_render(pp, rp, out)
        assert path == out and box == (30, 40, 170, 160) and ov > 0.9


def test_provider_balances_and_affordability(monkeypatch):
    from mastersmith import providers

    class R:
        def __init__(self, text=None, js=None):
            self.text, self._js = text, js

        def raise_for_status(self):
            pass

        def json(self):
            return self._js

    def fake_get(url, headers=None, timeout=None):
        if url == providers.FAL_BALANCE:
            return R(text="135.5861")
        if url == providers.OPENROUTER_CREDITS:
            return R(js={"data": {"total_credits": 870, "total_usage": 712.26}})
        return R(js={"data": {"usage_daily": 0.16, "usage_weekly": 11.75, "usage_monthly": 568.56, "limit": None}})

    monkeypatch.setattr(providers.requests, "get", fake_get)
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    d = providers.balances(force=True)
    assert d["fal"]["usd"] == 135.5861 and d["openrouter"]["usd"] == 157.74 and d["openrouter"]["key_usage_month_usd"] == 568.56
    assert providers.short(d) == "fal $135.59, OpenRouter $157.74"
    providers.check_affordable(100.0, d)
    with pytest.raises(providers.ProviderBalanceLow):
        providers.check_affordable(140.0, d)
    unknown = {"fal": None, "openrouter": None, "errors": {"fal": "down"}, "checked": 0}
    providers.check_affordable(1e6, unknown)       # an outage never blocks a build

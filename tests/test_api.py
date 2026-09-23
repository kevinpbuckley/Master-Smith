"""The HTTP surface with a fixed key from the environment, against a temporary data directory and no worker.
Nothing here reaches fal, OpenRouter or Blender."""
import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEY = "ms_test_made_up"


@pytest.fixture(scope="module")
def client():
    httpx = pytest.importorskip("httpx")  # noqa: F841 - the FastAPI test client needs it
    from fastapi.testclient import TestClient
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="ms-api-"))
    os.environ["MASTERSMITH_NO_WORKER"] = "1"           # read at startup: jobs queue but never run
    from mastersmith import config, providers
    service = importlib.import_module("mastersmith.service")
    from mastersmith.store import Store
    from mastersmith.wallet import Wallet
    # point the running module at a scratch data directory and a fixed key without re-importing anything
    saved = {k: getattr(config, k) for k in ("API_KEY", "DATA_DIR", "OUT_DIR", "UPLOADS_DIR", "DB_PATH")}
    config.API_KEY, config.DATA_DIR = KEY, tmp
    config.OUT_DIR, config.UPLOADS_DIR, config.DB_PATH = tmp / "out", tmp / "uploads", tmp / "test.db"
    service.store, service.wallet = Store(config.DB_PATH), Wallet(config.DB_PATH)
    providers._cache.update(at=9e12, data={"fal": {"usd": 50.0}, "openrouter": {"usd": 50.0}, "errors": {}, "checked": 0})
    with TestClient(service.app) as c:
        yield c
    for k, v in saved.items():
        setattr(config, k, v)
    providers._cache.update(at=0.0, data=None)


def test_fixed_key_is_required_and_accepted(client):
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    me = client.get("/v1/me", headers={"X-API-Key": KEY}).json()
    assert me["user"] == "agent" and me["role"] == "admin" and me["local_mode"] is False
    h = client.get("/healthz").json()
    assert h["ok"] and h["local_mode"] is False and h["worker"] is False


def test_config_hides_secrets(client):
    c = client.get("/v1/config", headers={"Authorization": "Bearer " + KEY}).json()
    assert c["keys_set"]["MASTERSMITH_API_KEY"] is True
    assert KEY not in str(c) and "SEED_MODEL" in c and "prop" in c["categories"]


def test_dry_run_estimates_without_queueing(client):
    H = {"Authorization": "Bearer " + KEY}
    r = client.post("/v1/jobs?dry_run=1", headers=H, json={"spec": {"name": "crate", "category": "prop", "description": "oak crate"}})
    assert r.status_code == 200
    j = r.json()
    assert j["dry_run"] and j["brief"]["name"] == "crate" and j["brief"]["tri_budget"] == 30000 and j["estimate_usd"] > 0 and j["steps"]
    assert j["providers"]["fal"]["usd"] == 50.0
    assert client.get("/v1/jobs", headers=H).json() == []


def test_queue_poll_log_and_debug(client):
    H = {"Authorization": "Bearer " + KEY}
    r = client.post("/v1/jobs", headers=H, json={"spec": {"name": "Crate", "category": "prop", "description": "oak crate"}})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert r.json()["status"] == "queued"
    job = client.get("/v1/jobs/%s" % jid, headers=H).json()
    assert job["status"] == "queued" and job["spec"]["name"] == "Crate"
    assert client.get("/v1/jobs/%s/log" % jid, headers=H).text == ""
    dbg = client.get("/v1/jobs/%s/debug" % jid, headers=H).json()
    assert dbg["id"] == jid and dbg["work_files"] == [] and dbg["blender_logs"] == {}
    assert client.get("/v1/jobs/%s/work/nothing.png" % jid, headers=H).status_code == 404
    assert client.get("/v1/jobs/unknown", headers=H).status_code == 404


def test_build_refused_when_a_provider_cannot_cover_it(client):
    from mastersmith import providers
    H = {"Authorization": "Bearer " + KEY}
    saved = dict(providers._cache["data"])
    providers._cache["data"] = {**saved, "fal": {"usd": 0.05}}
    try:
        r = client.post("/v1/jobs", headers=H, json={"spec": {"name": "Jet", "category": "aircraft", "description": "grey jet"}})
        assert r.status_code == 402 and "provider balance too low" in r.json()["detail"]["error"]
    finally:
        providers._cache["data"] = saved


def test_upload_rejects_other_types_and_keeps_models(client):
    H = {"Authorization": "Bearer " + KEY}
    r = client.post("/v1/uploads", headers=H, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/v1/uploads", headers=H, files={"file": ("thing.glb", b"glTF\x02\x00\x00\x00", "model/gltf-binary")})
    assert r.status_code == 200 and r.json()["kind"] == "mesh" and os.path.isfile(r.json()["path"])
    r2 = client.post("/v1/jobs/import", headers=H, json={"path": r.json()["path"], "spec": {"category": "prop"}})
    assert r2.status_code == 200 and r2.json()["kind"] == "rework"
    bad = client.post("/v1/jobs/import", headers=H, json={"path": "C:/Windows/notepad.exe", "spec": {}})
    assert bad.status_code == 400


def test_sessions_are_absent_until_a_chat_turn(client):
    H = {"Authorization": "Bearer " + KEY}
    assert client.get("/v1/sessions/none", headers=H).status_code == 404
    assert client.delete("/v1/sessions/none", headers=H).json() == {"dropped": False}


def test_models_list_prices_and_the_env_default_first(client):
    from mastersmith import config, providers
    H = {"Authorization": "Bearer " + KEY}
    fake = {config.DIRECTOR_MODEL: {"name": "d", "context": 1, "in_per_m": 0.75, "out_per_m": 3.75, "tools": True, "vision": True},
            "deepseek/deepseek-v4.1-flash": {"name": "ds", "context": 1, "in_per_m": 0.1, "out_per_m": 0.5, "tools": True, "vision": True},
            "vendor/tool-only": {"name": "t", "context": 1, "in_per_m": 1, "out_per_m": 2, "tools": True, "vision": False},
            "vendor/vision-tools": {"name": "v", "context": 1, "in_per_m": 3, "out_per_m": 4, "tools": True, "vision": True}}
    providers._models_cache.update(at=9e12, data=fake)
    try:
        m = client.get("/v1/models", headers=H).json()
        ids = [d["id"] for d in m["director_models"]]
        assert ids[0] == config.DIRECTOR_MODEL and "(default)" in m["director_models"][0]["label"]
        assert "$0.75 in / $3.75 out per 1M" in m["director_models"][0]["label"]
        assert "deepseek/deepseek-v4.1-flash" in ids and "vendor/vision-tools" not in ids and not m["all_models"]
        m2 = client.get("/v1/models?all=1", headers=H).json()
        ids2 = [d["id"] for d in m2["director_models"]]
        assert ids2[0] == config.DIRECTOR_MODEL and "vendor/vision-tools" in ids2 and "vendor/tool-only" not in ids2 and m2["all_models"]
        assert [v["key"] for v in m["seed_vendors"]][0] == "tripo" and m["seed_vendors"][0]["usd"] == 0.6
    finally:
        providers._models_cache.update(at=0.0, data=None)


def test_jfif_and_webp_uploads_become_png(client):
    import io
    from PIL import Image
    H = {"Authorization": "Bearer " + KEY}
    for ext, fmt, mime in ((".jfif", "JPEG", "image/jpeg"), (".webp", "WEBP", "image/webp")):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, fmt)
        r = client.post("/v1/uploads", headers=H, files={"file": ("photo" + ext, buf.getvalue(), mime)})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["kind"] == "image" and j["name"] == "photo.png" and j["path"].endswith(".png") and os.path.isfile(j["path"])
        assert Image.open(j["path"]).size == (8, 8)
    bad = client.post("/v1/uploads", headers=H, files={"file": ("broken.jfif", b"not a picture", "image/jpeg")})
    assert bad.status_code == 415

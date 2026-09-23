"""HTTP service: chat with the director, upload pictures and models, queue builds, poll jobs, fetch files, see the spend.
    python -m mastersmith serve --port 8080
Auth: with no API keys created, every request is the local admin user (a single-user machine). Create keys with
`python -m mastersmith keys create <user>` and requests then need `Authorization: Bearer ms_...`.
The worker thread runs inside this process unless MASTERSMITH_NO_WORKER=1 (then run `python -m mastersmith worker`)."""
import json
import mimetypes
import os
import re
import threading
import time
import uuid

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import config, pricing, providers
from .agent import Director
from .pipeline import MESH_EXTENSIONS, seed_of
from .spec import Spec
from .store import Store
from .wallet import Wallet
from .worker import Worker, new_job_id

app = FastAPI(title="Master Smith", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store = Store()
wallet = Wallet()
_lock = threading.Lock()
_sessions = {}          # session_id -> {"director": Director, "user": str, "touched": float}
SESSION_TTL = 6 * 3600
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
LOCAL_USER = {"user": "local", "role": "admin"}


@app.on_event("startup")
def _start():
    os.makedirs(config.UPLOADS_DIR, exist_ok=True)
    if os.environ.get("MASTERSMITH_NO_WORKER") != "1":
        Worker(store, wallet).start()


# ------------------------------------------------------------------ auth
def auth(authorization: str = Header(default="")):
    key = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    if not store.has_keys():
        return dict(LOCAL_USER)             # nobody created a key: this is one person's machine
    who = store.user_for_key(key)
    if not who:
        raise HTTPException(401, "missing or unknown API key")
    return who


def admin(who=Depends(auth)):
    if who["role"] != "admin":
        raise HTTPException(403, "admin key required")
    return who


# ------------------------------------------------------------------ models
class Attachment(BaseModel):
    path: str
    name: str = ""
    kind: str = ""          # "image" | "mesh" (filled in by /v1/uploads)


class ChatIn(BaseModel):
    message: str
    session_id: str = "default"
    attachments: list[Attachment] = []


class JobIn(BaseModel):
    spec: dict


class ImportIn(BaseModel):
    path: str               # a path returned by /v1/uploads
    spec: dict = {}         # name, category, size_m (omit to keep the file's size), tri_budget, glass, rig, engine


class RefinishIn(BaseModel):
    source_job: str
    overrides: dict = {}


class CreditsIn(BaseModel):
    user: str
    credits: int
    note: str = "admin top-up"


# ------------------------------------------------------------------ helpers
def _upload_path_ok(path):
    """Only files under the uploads directory (or a finished job's output) may seed a job."""
    try:
        real = os.path.realpath(path)
    except (TypeError, ValueError):
        return False
    roots = (os.path.realpath(config.UPLOADS_DIR), os.path.realpath(config.OUT_DIR))
    return os.path.isfile(real) and any(real.startswith(r + os.sep) for r in roots)


def last_seed(user, job_id):
    """The mesh and reference picture of a finished job, for a chat that goes on changing the same model."""
    if not job_id:
        return None
    row = store.job(job_id, user)
    if not row or row["status"] != "done":
        return None
    r = row.get("result") or {}
    glb = seed_of(r)
    if not glb:
        return None
    ref = ((r.get("reference") or {}).get("views") or [None])[0]
    return {"glb": glb, "ref": ref if ref and os.path.exists(ref) else None, "spec": r.get("spec") or {}}


def _enqueue(user, spec, kind, source=None):
    if kind in ("refinish", "rework"):     # the seed is reused; only the finishing calls are held
        mode = (source or {}).get("mode") if isinstance(source, dict) else "refinish"
        est = pricing.estimate_rework(spec, mode)
    else:
        est = pricing.estimate(spec)
    credits = est["credits"]
    bal = wallet.balance(user)
    if config.ENFORCE_CREDITS and bal < credits:
        return {"error": "insufficient credits", "needed": credits, "balance": bal}
    try:
        providers.check_affordable(est["usd"])      # a known provider balance below the worst case stops it here
    except providers.ProviderBalanceLow as exc:
        return {"error": "provider balance too low: %s" % exc, "needed_usd": est["usd"], "providers": exc.data}
    job_id = new_job_id()
    store.enqueue(job_id, user, kind, spec.to_dict(), source_job=json.dumps(source) if isinstance(source, dict) else source)
    return {"job_id": job_id, "status": "queued", "kind": kind, "estimate_credits": credits, "balance": bal}


def submit_build(user, spec_dict, seed=None):
    """Queue a build. With `seed` (the session's current model): a repaint keeps the mesh, a change that keeps the
    shape re-finishes it, and a change of shape edits the previous picture rather than redrawing from the text."""
    spec = Spec.from_dict(spec_dict)
    if seed:
        same_shape = all(spec_dict.get(k) == seed["spec"].get(k) for k in ("description", "category", "style"))
        if spec.retexture:
            return _enqueue(user, spec, "rework", {"seed": seed["glb"], "ref": seed["ref"], "mode": "retexture"})
        if same_shape:
            return _enqueue(user, spec, "rework", {"seed": seed["glb"], "ref": seed["ref"], "mode": "refinish"})
        if seed["ref"] and not spec.reference_images:
            spec.reference_images, spec.reference_image = [seed["ref"]], seed["ref"]
            spec.research, spec.search_query = False, ""
            if not spec.edit_instructions:
                spec.edit_instructions = "make it match this description: " + spec.description[:400]
    return _enqueue(user, spec, "build")


def submit_import(user, path, spec_dict):
    if not _upload_path_ok(path) or not path.lower().endswith(MESH_EXTENSIONS):
        return {"error": "not an uploaded model file: %s" % path}
    d = dict(spec_dict or {})
    d.setdefault("name", re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(os.path.basename(path))[0]) or "Imported")
    d.setdefault("description", "imported model")
    d["size_m"] = float(d.get("size_m") or 0) or -1
    return _enqueue(user, Spec.from_dict(d), "rework", {"seed": path, "ref": None, "mode": "refinish"})


def job_view(row, user):
    r = row.get("result") or {}
    delivery = r.get("delivery") or {}
    files = []
    if r.get("delivery_dir") and os.path.isdir(r["delivery_dir"]):
        files = sorted(os.listdir(r["delivery_dir"]))
    return {"id": row["id"], "status": row["status"], "kind": row["kind"], "spec": row["spec"],
            "created": row["created"], "started": row["started"], "finished": row["finished"], "error": row["error"],
            "log": row["log"].splitlines()[-40:],
            "summary": {"lods": delivery.get("lods"), "dimensions_m": delivery.get("dimensions_m"),
                        "glass": delivery.get("glass"), "materials": delivery.get("materials"),
                        "review": r.get("review"), "gate": r.get("gate"), "package": r.get("package"),
                        "rig": {k: v for k, v in (r.get("rig") or {}).items() if k != "notes"},
                        "bill": {k: v for k, v in (r.get("bill") or {}).items() if k not in ("fal_calls", "llm_calls", "image_calls")}},
            "files": ["/v1/jobs/%s/files/%s" % (row["id"], f) for f in files],
            "previews": ["/v1/jobs/%s/files/%s" % (row["id"], f) for f in files if f.startswith("preview_")],
            "glb": next(("/v1/jobs/%s/files/%s" % (row["id"], f) for f in files if f.lower().endswith(".glb") and f.startswith("SM_")), None)}


def _director(session_id, user):
    with _lock:
        now = time.time()
        for sid in [s for s, v in _sessions.items() if now - v["touched"] > SESSION_TTL]:
            _sessions.pop(sid, None)
        key = "%s:%s" % (user, session_id)
        if key not in _sessions:
            d = Director(user, wallet, log=lambda m: None)
            d.submit = lambda spec_dict: submit_build(user, spec_dict, seed=last_seed(user, d.last_job_id))
            d.import_model = lambda path, spec_dict: submit_import(user, path, spec_dict)
            d.job_status = lambda job_id: (lambda row: job_view(row, user) if row else {"error": "unknown job"})(store.job(job_id, user))
            _sessions[key] = {"director": d, "user": user, "touched": now}
        _sessions[key]["touched"] = now
        return _sessions[key]["director"]


def _attachment_note(attachments):
    lines = []
    for a in attachments:
        if not _upload_path_ok(a.path):
            raise HTTPException(400, "attachment is not an uploaded file: %s" % a.name)
        kind = a.kind or ("mesh" if a.path.lower().endswith(MESH_EXTENSIONS) else "image")
        lines.append("- %s %s at path %s" % ("3D model" if kind == "mesh" else "picture", a.name or os.path.basename(a.path), a.path))
    return ("\n\n[Attached files]\n" + "\n".join(lines)) if lines else ""


# ------------------------------------------------------------------ routes
@app.get("/", response_class=HTMLResponse)
def index():
    return ("<!doctype html><title>Master Smith</title><body style='font-family:system-ui;max-width:40em;margin:3em auto'>"
            "<h1>Master Smith API</h1><p>The chat interface is the Next.js app in <code>web/</code> "
            "(<code>npm run dev</code>, http://localhost:3000). This process answers <code>/v1/*</code> and "
            "<code>/healthz</code>; the OpenAPI schema is at <a href='/docs'>/docs</a>.</p></body>")


@app.get("/v1/me")
def me(who=Depends(auth)):
    return {"user": who["user"], "role": who["role"], "balance": wallet.balance(who["user"]),
            "local_mode": not store.has_keys(), "providers": providers.balances(), "jobs": store.jobs_for(who["user"])}


@app.get("/v1/providers")
def provider_balances(refresh: bool = False, who=Depends(auth)):
    """What the fal and OpenRouter accounts behind this instance have left (cached a minute; ?refresh=1 re-reads)."""
    return providers.balances(force=refresh)


@app.post("/v1/uploads")
async def upload(file: UploadFile = File(...), who=Depends(auth)):
    """Store a picture or a 3D model for the chat to use; returns the path to put in the message's attachments."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(file.filename or "upload"))[:120] or "upload"
    ext = os.path.splitext(name)[1].lower()
    if ext not in MESH_EXTENSIONS + IMAGE_EXTENSIONS:
        raise HTTPException(415, "upload a picture (%s) or a model (%s)" % (", ".join(IMAGE_EXTENSIONS), ", ".join(MESH_EXTENSIONS)))
    folder = os.path.join(config.UPLOADS_DIR, who["user"], uuid.uuid4().hex[:10])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    size = 0
    with open(path, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)
    return {"path": path, "name": name, "kind": "mesh" if ext in MESH_EXTENSIONS else "image", "bytes": size}


@app.post("/v1/chat")
def chat(body: ChatIn, who=Depends(auth)):
    d = _director(body.session_id, who["user"])
    text = body.message + _attachment_note(body.attachments)
    try:
        reply = d.turn(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "director error: %s" % str(exc)[:300])
    return {"reply": reply, "brief": d.spec.to_dict() if d.spec else None, "balance": wallet.balance(who["user"]),
            "providers": providers.balances(), "last_job": d.last_job_id, "chat_cost_usd": round(d.chat_cost_usd(), 5),
            "tools": [{"name": t["name"], "args": t.get("args"), "result": t.get("result")} for t in d.last_tools]}


@app.post("/v1/jobs")
def create_job(body: JobIn, who=Depends(auth)):
    out = submit_build(who["user"], body.spec)
    if "error" in out:
        raise HTTPException(402, out)
    return out


@app.post("/v1/jobs/import")
def import_job(body: ImportIn, who=Depends(auth)):
    out = submit_import(who["user"], body.path, body.spec)
    if "error" in out:
        raise HTTPException(400, out)
    return out


@app.post("/v1/jobs/refinish")
def refinish_job(body: RefinishIn, who=Depends(auth)):
    src = store.job(body.source_job, who["user"])
    if not src or not (src.get("result") or {}).get("dir"):
        raise HTTPException(404, "source job not found or has no output")
    spec = {**src["spec"], **body.overrides}
    return _enqueue(who["user"], Spec.from_dict(spec), "refinish", src["result"]["dir"])


@app.get("/v1/jobs")
def list_jobs(who=Depends(auth)):
    return store.jobs_for(who["user"], limit=50)


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, who=Depends(auth)):
    row = store.job(job_id, who["user"])
    if not row:
        raise HTTPException(404, "unknown job")
    return job_view(row, who["user"])


@app.get("/v1/jobs/{job_id}/files/{name}")
def get_file(job_id: str, name: str, who=Depends(auth)):
    row = store.job(job_id, who["user"])
    r = (row or {}).get("result") or {}
    d = r.get("delivery_dir")
    if not d or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(404, "no such file")
    path = os.path.join(d, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "no such file")
    return FileResponse(path, media_type=mimetypes.guess_type(name)[0] or "application/octet-stream", filename=name)


@app.get("/v1/wallet")
def get_wallet(who=Depends(auth)):
    return {"user": who["user"], "balance": wallet.balance(who["user"]), "enforced": config.ENFORCE_CREDITS,
            "history": [{"ts": t, "kind": k, "credits": c, "usd": u, "note": n} for t, k, c, u, n in wallet.history(who["user"])]}


@app.post("/v1/admin/credits")
def add_credits(body: CreditsIn, who=Depends(admin)):
    return {"user": body.user, "balance": wallet.add(body.user, body.credits, body.note)}


@app.get("/v1/estimate")
def estimate(request: Request, who=Depends(auth)):
    spec = Spec.from_dict(dict(request.query_params))
    est = pricing.estimate(spec)
    return {"brief": spec.to_dict(), "credits": est["credits"], "usd": est["usd"], "steps": [s for s, _ in est["steps"]]}


@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True, "blender": os.path.exists(config.BLENDER_BIN), "local_mode": not store.has_keys()})

# Driving Master Smith from a script or an agent

Everything the chat does is plain HTTP on the Python service (default `http://localhost:8080`). The OpenAPI schema is
served at `/docs` and `/openapi.json`. This page is the short version with `curl` recipes.

## Authentication

Put any string you like in `.env`:

```
MASTERSMITH_API_KEY=ms_dev_change_me
```

and send it as `Authorization: Bearer ms_dev_change_me` or `X-API-Key: ms_dev_change_me`. It acts as the admin user
`agent` (rename with `MASTERSMITH_API_USER`). Keys made with `python -m mastersmith keys create <user>` keep working
beside it. With no key configured anywhere, every request is the local admin user and no header is needed.

```bash
export MS=http://localhost:8080
export H="Authorization: Bearer ms_dev_change_me"
curl -s $MS/healthz                       # {"ok":true,"blender":true,"local_mode":false,"worker":true}
curl -s -H "$H" $MS/v1/me                 # who you are, spend, provider balances, recent jobs
curl -s -H "$H" $MS/v1/config             # effective models, vendors, paths, flags; which keys are set (never values)
curl -s -H "$H" $MS/v1/providers          # what the fal and OpenRouter accounts have left
```

## Test a brief without spending

```bash
curl -s -H "$H" -H "Content-Type: application/json" "$MS/v1/jobs?dry_run=1" -d '{
  "spec": {"name": "AmmoCrate", "category": "prop", "size_m": 1.0, "engine": "unreal",
           "description": "weathered oak military ammunition crate with rope handles and black stencils"}
}'
```

Returns the resolved brief (defaults filled in), the worst-case estimate with each priced step, and the provider
balances. Nothing is queued. `GET /v1/estimate?name=..&category=..&description=..` does the same from query
parameters.

## Build

```bash
JOB=$(curl -s -H "$H" -H "Content-Type: application/json" $MS/v1/jobs -d '{"spec": {...}}' | jq -r .job_id)
```

The answer is `{"job_id", "status": "queued", "kind", "estimate_credits"}`, or HTTP 402 with `error` when a provider
balance (or, on a shared instance, the user's credits) cannot cover the worst case.

Bring in a model you already have: upload it, then queue an import.

```bash
P=$(curl -s -H "$H" -F "file=@my_rifle.glb" $MS/v1/uploads | jq -r .path)
curl -s -H "$H" -H "Content-Type: application/json" $MS/v1/jobs/import -d "{\"path\": \"$P\", \"spec\": {\"name\": \"Rifle\", \"category\": \"weapon\", \"size_m\": 1.2, \"glass\": true}}"
```

Re-finish an earlier job's mesh with a changed brief (no new mesh is bought):

```bash
curl -s -H "$H" -H "Content-Type: application/json" $MS/v1/jobs/refinish -d "{\"source_job\": \"$JOB\", \"overrides\": {\"tri_budget\": 80000, \"rig\": true}}"
```

## Watch and debug

```bash
curl -s -H "$H" $MS/v1/jobs/$JOB                  # status, log tail (40 lines), summary, file URLs
curl -s -H "$H" "$MS/v1/jobs/$JOB/log?tail=0"     # the whole log as text (tail=N for the last N lines)
curl -s -H "$H" $MS/v1/jobs/$JOB/debug            # job.json, work-dir listing, Blender log tails, bill by stage
curl -s -H "$H" $MS/v1/jobs/$JOB/work/probe_iso.png -o probe_iso.png      # any work file: probes, masks, args, logs
curl -s -H "$H" $MS/v1/jobs/$JOB/files/SM_AmmoCrate.glb -o SM_AmmoCrate.glb # any delivered file
```

Statuses: `queued` → `running` → `done` | `failed` | `refused`. A failed job's `error` names the stage; the
`debug` answer carries the Blender `prepare.log` / `finish.log` tails that explain it. Jobs run one at a time.

Delivered files follow the engine conventions: `SM_<Name>.fbx/.glb` (+ `_LOD1`, `_LOD2` FBX), `T_<Name>_BC/N/ORM.png`,
`SK_<Name>` and `A_<Name>_*` when rigged, `preview_*.png`, `README.txt`, `<Name>.zip`, `job.json` in the job dir.

## Chat, the way the web app does it

```bash
curl -s -H "$H" -H "Content-Type: application/json" $MS/v1/chat -d '{"session_id": "t1", "message": "a matte black Glock 17, 0.2 m, Unreal"}'
curl -s -H "$H" -H "Content-Type: application/json" $MS/v1/chat -d '{"session_id": "t1", "message": "go"}'
curl -s -H "$H" $MS/v1/sessions/t1        # the director transcript, brief, last tool calls, chat cost
curl -s -X DELETE -H "$H" $MS/v1/sessions/t1
```

Each `/v1/chat` answer carries `reply`, `brief`, `last_job`, `tools` (the director's calls this turn, with results),
`providers` and `chat_cost_usd`. Attach an uploaded picture or model with
`"attachments": [{"path": "<from /v1/uploads>", "name": "x.png", "kind": "image"}]`.

## Running it for tests

- `MASTERSMITH_DATA=/tmp/ms-test python -m mastersmith serve --port 8081` keeps a test instance's builds, uploads and
  ledger apart from your real ones.
- `MASTERSMITH_NO_WORKER=1` on the service means jobs queue but never run: handy for testing the API surface with no
  Blender and no spend. Run `python -m mastersmith worker` when you want them to go.
- `tests/test_api.py` shows the FastAPI test client against a temporary data directory with a fixed key.
- A build reaches fal and OpenRouter and spends real money; `?dry_run=1` does not.

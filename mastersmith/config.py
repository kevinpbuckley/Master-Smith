"""Environment, paths and model routing. Keys come from <repo>/.env (FAL_KEY, OPENROUTER_API_KEY)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "mastersmith" / "skills"
BLENDER_SCRIPT = ROOT / "mastersmith" / "blender" / "finish.py"


def load_env(path=None):
    """KEY=VALUE lines into os.environ; variables already set win. Never prints values."""
    path = Path(path or ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

# Everything the service writes lives under one directory: builds (out/), uploads and the SQLite ledger. The Docker
# image points MASTERSMITH_DATA at a volume; locally it is the repository.
DATA_DIR = Path(os.environ.get("MASTERSMITH_DATA") or ROOT).resolve()
OUT_DIR = DATA_DIR / "out"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "mastersmith.db"

BLENDER_BIN = os.environ.get("BLENDER_BIN", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")

# --- LLMs (OpenRouter ids). The director runs the chat and decides; it is cheap on purpose.
DIRECTOR_MODEL = os.environ.get("MASTERSMITH_DIRECTOR_MODEL", "google/gemini-3.8-flash")
VISION_MODEL = os.environ.get("MASTERSMITH_VISION_MODEL", "google/gemini-3.8-flash")
PREMIUM_MODEL = os.environ.get("MASTERSMITH_PREMIUM_MODEL", "anthropic/claude-sonnet-5")

# --- fal endpoints by role. One vendor per role; the 2026-09-16 bake-off picked these.
# --- pictures: OpenRouter's image API (POST /api/v1/images) since 2026-09-19 (ported from the openrouter-only branch):
# the same Gemini image models as fal's nano-banana at about 7 cents a picture, with edits from reference pictures and
# the cost reported per call. Ids in pricing.IMAGE_PRICES; every one has an MASTERSMITH_* override.
CONCEPT_MODEL = os.environ.get("MASTERSMITH_CONCEPT_MODEL", "google/gemini-3.1-flash-image")        # text -> clean product shot
CONCEPT_MODEL_PREMIUM = os.environ.get("MASTERSMITH_CONCEPT_PREMIUM", "google/gemini-3-pro-image")
# Hard-surface categories get a stronger picture model: the seed reproduces every 2D error as geometry, and
# the cheap model hallucinates extra fine parts on weapons and vehicles (issue #8). Set MASTERSMITH_CONCEPT_HARD to override.
CONCEPT_MODEL_HARD = os.environ.get("MASTERSMITH_CONCEPT_HARD", "google/gemini-3-pro-image")
IMAGE_RESOLUTION = os.environ.get("MASTERSMITH_IMAGE_RESOLUTION", "1K")
# The hybrid repaint of the seed: "meshy" = Meshy retexture on fal ($0.30); "pictures" = the picture model repaints the
# seed's own orthographic renders in the reference's look and Blender projects and bakes them (about $0.40 of pictures,
# ported from the openrouter-only branch). MASTERSMITH_REPAINT overrides; Spec.repaint per build.
REPAINT_DEFAULT = os.environ.get("MASTERSMITH_REPAINT", "meshy").strip().lower() or "meshy"
STAMP_MARKINGS = os.environ.get("MASTERSMITH_STAMP_MARKINGS", "0") == "1"   # exact lettering stamped from a markings read of the reference
HARD_SURFACE_CATEGORIES = ("weapon", "vehicle", "aircraft", "helicopter")
# Alternative seed vendors for the hard-surface comparison of issue #6; MASTERSMITH_SEED_MODEL overrides the default.
SEED_MODEL_ALTERNATIVES = {"hitem3d": "fal-ai/hitem3d/image-to-3d", "meshy7": "fal-ai/meshy/v7/image-to-3d",
                           "hitem3d3": "hitem3d/hi3d/v3.0/image-to-3d"}   # issue #6: the 2048-voxel model, on fal since 2026-09
# Multiview alternatives: these take the SAME checked view set as Tripo multiview. Meshy v7 multi-image asks only for
# "1 to 4 images of the same object from different angles" - no fixed [front, left, back, right] order (issue #6).
SEED_MULTIVIEW_ALTERNATIVES = {"meshy7mv": "fal-ai/meshy/v7/multi-image-to-3d"}
# Hybrid seed (2026-09-18): Meshy v7 geometry (sharper, ~$0.035) then Meshy retexture on the mesh's own UVs (~$0.30) for
# a clean albedo instead of Meshy's speckled one. Categories listed here default to it; MASTERSMITH_HYBRID=0|1 overrides.
_hyb_env = os.environ.get("MASTERSMITH_HYBRID", "").strip()
HYBRID_DEFAULT = None if _hyb_env not in ("0", "1") else _hyb_env == "1"
# Off by default (opt in with Spec.hybrid or MASTERSMITH_HYBRID=1). Local pairs favoured it on ground vehicles and the sword
# (clean albedo, sharper edges), but production wave 22 (2026-09-18) showed the reference repaint washing colours toward
# light silver (M4A1, Glock, a grey F-150 for a dark blue truck), painting windows white, and Meshy melting rotor hubs
# and thin airframes. Until the repaint holds the reference colours, Tripo stays the default everywhere.
HYBRID_CATEGORIES = ()
# Which geometry a hybrid build seeds with: "meshy7mv" (the original hybrid) or "tripo" (Tripo's mesh, repainted). Tripo
# geometry with the picture repaint is the production setting since 2026-09-19 (Meshy melted rotor hubs and airframes).
HYBRID_SEED = os.environ.get("MASTERSMITH_HYBRID_SEED", "meshy7mv").strip().lower() or "meshy7mv"
# Tripo quad topology (+$0.05, answers FBX): on the Glock photo it kept the slide text legible and scored the best edge
# energy of four vendors (issue #6, 2026-09-17). Default for hard-surface categories; MASTERSMITH_SEED_QUAD=0/1 forces it.
_quad_env = os.environ.get("MASTERSMITH_SEED_QUAD", "")
SEED_QUAD = _quad_env == "1" if _quad_env in ("0", "1") else None   # None -> by category
EDIT_MODEL = os.environ.get("MASTERSMITH_EDIT_MODEL", "google/gemini-3.1-flash-image")   # photo -> clean profile / other view
CUTOUT_MODEL = "fal-ai/birefnet/v2"             # background removal, $0.003
SEED_MODEL = "tripo3d/h3.1/image-to-3d"         # full PBR, thin parts survive
RETEXTURE_MODEL = "fal-ai/meshy/v5/retexture"   # repaint an existing mesh on its own UVs, $0.30
SEED_MULTIVIEW_MODEL = "tripo3d/h3.1/multiview-to-3d"
SEED_ALT_MODEL = "fal-ai/hyper3d/rodin/v2"      # several references at once; refuses military subjects

# --- spend. You run this against your own fal and OpenRouter keys, so the ledger only keeps score: one credit is one
# cent of provider cost and a build is never refused for lack of credits unless MASTERSMITH_ENFORCE_CREDITS=1 (a shared
# instance where each user is topped up by an admin). MASTERSMITH_MARKUP scales the charge for that case.
CREDIT_USD = 0.01                                # one credit is one cent
MARKUP = float(os.environ.get("MASTERSMITH_MARKUP", "1.0"))   # charge = provider cost x markup
ENFORCE_CREDITS = os.environ.get("MASTERSMITH_ENFORCE_CREDITS", "0") == "1"


def credits_for_usd(usd):
    """Provider cost -> credits charged (rounded up so we never undercharge a cent)."""
    import math
    return int(math.ceil(usd * MARKUP / CREDIT_USD))

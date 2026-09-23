"""What each paid call costs (USD, per fal's published prices as of 2026-09-16) and the job estimate
shown to the user before anything is spent. THIS TABLE IS THE BILL: an endpoint missing here is refused,
not guessed."""
from . import config

FAL_PRICES = {
    "fal-ai/patina": 0.12,                       # $0.01 + $0.01 per megapixel per map; 5 maps at 2K ~ $0.21 (issue #7)
    "hitem3d/hi3d/v3.0/image-to-3d": 2.10,       # fal: $0.02/credit, 2048quality geometry + texture 10 + pbr 5 = $2.10 (master $9.10)
    "fal-ai/hitem3d/image-to-3d": 0.50,          # CALIBRATE: fal shows no fixed price; Hitem3D 1536pro list price (issue #6)
    "fal-ai/meshy/v7/image-to-3d": 0.05,         # inferred from wave 17's measured spend (2026-09-18): the whole wave
                                                 # came in $2.63 UNDER the table with five of these rows at 0.40; the
                                                 # multi-image sibling measured $0.035, so hold both at 0.05
    "fal-ai/meshy/v7/multi-image-to-3d": 0.05,   # MEASURED 2026-09-18 via fal's balance endpoint: $0.034 and $0.037
                                                 # on two 4-view 300k-quad PBR runs. Held at 0.05 as the reservation.
    "fal-ai/birefnet/v2": 0.003,
    "tripo3d/h3.1/image-to-3d": 0.30,         # standard; +0.10 HD textures, +0.20 detailed geometry, +0.05 quad
    "tripo3d/h3.1/multiview-to-3d": 0.30,
    "fal-ai/hyper3d/rodin/v2": 0.40,
    "fal-ai/meshy/v5/retexture": 0.30,
    "fal-ai/meshy/v5/remesh": 0.20,
    "fal-ai/sam-3/image": 0.005,                 # text-prompted segmentation masks (glass, wheels)
    "fal-ai/hunyuan-3d/v3.1/part": 0.45,         # split a fused mesh (FBX, <=30k faces) into parts
    "fal-ai/meshy/rigging": 0.20,                # humanoid auto-rig from a GLB; +0.12 with enable_animation
    "fal-ai/meshy/rigging/multi-animation": 0.56,
    "tripo3d/tripo/segment": 0.20,               # semantic part split of a GLB (CALIBRATE against the fal dashboard)
}


# Worst-case USD for ONE picture from OpenRouter's image API (per-image output token prices as of 2026-09-18, 1K
# resolution, rounded up); the real usage.cost is what gets billed.
IMAGE_PRICES = {
    "google/gemini-3.1-flash-image": 0.08,
    "google/gemini-3.1-flash-image-preview": 0.08,
    "google/gemini-3.1-flash-lite-image": 0.04,
    "google/gemini-2.5-flash-image": 0.04,
    "google/gemini-3-pro-image": 0.16,
    "google/gemini-3-pro-image-preview": 0.16,
    "openai/gpt-5.4-image-2": 0.10,
    "openai/gpt-5-image": 0.12,
    "openai/gpt-5-image-mini": 0.03,
}
REPAINT_PICTURES = 5          # front / left / back / right / top renders repainted by the picture model


class Unpriced(Exception):
    pass


def image_price(model):
    if model not in IMAGE_PRICES:
        raise Unpriced("no price for picture model %s; add it to pricing.IMAGE_PRICES before calling it" % model)
    return IMAGE_PRICES[model]


def concept_model(spec):
    model = config.CONCEPT_MODEL_PREMIUM if spec.premium else config.CONCEPT_MODEL
    if spec.category in config.HARD_SURFACE_CATEGORIES and config.CONCEPT_MODEL_HARD:
        model = config.CONCEPT_MODEL_HARD
    return model


def repaint_mode(spec):
    m = (getattr(spec, "repaint", None) or config.REPAINT_DEFAULT or "meshy").lower()
    return m if m in ("meshy", "pictures") else "meshy"


def price(model, payload=None):
    if model not in FAL_PRICES:
        raise Unpriced("no price for %s; add it to mastersmith/pricing.py before calling it" % model)
    usd = FAL_PRICES[model]
    payload = payload or {}
    if model.startswith("tripo3d/"):
        if payload.get("texture_quality") == "detailed":
            usd += 0.10
        if payload.get("geometry_quality") == "detailed":
            usd += 0.20
        if payload.get("quad"):
            usd += 0.05                             # quad topology (default for hard-surface categories)
    return round(usd, 4)


# A generous per-call allowance for the director/vision LLM; settled to the real usage.cost after.
LLM_CALL_ALLOWANCE_USD = 0.03


def estimate(spec):
    """Worst-case USD for one build of `spec`, step by step. Reserved up front, settled to actual."""
    steps = []
    seed_payload = {"texture_quality": "detailed", "geometry_quality": "detailed"}
    quad = config.SEED_QUAD if config.SEED_QUAD is not None else spec.category in config.HARD_SURFACE_CATEGORIES
    if quad:
        seed_payload["quad"] = True
    if spec.reference_images:
        steps.append(("clean up your reference picture(s)", image_price(config.EDIT_MODEL)))
    elif spec.research and spec.search_query:
        steps.append(("find a photo of %s on the web and clean it up" % spec.search_query[:40], image_price(config.EDIT_MODEL) + LLM_CALL_ALLOWANCE_USD))
    else:
        steps.append(("concept picture", image_price(concept_model(spec))))
    steps.append(("check the picture (vision)", LLM_CALL_ALLOWANCE_USD))
    steps.append(("second picture attempt if the first fails", image_price(config.EDIT_MODEL) + LLM_CALL_ALLOWANCE_USD))
    if spec.multiview:
        steps.append(("extra views for multiview seeding", 3 * (image_price(config.EDIT_MODEL) + LLM_CALL_ALLOWANCE_USD)))
        steps.append(("3D seed (Tripo H3.1 multiview, detailed)", price(config.SEED_MULTIVIEW_MODEL, seed_payload)))
    else:
        steps.append(("3D seed (Tripo H3.1, detailed)", price(config.SEED_MODEL, seed_payload)))
    steps.append(("which end is the front (vision)", LLM_CALL_ALLOWANCE_USD))
    if spec.category == "environment" and spec.style == "realistic":
        steps.append(("tiling PBR material set from the reference (Patina)", price("fal-ai/patina")))
    if getattr(spec, "retexture", False):
        steps.append(("repaint of the existing mesh (Meshy retexture, original UVs)", price(config.RETEXTURE_MODEL)))
    from .stages.seed import hybrid_wanted
    if hybrid_wanted(spec) and not getattr(spec, "retexture", False):
        if repaint_mode(spec) == "pictures":
            steps.append(("hybrid repaint of the seed (its renders repainted by the picture model, baked in Blender)",
                          REPAINT_PICTURES * image_price(config.EDIT_MODEL) + LLM_CALL_ALLOWANCE_USD))
        else:
            steps.append(("hybrid repaint of the seed (Meshy retexture, original UVs)", price(config.RETEXTURE_MODEL)))
    if spec.category in config.HARD_SURFACE_CATEGORIES and (spec.premium or spec.tri_budget >= 150000):
        steps.append(("separately seeded parts (up to 2: picture + seed each)", 2 * (image_price(config.EDIT_MODEL) + LLM_CALL_ALLOWANCE_USD
                      + price(config.SEED_MODEL, {"geometry_quality": "detailed", "texture_quality": "detailed"}))))
    if getattr(spec, "cockpit", False):
        steps.append(("cockpit as a second model: picture + seed", 2 * image_price(config.CONCEPT_MODEL) + LLM_CALL_ALLOWANCE_USD
                      + price(config.SEED_MODEL, {"geometry_quality": "detailed", "texture_quality": "detailed"})))
    if spec.glass:
        steps.append(("glass masks, 5 views (SAM 3)", 5 * price("fal-ai/sam-3/image")))
    if spec.rig and spec.category == "vehicle":
        steps.append(("wheel masks, 3 views (SAM 3)", 3 * price("fal-ai/sam-3/image")))
    if spec.rig and spec.category == "vehicle":
        steps.append(("part split for wheel bones (Hunyuan)", price("fal-ai/hunyuan-3d/v3.1/part")))
    if spec.rig and spec.category == "character":
        steps.append(("humanoid auto-rig with walk/run (Meshy)", price("fal-ai/meshy/rigging")))
    steps.append(("Blender finish: decimate, orient, scale, LODs, collision, maps, FBX/GLB", 0.0))
    steps.append(("review the result against the picture (vision)", LLM_CALL_ALLOWANCE_USD))
    steps.append(("director chat overhead", 2 * LLM_CALL_ALLOWANCE_USD))
    total = round(sum(u for _, u in steps), 4)
    return {"steps": steps, "usd": total, "credits": config.credits_for_usd(total)}

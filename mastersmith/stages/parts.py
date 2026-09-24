"""Issue #5, first version: separately seeded parts fitted into the body. Image-to-3D melts small attached parts
(magazine, optic, muzzle device) when it builds the whole object at once; the same part alone is a simple shape
the vendor gets right. The picture editor cuts the part out of the reference on white, Tripo seeds it, and the
finish pass fits the seed into the bounding box of the part's faces on the body (the cockpit path), shrinking the
old faces underneath. Gated to premium / hero builds by the caller."""
import os

from .. import config, pricing
from ..fal import first_url
from ..llm import extract_json

CHECK = """Is this a clear picture of ONE {part}, whole, isolated on a plain white background, with no other part of the
object around it? Answer JSON only: {{"ok": true/false, "score": 1-10, "fixes": "one sentence"}}"""


def make_part_seed(job, spec, part, reference_path):
    """part: {"phrase": "...", "name": "Magazine"} -> {"glb", "picture"} or None."""
    phrase = part["phrase"]
    fixes = ""
    picture = None
    for attempt in range(2):
        prompt = ("From this picture, show ONLY %s, whole and complete, exactly as it looks here (same colours, same "
                  "materials, same markings), isolated on a plain pure white background, nothing else in frame, sharp, "
                  "product photograph. %s" % (phrase, fixes)).strip()
        path = os.path.join(job.dir, "part_%s_ref_%d.png" % (part.get("name", "Part"), attempt))
        job.images.generate(prompt, path, model=pricing.edit_model(spec), references=[reference_path], aspect_ratio="4:3")
        j = extract_json(job.llm.vision(CHECK.format(part=phrase), [path])) or {}
        job.log("  part %s picture: score %s" % (part.get("name"), j.get("score")))
        if j.get("ok") and int(j.get("score", 0) or 0) >= 6:
            picture = path
            break
        fixes = str(j.get("fixes") or "")
        picture = picture or path
    url = job.fal.upload(picture)
    payload = {"image_url": url, "geometry_quality": "detailed", "texture_quality": "detailed", "pbr": True, "face_limit": 80000}
    if spec.category in config.HARD_SURFACE_CATEGORIES:
        payload["quad"] = True
    out = job.fal.run(config.SEED_MODEL, payload)
    mesh_url = first_url(out, (".glb",)) or first_url(out, (".fbx",))
    if not mesh_url:
        job.log("  part %s: the seed vendor returned no mesh" % part.get("name"))
        return None
    ext = ".fbx" if mesh_url.split("?")[0].lower().endswith(".fbx") else ".glb"
    glb = os.path.join(job.dir, "part_%s_seed%s" % (part.get("name", "Part"), ext))
    job.fal.download(mesh_url, glb)
    job.log("  part %s seed: %.1f MB" % (part.get("name"), os.path.getsize(glb) / 1e6))
    return {"glb": glb, "picture": picture, "name": part.get("name", "Part"), "phrase": phrase}


INTERIOR_WORDS = ("cockpit", "cabin", "interior", "seat", "console", "dashboard", "instrument")


def make_added_part(job, spec, part, reference_path):
    """A part to ADD to the built model: drawn alone on white (from the customer's picture when they gave one, edited out
    of the reference when the part is visible on it, or drawn from the words for an interior), checked, seeded as a
    small mesh. -> {"glb", "picture", "name", "phrase"} or None. The body is not touched here; the finish fits it."""
    phrase, name = part["phrase"], part.get("name", "Part")
    picture, fixes = None, ""
    if part.get("picture") and os.path.exists(part["picture"]):
        picture = part["picture"]
    else:
        interior = part.get("place") == "inside" and any(w in phrase.lower() for w in INTERIOR_WORDS)
        for attempt in range(2):
            path = os.path.join(job.dir, "part_%s_ref_%d.png" % (name, attempt))
            if interior or not reference_path or not os.path.exists(reference_path):
                prompt = ("%s of a %s, as one open-topped module seen from above at a three-quarter angle, complete, "
                          "isolated on a plain pure white background, no roof, no glass, nothing else in frame, "
                          "photorealistic, sharp. %s" % (phrase, (spec.search_query or spec.description[:140]), fixes)).strip()
                job.images.generate(prompt, path, model=pricing.concept_model(spec), aspect_ratio="4:3")
            else:
                prompt = ("Show ONLY %s that belongs on this exact object, whole and complete, matching its colours and "
                          "materials, isolated on a plain pure white background, nothing else in frame, sharp, product "
                          "photograph. %s" % (phrase, fixes)).strip()
                job.images.generate(prompt, path, model=pricing.edit_model(spec), references=[reference_path], aspect_ratio="4:3")
            j = extract_json(job.llm.vision(CHECK.format(part=phrase), [path])) or {}
            job.log("  add %s picture: score %s" % (name, j.get("score")))
            if j.get("ok") and int(j.get("score", 0) or 0) >= 6:
                picture = path
                break
            fixes = str(j.get("fixes") or "")
            picture = picture or path
    url = job.fal.upload(picture)
    payload = {"image_url": url, "geometry_quality": "detailed", "texture_quality": "detailed", "pbr": True, "face_limit": 80000}
    if spec.category in config.HARD_SURFACE_CATEGORIES:
        payload["quad"] = True
    out = job.fal.run(config.SEED_MODEL, payload)
    mesh_url = first_url(out, (".glb",)) or first_url(out, (".fbx",))
    if not mesh_url:
        job.log("  add %s: the seed vendor returned no mesh" % name)
        return None
    ext = ".fbx" if mesh_url.split("?")[0].lower().endswith(".fbx") else ".glb"
    glb = os.path.join(job.dir, "part_%s_seed%s" % (name, ext))
    job.fal.download(mesh_url, glb)
    job.log("  add %s seed: %.1f MB" % (name, os.path.getsize(glb) / 1e6))
    return {"glb": glb, "picture": picture, "name": name, "phrase": phrase}

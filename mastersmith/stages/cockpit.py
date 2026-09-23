"""Stage 3a: a cockpit for a jet or helicopter. The seed vendor never models an interior; behind a
translucent canopy there is only the inside of the shell. So the cockpit is made as a SECOND model - a
picture of the cockpit tub (seat, instrument panel, consoles), seeded like any asset - and the finish
pass fits it under the canopy glass and joins it in."""
import os

from .. import config, pricing
from ..fal import first_url
from ..llm import extract_json

COCKPIT_PROMPT = {
    "aircraft": "the cockpit tub of a {subject}: ejection seat with harness, instrument panel with screens and gauges, "
                "HUD frame, control stick, throttle and side consoles, canopy sill, seen from above at a three-quarter "
                "angle, the whole tub isolated on a plain pure white background, OPEN-TOPPED with no roof, no windscreen, "
                "no canopy glass and no canopy frame of any kind, no airframe around it, photorealistic, sharp",
    "helicopter": "the cockpit interior module of a {subject}: two crew seats one behind the other, instrument panels "
                  "with screens, cyclic and collective controls, pedals, side consoles, seen from above at a three-quarter "
                  "angle, the whole module isolated on a plain pure white background, OPEN-TOPPED with no roof, no "
                  "windscreen, no windows, no canopy glass or frame of any kind, no fuselage around it, photorealistic, sharp",
}

CHECK = """Is this a clear picture of ONE cockpit interior module (seats, instrument panel, consoles) isolated on a plain
background, with no aircraft body around it AND no windscreen, canopy glass, canopy frame or roof over it (it must be open
on top)? A windscreen or canopy means ok=false. Answer JSON only: {"ok": true/false, "score": 1-10, "fixes": "one sentence"}"""


SEAT_WORDS = (("single-seat", "one seat"), ("single seat", "one seat"), ("one-seat", "one seat"), ("tandem", "two seats one behind the other"),
              ("two-seat", "two seats"), ("two seat", "two seats"), ("side-by-side", "two seats side by side"), ("twin-seat", "two seats"))


def seat_phrase(spec):
    d = (spec.description or "").lower()
    for word, phrase in SEAT_WORDS:
        if word in d:
            return phrase
    return "two seats one behind the other" if spec.category == "helicopter" else "one seat"


def make_cockpit(job, spec, reference=None):
    """Returns the cockpit seed GLB path, or None when the picture never came out right. With the aircraft's own
    reference picture the tub is EDITED out of it (this aircraft, canopy removed) so it is tandem for an Apache and
    single for an F-16; the generic text prompt gave every aircraft the same grey box (owner, 2026-09-18)."""
    subject = spec.search_query or spec.description[:120]
    fixes = ""
    picture = None
    seats = seat_phrase(spec)
    for attempt in range(2):
        path = os.path.join(job.dir, "cockpit_ref_%d.png" % attempt)
        edited = False
        if reference and os.path.exists(reference) and not getattr(job, "edit_refused", False):
            try:
                job.images.generate(("Show ONLY the cockpit interior of this exact aircraft, seen from above and slightly behind, "
                                     "with the canopy glass and its frame completely removed: %s, the instrument panels, consoles and "
                                     "controls exactly as this aircraft has them, in its colours. One open-topped tub, no roof, no "
                                     "windscreen, no airframe around it, isolated on a plain pure white background, sharp. %s" % (seats, fixes)).strip(),
                                    path, model=pricing.edit_model(spec), references=[reference], aspect_ratio="4:3")
                edited = True
            except Exception as exc:  # noqa: BLE001 - the text prompt is the fallback
                job.log("  cockpit picture from the reference failed (%s); drawing it from the text" % str(exc)[:120])
        if not edited:
            prompt = COCKPIT_PROMPT.get(spec.category, COCKPIT_PROMPT["aircraft"]).format(subject=subject) + " (%s) " % seats + fixes
            job.images.generate(prompt, path, model=pricing.concept_model(spec), aspect_ratio="4:3")
        j = extract_json(job.llm.vision(CHECK, [path])) or {}
        job.log("  cockpit picture: score %s" % j.get("score"))
        if j.get("ok") and int(j.get("score", 0) or 0) >= 6:
            picture = path
            break
        fixes = str(j.get("fixes") or "")
    if picture is None:
        # issue #12: the picture model keeps drawing a windscreen and the seed vendor turns it into a blob; the finish
        # builds the tub parametrically instead (floor, seats, panel, sticks) - always readable, no vendor call
        job.log("  cockpit picture never came out open-topped; the tub is built parametrically")
        return None
    url = job.fal.upload(picture)
    out = job.fal.run(config.SEED_MODEL, {"image_url": url, "geometry_quality": "detailed", "texture_quality": "detailed",
                                          "pbr": True, "face_limit": 120000})
    glb_url = first_url(out, (".glb",))
    if not glb_url:
        job.log("  cockpit: the seed vendor returned no mesh")
        return None
    glb = os.path.join(job.dir, "cockpit_seed.glb")
    job.fal.download(glb_url, glb)
    job.log("  cockpit seed: %.1f MB" % (os.path.getsize(glb) / 1e6))
    return {"glb": glb, "picture": picture}

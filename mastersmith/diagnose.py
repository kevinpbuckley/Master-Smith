"""A post-mortem for every finished job, written for the director. It reads what the pipeline already knows - the
reviewer's sentences, the reference stage's checks, the seed's view count and the Blender log - and turns it into
findings that each name a remedy the director can act on (a texture fix, a part removal, a vendor switch, another
angle). Why: on the 2026-09-24 M4A1 the cheap director only saw "muddy textures" while the log said a sword family
had swallowed the rifle, the photo's lighting had been projected on, and the seed had one view. Nothing here spends."""
import os
import re

GEOMETRY_WORDS = ("melted", "blobby", "low-poly", "fused", "glitch", "warped", "missing geometry", "deformed", "misshapen", "collapsed")
SPECULAR_WORDS = ("baked", "painted-on", "painted on", "specular", "reflection", "burnt-in", "highlight")
BLUR_WORDS = ("blurry", "muddy", "smudg", "washed", "chalky", "flat")
GLASS_WORDS = ("canopy", "glass", "windshield", "window", "hollow", "milky", "see-through")
EXTRA_WORDS = ("extra ", "floating", "artifact", "artefact", "strap", "sling", "stand", "blob", "fused to", "attached to")


def _read(path, limit=400_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def diagnose(result, work_dir, spec, reference_source=None):
    """[{"finding": str, "remedy": str, "fix": {...}|None}] - fix is the brief change that applies the remedy."""
    out = []
    review = result.get("review") or {}
    issues = [str(i) for i in (review.get("issues") or [])]
    delivery = result.get("delivery") or {}
    log = _read(os.path.join(work_dir, "finish.log")) + "\n" + _read(os.path.join(work_dir, "prepare.log"))
    joined = " ".join(issues).lower()

    # --- how many angles the mesh was made from
    seed = result.get("seed") or {}
    views = (result.get("reference") or {}).get("views") or []
    if seed.get("model") and getattr(spec, "multiview", False) and len(views) <= 1 and not spec.reference_job:
        out.append({"finding": "the mesh was seeded from ONE picture: the extra angle(s) failed their checks or were not drawn, so the "
                               "vendor guessed the cross-section (fused trigger guards, melted rails, second tails come from this)",
                    "remedy": "draw the reference again so the angles pass, or pick a single-view vendor that models hard surfaces "
                              "crisply (Hitem3D v3)",
                    "fix": {"seed_vendor": "hitem3d3"}})

    # --- material families: what the segmenter found (or did not) and any family that swallowed the object
    for m in re.finditer(r"material family (the [^:]+?): no faces found", log):
        out.append({"finding": "the material family '%s' matched nothing on the renders, so those parts kept the vendor's "
                               "roughness and metal" % m.group(1), "remedy": "that family's phrase needs rewording in the skill", "fix": None})
    for m in re.finditer(r"material family (the [^:]+?): (\d+) faces -> [^(]*\((\d+)% of the atlas\)", log):
        share = int(m.group(3))
        if share >= 30:
            out.append({"finding": "the material family '%s' covered %d%% of the atlas: one finish for most of the object" % (m.group(1), share),
                        "remedy": "the families are too coarse for this object; a repaint (retexture) separates materials", "fix": {"retexture": True}})

    # --- a photograph projected onto the mesh
    if "reprojected the reference onto the mesh" in log and reference_source in ("research", "customer"):
        out.append({"finding": "the reference photograph was projected onto the mesh, so its studio lighting is in the base colour",
                    "remedy": "re-finish: photographs are no longer reprojected, and kill_highlights removes the painted specular",
                    "fix": {"texture_fixes": ["kill_highlights", "delight"]}})

    # --- reviewer sentences -> remedies
    if any(w in joined for w in SPECULAR_WORDS):
        out.append({"finding": "reviewer: painted lighting / specular in the texture", "remedy": "free re-finish with kill_highlights + delight",
                    "fix": {"texture_fixes": ["kill_highlights", "delight"]}})
    elif any(w in joined for w in BLUR_WORDS):
        out.append({"finding": "reviewer: blurry / muddy / flat texture", "remedy": "free re-finish with delight; if still flat, a repaint",
                    "fix": {"texture_fixes": ["delight"]}})
    if any(w in joined for w in GEOMETRY_WORDS):
        out.append({"finding": "reviewer: melted or fused geometry", "remedy": "a crisper seed: Hitem3D v3 (2048) from the same approved "
                               "pictures, or more angles for Tripo", "fix": {"seed_vendor": "hitem3d3"}})
    if any(w in joined for w in GLASS_WORDS) and getattr(spec, "glass", False):
        out.append({"finding": "reviewer: the glass / canopy reads wrong", "remedy": "free re-finish: clear_glass_highlights, or dark_canopy "
                               "when the interior is hollow", "fix": {"texture_fixes": ["clear_glass_highlights", "dark_canopy"]}})
    if any(w in joined for w in EXTRA_WORDS):
        out.append({"finding": "reviewer: an extra or fused part", "remedy": "remove_parts with a phrase for that part; the red preview shows "
                               "what would go before anything is deleted", "fix": {"remove_parts": ["<phrase for the part>"]}})

    # --- cockpit tub, removed parts, highlight passes: what the finish did, so the director can say so
    m = re.search(r"cockpit fitted under the canopy \((\d+) faces, scale ([\d.]+)\)", log)
    if m and float(m.group(2)) > 1.6:
        out.append({"finding": "the cockpit tub was scaled x%s to fit and part of it may stick out" % m.group(2),
                    "remedy": "build without the tub (cockpit=false) and use dark_canopy", "fix": {"cockpit": False, "texture_fixes": ["dark_canopy"]}})
    for key, label in (("removed_parts", "parts removed"), ("glass_reflections_cleared", "glass highlights cleared")):
        if delivery.get(key):
            out.append({"finding": "%s: %s" % (label, delivery[key]), "remedy": "done in this job", "fix": None})
    m = re.search(r"kill highlights: (\d+) painted-specular texels \(([\d.]+)%", log)
    if m:
        out.append({"finding": "kill_highlights replaced %s texels (%s%% of the atlas)" % (m.group(1), m.group(2)), "remedy": "done in this job", "fix": None})

    # --- the score itself
    score = review.get("score")
    if isinstance(score, (int, float)):
        if score >= 7:
            out.insert(0, {"finding": "reviewer %s/10: ship" % score, "remedy": "nothing needed", "fix": None})
        elif score >= 5:
            out.insert(0, {"finding": "reviewer %s/10: usable with the notes above" % score, "remedy": "apply the free fixes first", "fix": None})
        else:
            out.insert(0, {"finding": "reviewer %s/10: not usable as is" % score, "remedy": "work through the findings below, cheapest first", "fix": None})
    return out

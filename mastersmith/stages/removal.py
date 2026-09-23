"""A removal is previewed before it is done. The masks that would drive the deletion are drawn in red on the probe
renders of the job the mesh came from - three SAM calls a phrase, no Blender pass - and the customer confirms.
Why: the M4A1's "extra cylinder attached to the magazine" masked the whole magazine and the finish deleted it
(9,066 faces, reviewer 4/10, 2026-09-23). A segmenter's idea of a part is not the customer's until they have seen it."""
import os

import numpy as np
from PIL import Image

from .probe import _sam, _sam_by_box, part_variants

PREVIEW_VIEWS = ("iso", "negy", "posy", "posx")      # three-quarter first, then the sides, then the nose
MAX_VIEWS = 3


def overlay(probe_path, mask_paths, out_path, colour=(255, 40, 40), strength=0.65):
    """The union of the masks tinted `colour` over the render. Returns the share of the picture it covers."""
    base = np.asarray(Image.open(probe_path).convert("RGB")).astype(np.float32)
    h, w = base.shape[:2]
    union = np.zeros((h, w), bool)
    for mp in mask_paths:
        m = Image.open(mp).convert("L")
        if m.size != (w, h):
            m = m.resize((w, h))
        union |= np.asarray(m) > 127
    tint = np.array(colour, np.float32)
    base[union] = base[union] * (1 - strength) + tint * strength
    Image.fromarray(base.clip(0, 255).astype(np.uint8)).save(out_path)
    return float(union.mean())


def preview_removal(job, source_dir, phrases):
    """[{"label", "path", "coverage"}]: for each phrase, up to MAX_VIEWS probe renders of `source_dir` with the
    faces that would be deleted in red. A view where nothing is found is skipped."""
    out = []
    work = os.path.join(source_dir, "work")
    for i, phrase in enumerate(list(phrases)[:4]):
        variants = part_variants(job.spec, phrase)
        shown = 0
        for v in PREVIEW_VIEWS:
            if shown >= MAX_VIEWS:
                break
            probe = os.path.join(work, "probe_%s.png" % v)
            if not os.path.exists(probe):
                continue
            kept = []
            for variant in variants:
                kept = _sam(job, probe, variant, min_score=0.3)
                if kept:
                    break
            if not kept:
                kept = _sam_by_box(job, probe, variants[0])
            if not kept:
                job.log("  remove preview: %s not found on the %s view" % (phrase, v))
                continue
            path = os.path.join(job.dir, "remove_preview_%d_%s.png" % (i, v))
            cov = overlay(probe, [os.path.join(job.work_dir, k["file"]) for k in kept], path)
            out.append({"label": "%s - %s view, red = deleted (%.0f%% of the picture)" % (phrase, v, cov * 100),
                        "path": path, "coverage": cov, "phrase": phrase, "view": v})
            shown += 1
    return out

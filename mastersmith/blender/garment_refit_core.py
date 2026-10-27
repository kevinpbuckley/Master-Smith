"""The numeric core of `garment_refit.py`'s stages, pure numpy (no bpy, no mathutils) so the tests can load it without
Blender. Extracted 2026-10-07 from the day's separate polish scripts (p4_reseat.py, p4_shrink.py, p5_collar.py,
p5_lift.py, p5_weights.py, MissionCommander and DrHart): the maths that mapped a garment vertex's gap to the body,
held the collar still, told a blended label band from a clean one, and matched an old mesh's vertices to a rebuilt
one with a different vertex count.

Every function takes and returns plain numpy arrays or dicts; `garment_refit.py` wires them to BVH ray casts and
Blender mesh data."""
import numpy as np

# -------------------------------------------------------------------------------------------------- shrink (p4_shrink)


def shrink_pull(gap, k, floor):
    """The displacement (metres, along the inward gap direction) that maps a vertex's signed gap-to-body from `gap`
    toward `floor + k * (gap - floor)` for any gap above `floor`, and leaves a gap at or under `floor` alone. k in
    [0, 1): the share of the gap above the floor that is KEPT (0.7 keeps 70%, pulls in 30%). Linear and
    non-decreasing in `gap`, so two vertices that started at different gaps keep their order after the pull (a tunic's
    skirt stays over the trousers, a belt stays proud of the shirt): gap_after = gap - shrink_pull(...) is
    monotonic non-decreasing in gap for any k in [0, 1] and any floor."""
    gap = np.asarray(gap, dtype=float)
    return np.where(gap > floor, (1.0 - k) * (gap - floor), 0.0)


def gap_after_pull(gap, k, floor):
    """The gap a vertex ends at after `shrink_pull`: `floor + k * (gap - floor)` above the floor, `gap` at or below
    it. Only here for callers that want the resulting gap rather than the displacement."""
    return np.asarray(gap, dtype=float) - shrink_pull(gap, k, floor)


# ------------------------------------------------------------------------------------- held bands (p4_shrink, p5_collar, p5_lift)


def smoothstep_hold(dist, band):
    """1.0 at `dist` 0 (on the collar, or any other held feature), 0.0 at `dist` >= `band`, smoothstep (3t^2 - 2t^3)
    in between: a push or a pull fades out smoothly from a held edge so no crease shows at the join (a LINEAR fade
    from the collar to the shoulder board creased there, MissionCommander p4 run 1, 2026-10-07). `dist` is the graph
    (mesh) distance in metres from the nearest held vertex; `band` the width of the fade, also metres."""
    dist = np.asarray(dist, dtype=float)
    t = np.clip(1.0 - dist / band, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# -------------------------------------------------------------------------------------------- bone families (p5_weights)

_ARM_PREFIXES = ("upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky")
_LEG_PREFIXES = ("thigh", "calf", "foot", "ball")


def bone_family(bone_name):
    """'upperarm_l' -> 'arm_l', 'thigh_r' -> 'leg_r', anything else (spine, neck, clavicle, pelvis, head) -> 'torso'.
    The side suffix only matters to keep a left sleeve's weight from blending with a right one; torso has none."""
    b = bone_name.lower()
    side = "_l" if b.endswith("_l") or "_l_" in b else ("_r" if b.endswith("_r") or "_r_" in b else "")
    if b.startswith(_ARM_PREFIXES):
        return "arm" + side
    if b.startswith(_LEG_PREFIXES):
        return "leg" + side
    return "torso"


def family_shares(weights):
    """{bone: weight} -> {family: summed weight}, families from `bone_family`."""
    shares = {}
    for bone, w in weights.items():
        f = bone_family(bone)
        shares[f] = shares.get(f, 0.0) + w
    return shares


def dominant_family(weights):
    shares = family_shares(weights)
    return max(shares, key=shares.get) if shares else "torso"


def is_mixed_band(weights, share=0.12):
    """True where a SECOND bone family (after the dominant one) still holds more than `share` of the total weight:
    a label band the fit blended across a seam (an armpit, a shoulder cap, a hip) rather than a vertex cleanly on one
    side. Exact body weights taken there gave a side panel the upper arm's weights and a 12x armpit stretch in an arm
    raise (GARMENTS.md v5/v6, run 1, 2026-10-06/07); such vertices keep the fit's own smoothed weights instead."""
    shares = family_shares(weights)
    vals = sorted(shares.values(), reverse=True)
    total = sum(vals) or 1.0
    return len(vals) > 1 and vals[1] > share * total


# --------------------------------------------------------------------------------------------- UV matching (p4_reseat)


def match_by_uv(old_uv, new_uv, old_pos, new_pos, candidates=4):
    """Map each OLD vertex to the NEW vertex at (nearly) the same UV: a rebuilt body FBX can come back with a vertex
    count that differs by one or two (MissionCommander's r5 export, 32335 vs 32334) while the UVs - the MetaHuman
    body's own, fixed - stay the same. For each old UV, the `candidates` nearest new UVs are ranked by UV distance
    first and, among near-ties, by how close the candidate's 3D position is to the old vertex's (breaks a tie between
    two new vertices that share a UV seam). Returns (idx, worst_uv_distance): `new_pos[idx]` lines up with `old_pos`,
    and a new vertex that no old UV claims (the extra one) is simply never chosen."""
    old_uv = np.asarray(old_uv, dtype=float)
    new_uv = np.asarray(new_uv, dtype=float)
    old_pos = np.asarray(old_pos, dtype=float)
    new_pos = np.asarray(new_pos, dtype=float)
    idx = np.zeros(len(old_uv), dtype=int)
    worst_uv = 0.0
    for i, uv in enumerate(old_uv):
        d = np.linalg.norm(new_uv - uv, axis=1)
        order = np.argsort(d)[:candidates]
        best = min(order, key=lambda j: (round(float(d[j]), 6), float(np.linalg.norm(new_pos[j] - old_pos[i]))))
        idx[i] = best
        worst_uv = max(worst_uv, float(d[best]))
    return idx, worst_uv


# -------------------------------------------------------------------------------------------- mesh smoothing (shared)


def laplacian_smooth(values, edges, n, iterations, keep_mask=None):
    """`values` (n, k) averaged with its edge-neighbours' mean, half and half, `iterations` times (p4_shrink's and
    p5_collar's displacement smoothing). `edges` is an (m, 2) int array of vertex-index pairs. `keep_mask` (n,) bool,
    when given, is re-pinned to its ORIGINAL value after every iteration (a collar or a boot that must not move while
    the rest of the cloth is relaxed)."""
    values = np.array(values, dtype=float, copy=True)
    pinned = values.copy()
    if len(edges) == 0 or iterations <= 0:
        return values
    edges = np.asarray(edges, dtype=int)
    ni = np.concatenate([edges[:, 0], edges[:, 1]])
    nj = np.concatenate([edges[:, 1], edges[:, 0]])
    deg = np.maximum(np.bincount(ni, minlength=n), 1).astype(float)
    for _ in range(iterations):
        acc = np.zeros_like(values)
        np.add.at(acc, ni, values[nj])
        values = 0.5 * values + 0.5 * acc / deg[(slice(None),) + (None,) * (values.ndim - 1)]
        if keep_mask is not None:
            values[keep_mask] = pinned[keep_mask]
    return values

"""The vendor parts' triangle shares (pure python, tested): by surface area with a floor, inside the budget."""


def shares(left, areas, floor=2000, want=None):
    """Each part's triangles: `left` split by area, no part under `floor`, and the total never over `left`. A plain
    max(floor, share) let four small fan and stator discs take 2,000 triangles each and LOD0 ran 4,000 over 120,000
    (cloud test A, 2026-10-22): the parts held at the floor now come out of the others' shares.
    `want[i]` (a part's planned "triangles", 2026-10-23) fixes that part's count and the rest split what is left by
    area: the Mk II's cockpit insert held 9% of the surface and got 10k of 120k, which blurred its dials and HOTAS.
    Wanted counts over the budget are scaled down together so the others keep at least the floor each."""
    n = len(areas)
    if not n:
        return []
    want = list(want or [None] * n)
    fixed = {i: int(want[i]) for i in range(n) if want[i]}
    free = [i for i in range(n) if i not in fixed]
    if fixed:
        room = int(left) - (floor if free else 0) * len(free)
        total_fixed = sum(fixed.values())
        if total_fixed > room > 0:
            fixed = {i: int(v * room / total_fixed) for i, v in fixed.items()}
        rest = int(left) - sum(fixed.values())
        out = shares(max(rest, 0), [areas[i] for i in free], floor) if free else []
        result = [0] * n
        for i, v in fixed.items():
            result[i] = v
        for i, v in zip(free, out):
            result[i] = v
        return result
    floor = min(int(floor), int(left) // n)
    held = set()
    while True:
        free = [i for i in range(n) if i not in held]
        rest = left - floor * len(held)
        total = sum(areas[i] for i in free)
        out = {i: (rest * areas[i] / total if total > 0 else rest / max(len(free), 1)) for i in free}
        low = [i for i in free if out[i] < floor]
        if not low:
            break
        held.update(low)
    return [floor if i in held else int(out[i]) for i in range(n)]

"""The vendor parts' triangle shares (pure python, tested): by surface area with a floor, inside the budget."""


def shares(left, areas, floor=2000):
    """Each part's triangles: `left` split by area, no part under `floor`, and the total never over `left`. A plain
    max(floor, share) let four small fan and stator discs take 2,000 triangles each and LOD0 ran 4,000 over 120,000
    (cloud test A, 2026-10-22): the parts held at the floor now come out of the others' shares."""
    n = len(areas)
    if not n:
        return []
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

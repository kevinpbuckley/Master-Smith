"""The muzzle finder (blender/muzzle.py) on synthetic front depth maps: a bore, a capped pit, a ring round a barrel,
four tubes on one face (2026-10-01: sockets at the box centre, a capped laser muzzle, Muzzle_0..3 by hand)."""
import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("muzzle", Path(__file__).resolve().parents[1] / "mastersmith/blender/muzzle.py")
muzzle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(muzzle)

CELL, LENGTH = 0.001, 0.9            # a 1 mm grid on a 0.9 m rifle


def disc(grid, r, c, radius, value):
    rr, cc = np.mgrid[:grid.shape[0], :grid.shape[1]]
    grid[(rr - r) ** 2 + (cc - c) ** 2 <= radius ** 2] = value


def face(radius=20):
    g = np.full((80, 80), np.inf)                  # nothing in front: the rays leave
    disc(g, 40, 40, radius, 0.0)                   # the muzzle's face, at the front
    return g


def test_an_open_bore_is_found_at_its_centre():
    g = face()
    disc(g, 43, 38, 4, np.inf)                     # a bore the rays run straight down
    found = muzzle.muzzle_openings(g, CELL, LENGTH)
    assert len(found) == 1 and found[0]["open"]
    assert abs(found[0]["row"] - 43) < 0.6 and abs(found[0]["col"] - 38) < 0.6
    assert 0.006 < found[0]["diameter_m"] < 0.010


def test_a_capped_muzzle_is_a_shallow_pit_not_a_bore():
    g = face()
    disc(g, 40, 40, 5, 0.003)                      # 3 mm deep: the shotgun's "closed-looking recessed centre"
    found = muzzle.muzzle_openings(g, CELL, LENGTH)
    assert len(found) == 1 and not found[0]["open"] and found[0]["bore_depth_m"] < 0.004


def test_a_ring_round_a_barrel_is_not_a_muzzle():
    g = face(radius=25)
    disc(g, 40, 40, 12, 0.05)                      # the gap inside a handguard ...
    disc(g, 40, 40, 6, 0.0)                        # ... round the barrel's face
    disc(g, 40, 40, 2, np.inf)                     # the bore
    found = muzzle.muzzle_openings(g, CELL, LENGTH)
    assert len(found) == 1 and found[0]["diameter_m"] < 0.006


def test_four_tubes_on_one_face_and_their_order():
    g = face(radius=30)
    for r, c in ((25, 40), (40, 25), (40, 55), (55, 40)):
        disc(g, r, c, 5, 0.2)                      # four 10 mm tubes, 200 mm deep
    found = muzzle.muzzle_openings(g, CELL, LENGTH)
    assert len(found) == 4 and all(o["open"] for o in found)
    pts = [(0.0, o["col"], 80 - o["row"]) for o in found]          # z grows upwards
    order = muzzle.order_muzzles(pts)
    assert pts[order[0]][2] == max(p[2] for p in pts)             # the top tube is Muzzle_0


def test_loaded_tubes_are_found_by_their_vertices():
    rng = np.random.default_rng(0)
    centres = np.array([[0.0, 0.1], [-0.1, 0.0], [0.1, 0.0], [0.0, -0.1]])        # (y, z): top, sides, bottom
    yz = np.concatenate([c + rng.normal(0, 0.012, (300, 2)) for c in centres])
    got, lab = muzzle.cluster_tubes(yz, 4)
    for c in centres:
        assert np.min(np.linalg.norm(got - c, axis=1)) < 0.01
    assert np.argmax(got[:, 1]) == 0                          # the top tube first


def test_melee_weapons_have_no_muzzle():
    assert muzzle.is_melee("a longsword with a leather grip")
    assert not muzzle.is_melee("a bayonet-mounted rifle with a knife under the barrel")
    assert not muzzle.is_melee("a ship-mounted laser cannon")

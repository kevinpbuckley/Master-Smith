"""Material masks must reach preserved seed depth without moving or rewriting the original plan."""
import importlib.util
from pathlib import Path

import pytest


def test_kept_depth_material_zones_cover_sides_and_keep_asymmetry():
    path = Path(__file__).resolve().parents[1] / "mastersmith/blender/restrained_finish.py"
    spec = importlib.util.spec_from_file_location("restrained_finish", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    zones = [{"box_min": [-1, -0.025, 2], "box_max": [3, 0.025, 4]},
             {"box_min": [-1, 0.0, 2], "box_max": [3, 0.025, 4]}]
    mapped, scale = module.depth_zones(zones, -0.025, 0.025, -0.02, 0.06)
    assert scale == pytest.approx(1.6)
    assert mapped[0]["box_min"] == pytest.approx([-1, -0.02, 2])
    assert mapped[0]["box_max"] == pytest.approx([3, 0.06, 4])
    assert mapped[1]["box_min"][1] == pytest.approx(0.02)
    assert zones[0]["box_min"][1] == -0.025
    assert zones[1]["box_min"][1] == 0.0

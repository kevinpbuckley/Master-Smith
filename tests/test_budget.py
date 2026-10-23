"""The vendor parts' triangle shares stay inside the budget (blender/budget.py, pure python)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("budget", Path(__file__).resolve().parents[1] / "mastersmith/blender/budget.py")
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def test_small_parts_at_the_floor_come_out_of_the_others():
    s = budget.shares(100000, [50.0, 0.01, 0.01, 0.01, 0.01])
    assert s[1:] == [2000] * 4 and sum(s) <= 100000 and s[0] == 92000


def test_plain_area_split_when_no_part_is_small():
    assert budget.shares(10000, [1.0, 1.0]) == [5000, 5000]


def test_floor_shrinks_when_the_budget_is_tiny():
    s = budget.shares(3000, [1.0, 1.0, 1.0])
    assert sum(s) <= 3000 and min(s) >= 1000

"""Fitted glazing must remove pane skins without selecting the cockpit or neighbouring frame."""
import importlib.util
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('fitted_glass', Path(__file__).resolve().parents[1] / 'mastersmith/blender/fitted_glass.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_skin_depth_triangle_interior_and_normal_protect_cockpit_and_frame():
    centres = [[.2,.2,0], [.2,.2,-.02], [.2,.2,-.4], [.8,.8,0], [.2,.2,0]]
    normals = [[0,0,1], [0,0,-1], [0,0,1], [0,0,1], [1,0,0]]
    mask = module.surface_mask(centres, normals, [[0,0,0],[1,0,0],[0,1,0]], [[0,1,2]], .03)
    assert mask.tolist() == [True, True, False, False, False]


def test_explicit_bounds_preserve_frame_inside_pane_overlap():
    mask = module.surface_mask([[.1,.1,0],[.4,.1,0]], [[0,0,1]]*2,
                               [[0,0,0],[1,0,0],[0,1,0]], [[0,1,2]], .03,
                               [[.2,0,-.03],[1,1,.03]])
    assert mask.tolist() == [False, True]


def test_degenerate_pane_is_rejected_before_mutation():
    with pytest.raises(ValueError, match='degenerate'):
        module.surface_mask([[0,0,0]], [[0,0,1]], [[0,0,0],[1,0,0],[2,0,0]], [[0,1,2]], .03)


def test_fitted_zone_reports_the_existing_assembly_gate_contract(monkeypatch):
    # Load the actual selection entry point without importing Blender into pytest.
    folder = Path(__file__).resolve().parents[1] / 'mastersmith/blender'
    monkeypatch.syspath_prepend(str(folder))
    tree = ast.parse((folder / 'glasskit.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'pick_glass')
    namespace = {'np': np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<glass selection>', 'exec'), namespace)
    polygons = [SimpleNamespace(center=[.2,.2,0], normal=[0,0,1])]
    polygons += [SimpleNamespace(center=[.2,.2,-1], normal=[0,0,1]) for _ in range(49)]
    obj = SimpleNamespace(data=SimpleNamespace(polygons=polygons))
    zone = {'vertices': [[0,0,0],[1,0,0],[0,1,0]], 'triangles': [[0,1,2]], 'tolerance': .03}
    mask, stats, panes = namespace['pick_glass'](obj, zone, 'fitted')
    assert mask.sum() == 1
    assert stats['ok'] is True
    assert stats['share_of_part'] == pytest.approx(.02)
    assert stats['preserve_frame'] is True
    assert panes == (zone['vertices'], zone['triangles'])
    with pytest.raises(ValueError, match='under 8%'):
        namespace['pick_glass'](SimpleNamespace(data=SimpleNamespace(polygons=polygons[:1])), zone, 'fitted')

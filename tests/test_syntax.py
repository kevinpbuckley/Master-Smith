"""Every module parses: a patch script once left a literal newline inside a string (2026-09-17)."""
import os


def test_every_module_parses():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import ast, glob
    bad = []
    for p in glob.glob("mastersmith/**/*.py", recursive=True):
        try:
            ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError as e:
            bad.append((p, e.lineno))
    assert not bad, bad

"""The picture tools never draw over a picture that exists (2026-09-28: pictures cost money and were approved)."""
import os

from mastersmith import ms


def test_keep_existing_skips_a_present_picture(tmp_path, capsys):
    pic = tmp_path / "ref" / "ref_0.png"
    assert ms.keep_existing(str(pic)) is False            # nothing there: draw
    pic.parent.mkdir()
    pic.write_bytes(b"png")
    assert ms.keep_existing(str(pic)) is True             # there: keep, say so
    assert "kept" in capsys.readouterr().out
    assert ms.keep_existing(str(pic), redraw=True) is False


def test_existing_pictures_lists_refs_parts_and_builders(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref" / "ref_0.png").write_bytes(b"png")
    part = tmp_path / "parts" / "Barrel"
    part.mkdir(parents=True)
    (part / "side.png").write_bytes(b"png")
    (part / "build.py").write_text("def build(kit, L, W, H): return []")
    (part / "seed.glb").write_bytes(b"glb")               # a mesh is not a picture
    found = ms.existing_pictures(str(tmp_path))
    assert found == [os.path.join("ref", "ref_0.png"), os.path.join("parts", "Barrel", "side.png"),
                     os.path.join("parts", "Barrel", "build.py")]


def test_side_facing_catches_a_mirrored_part_picture(tmp_path):
    # 2026-09-29: the M4A1's grip was drawn facing backwards and assembled backwards
    from PIL import Image, ImageDraw
    from mastersmith import picturecheck
    plan = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(plan)
    d.polygon([(100, 60), (300, 60), (300, 90), (160, 150), (100, 150)], fill=(30, 30, 30))   # heavy at the back
    plan.save(tmp_path / "side.png")
    part = plan.crop((80, 40, 320, 170))
    part.save(tmp_path / "part.png")
    part.transpose(Image.FLIP_LEFT_RIGHT).save(tmp_path / "part_mirrored.png")
    box = [20, 80, 20, 85]                                     # percent: x 20-80, z 20-85
    assert not picturecheck.side_facing(str(tmp_path / "side.png"), box, str(tmp_path / "part.png"))["mirrored"]
    assert picturecheck.side_facing(str(tmp_path / "side.png"), box, str(tmp_path / "part_mirrored.png"))["mirrored"]


def _sheet(path, rows, cols, draw_in, bleed=None, lines=False):
    from PIL import Image, ImageDraw
    W, H = 400 * cols, 300 * rows
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    for (r, c) in draw_in:
        x0, y0 = c * 400 + 80, r * 300 + 60
        d.ellipse([x0, y0, x0 + 240, y0 + 180], fill=(40, 40, 40))
        d.rectangle([x0 + 100, y0 - 30, x0 + 110, y0 + 10], fill=(40, 40, 40))     # a sight, joined to its gun
    if lines:
        for c in range(1, cols):
            d.line([(c * 400, 0), (c * 400, H)], fill=(0, 0, 0), width=2)           # divider lines, as nano drew them
        for r in range(1, rows):
            d.line([(0, r * 300), (W, r * 300)], fill=(0, 0, 0), width=2)
    if bleed:
        r, c = bleed
        d.rectangle([c * 400 + 300, r * 300 + 100, c * 400 + 400 + 110, r * 300 + 200], fill=(40, 40, 40))   # across the gutter into the next panel
    im.save(path)


def test_sheet_cells_find_the_panels_in_reading_order_and_ignore_divider_lines(tmp_path):
    # 2026-10-04: nano laid three panels out as two over one wide one with lines between: the panels are found, not assumed
    from mastersmith import picturecheck
    p = tmp_path / "sheet.png"
    _sheet(str(p), 2, 2, [(0, 0), (0, 1), (1, 0), (1, 1)], lines=True)
    cells = picturecheck.sheet_cells(str(p), 4)
    assert [c["cell"] for c in cells] == [0, 1, 2, 3] and all(c["box"] for c in cells), cells
    x0, y0, x1, y1 = cells[3]["box"]
    assert 470 <= x0 <= 490 and 320 <= y0 <= 340 and 710 <= x1 <= 730 and 530 <= y1 <= 550   # the object (sight up), not the cell
    assert cells[1]["box"][0] > cells[0]["box"][2] and cells[2]["box"][1] > cells[0]["box"][3]


def test_sheet_cells_refuse_a_missing_panel_and_panels_that_ran_together(tmp_path):
    from mastersmith import picturecheck
    p = tmp_path / "sheet.png"
    _sheet(str(p), 2, 2, [(0, 0), (0, 1), (1, 1)])
    cells = picturecheck.sheet_cells(str(p), 4)
    assert all(c["box"] is None for c in cells) and "found 3 panels, asked for 4" in cells[0]["reason"], cells
    _sheet(str(p), 1, 2, [(0, 0), (0, 1)], bleed=(0, 0))
    cells = picturecheck.sheet_cells(str(p), 2)
    assert all(c["box"] is None for c in cells) and "ran together" in cells[0]["reason"]


def test_same_picture_tells_a_view_drawn_twice(tmp_path):
    from PIL import Image, ImageDraw
    from mastersmith import picturecheck
    a = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(a).polygon([(20, 100), (180, 60), (180, 140), (100, 120)], fill=(30, 30, 30))
    mirrored = a.transpose(Image.FLIP_LEFT_RIGHT)                   # the hero drawn again, muzzle the other way
    framed = Image.new("RGB", (400, 300), "white")
    framed.paste(a, (150, 50))                                      # the same view framed loosely, as a hero is
    other = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(other).ellipse([60, 20, 140, 180], fill=(30, 30, 30))      # an end-on view
    for name, im in (("a", a), ("m", mirrored), ("f", framed), ("o", other)):
        im.save(tmp_path / (name + ".png"))
    same = lambda x, y: picturecheck.same_picture(str(tmp_path / (x + ".png")), str(tmp_path / (y + ".png")))
    assert same("a", "f") > 0.97 and same("a", "m") > 0.97
    assert same("a", "o") < 0.9

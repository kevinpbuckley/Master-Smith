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

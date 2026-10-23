"""Reference crop beside the delivery's render, one picture per view, for the reviewers (2026-10-21).
    python cloud/compare.py <job dir> <out dir>
The job's ref/ holds exact crops of the sheet (ref_0 iso, ref_front, ref_back, ref_port, ref_side = starboard);
the top and bottom panels are cropped off the sheet here. Writes compare_<view>.png and contact.png."""
import os
import sys

from PIL import Image, ImageDraw

H = 450
# sheet panels not in ref/: (left, top, right, bottom) on proteus_refit_v3.png (1536 x 1024)
SHEET_CROPS = {"top": (517, 640, 1010, 1010), "bottom": (1026, 640, 1518, 1010)}
PAIRS = [("iso", "ref_0.png", "preview_iso.png"), ("front", "ref_front.png", "preview_front.png"),
         ("rear", "ref_back.png", "preview_back.png"), ("port", "ref_port.png", "preview_left.png"),
         ("starboard", "ref_side.png", "preview_right.png"), ("top", None, "preview_top.png"),
         ("bottom", None, "preview_bottom.png")]

SIX = {"rear": "back", "port": "right", "starboard": "left"}


def fit(im):
    return im.convert("RGB").resize((max(1, round(im.width * H / im.height)), H), Image.LANCZOS)


def main(job, out):
    os.makedirs(out, exist_ok=True)
    sheet = Image.open(os.path.join(job, "ref", "proteus_refit_v3.png"))
    rows = []
    for view, ref, render in PAIRS:
        rp = os.path.join(job, "delivery", render)
        if not os.path.exists(rp):
            # assemble writes the six sides as six_views/view_<side>.png; the sheet's port panel (bow left) is the
            # asset's right-hand view (Test A, 2026-10-22)
            rp = os.path.join(job, "six_views", "view_%s.png" % SIX.get(view, view))
        if not os.path.exists(rp):
            print("no render for %s (%s)" % (view, rp)); continue
        left = fit(sheet.crop(SHEET_CROPS[view])) if ref is None else fit(Image.open(os.path.join(job, "ref", ref)))
        right = fit(Image.open(rp))
        sheet_row = Image.new("RGB", (left.width + right.width + 12, H + 28), (30, 30, 30))
        sheet_row.paste(left, (0, 28)); sheet_row.paste(right, (left.width + 12, 28))
        d = ImageDraw.Draw(sheet_row)
        d.text((4, 6), "%s REFERENCE" % view.upper(), fill=(255, 200, 80))
        d.text((left.width + 16, 6), "%s RENDER" % view.upper(), fill=(120, 200, 255))
        p = os.path.join(out, "compare_%s.png" % view)
        sheet_row.save(p); rows.append(sheet_row); print("wrote", p)
    if rows:
        w = max(r.width for r in rows)
        contact = Image.new("RGB", (w, sum(r.height for r in rows)), (30, 30, 30))
        y = 0
        for r in rows:
            contact.paste(r, (0, y)); y += r.height
        contact.save(os.path.join(out, "contact.png")); print("wrote", os.path.join(out, "contact.png"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

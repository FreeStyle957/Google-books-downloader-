"""Verify long book titles no longer exceed Windows MAX_PATH."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402

TITLE = (
    "From Youthful Manuscripts to River Elegy_ The Chinese Popular Cultural ... "
    "(By Fangzheng Chen, Guantao Jin)"
)
BASE = Path(__file__).resolve().parent.parent / "downloads"

print("raw title len :", len(TITLE))
slug = core._safe(TITLE)
print("slug          :", repr(slug), len(slug))

outdir = BASE / slug
pdf = core._fit_path(outdir, slug, ".pdf")
print("outdir len    :", len(str(outdir)))
print("pdf len       :", len(str(pdf)))
print("pdf           :", pdf.name)
assert len(str(outdir)) < 260, "folder path too long"
assert len(str(pdf)) < 260, "pdf path too long"

# Real write test: create the dir, a small image, and build the PDF.
outdir.mkdir(parents=True, exist_ok=True)
from PIL import Image  # noqa: E402

img = Image.new("RGB", (600, 800), (250, 248, 240))
img_path = outdir / "page_0001_PP1.jpg"
img.save(img_path)

out_pdf = core.make_pdf([img_path], pdf)
print("pdf written   :", out_pdf)
assert out_pdf is not None and Path(out_pdf).exists(), "PDF was not created"
print("pdf size KB   :", round(Path(out_pdf).stat().st_size / 1024, 1))

# Also prove the old behaviour would have failed
old_pdf = outdir / f"{TITLE}.pdf"
print("old-style len :", len(str(old_pdf)), "-> exceeds 260:", len(str(old_pdf)) > 260)
print("PASS")

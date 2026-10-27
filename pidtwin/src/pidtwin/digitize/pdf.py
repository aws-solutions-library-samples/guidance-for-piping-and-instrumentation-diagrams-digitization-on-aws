"""Render P&ID PDF pages to PNG for the digitizer (pypdfium2: BSD-3 / Apache-2.0).

Usage: .venv/bin/python -m pidtwin.digitize.pdf drawing.pdf [--dpi 300] [--out-dir samples/]
       -> <stem>.p1.png, <stem>.p2.png, ...
Scanned ("PDF-image") sheets are rendered at the DPI asked for; the digitizer tiles large pages.
"""
import argparse
from pathlib import Path

MAX_SIDE = 20_000  # px: cap for very large sheets (A0 at 300 dpi is ~14000 px)


def render(pdf, out_dir=None, dpi=300, max_pages=None):
    import pypdfium2 as pdfium  # optional dependency: pip install '.[pdf]'
    pdf = Path(pdf)
    out_dir = Path(out_dir or pdf.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    if max_pages and len(doc) > max_pages:
        raise ValueError(f"{pdf.name} has {len(doc)} pages; the limit is {max_pages}")
    paths = []
    for i, page in enumerate(doc, 1):
        w, h = page.get_size()  # points (1/72 in)
        scale = min(dpi / 72, MAX_SIDE / max(w, h))
        img = page.render(scale=scale).to_pil().convert("L")
        path = out_dir / (f"{pdf.stem}.png" if len(doc) == 1 else f"{pdf.stem}.p{i}.png")
        img.save(path, optimize=True)
        paths.append(path)
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("--dpi", type=int, default=300); ap.add_argument("--out-dir")
    a = ap.parse_args()
    for p in render(a.pdf, a.out_dir, a.dpi):
        print(p)

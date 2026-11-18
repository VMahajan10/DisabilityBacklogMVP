"""OCR for pages with no (or almost no) text layer, via Tesseract (pytesseract)."""
import re

import pdfplumber
import pytesseract

WATERMARK_WORDS = {"synthetic", "test", "data"}


def render_page(page: "pdfplumber.page.Page", resolution: int = 300):
    return page.to_image(resolution=resolution).original.convert("L")


def ocr_page(page: "pdfplumber.page.Page", resolution: int = 300) -> tuple[str, float]:
    return ocr_image(render_page(page, resolution))


def ocr_image(img) -> tuple[str, float]:
    """Return (text, mean word confidence 0-100)."""
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 3")
    lines: dict[tuple, list[tuple[str, float]]] = {}
    for i, word in enumerate(d["text"]):
        w = (word or "").strip()
        conf = float(d["conf"][i])
        if not w or conf < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, []).append((w, conf))
    out, confs = [], []
    for key in sorted(lines):
        words = lines[key]
        toks = {re.sub(r"\W", "", w.lower()) for w, _ in words}
        # Drop stray fragments of the rotated watermark (short, low-confidence lines made of its words).
        if toks <= WATERMARK_WORDS | {""} and len(words) <= 3:
            continue
        if len(words) <= 2 and all(c < 50 for _, c in words):
            continue
        out.append(" ".join(w for w, _ in words))
        confs += [c for _, c in words]
    return "\n".join(out), round(sum(confs) / len(confs), 1) if confs else 0.0

"""PDF -> per-page text. The stored page text is the only source of truth for citations."""
import hashlib
from pathlib import Path

import pdfplumber

WATERMARK_MIN_FONT = 30  # diagonal watermark is drawn large and rotated


def _is_body_char(obj: dict) -> bool:
    if obj.get("object_type") != "char":
        return True
    # Drop the rotated, oversized "SYNTHETIC TEST DATA" watermark so it doesn't
    # interleave with clinical text. The footer notice (normal size) is kept.
    if not obj.get("upright", True):
        return False
    return obj.get("size", 0) < WATERMARK_MIN_FONT


def extract_pages(pdf_path: str | Path) -> list[str]:
    """Return a list of page texts, index 0 == page 1."""
    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.filter(_is_body_char).extract_text(layout=False) or ""
            pages.append(text.strip())
    return pages


def pdf_title(pdf_path: str | Path) -> str | None:
    with pdfplumber.open(str(pdf_path)) as pdf:
        title = (pdf.metadata or {}).get("Title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

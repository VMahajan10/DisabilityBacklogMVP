"""Tiny PDF builder for synthetic medical records (reportlab).

Every page gets a diagonal "SYNTHETIC TEST DATA" watermark, a facility header, and a
footer with "Page X of Y". Each logical page in the case definition starts a new PDF page,
so page citations line up with how the records were authored.
"""
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas
import io
import os
import tempfile

from reportlab.lib.utils import ImageReader
from reportlab.platypus import KeepInFrame, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_ss = getSampleStyleSheet()
STYLES = {
    "title": ParagraphStyle("t", parent=_ss["Heading2"], fontSize=13, spaceAfter=6),
    "h": ParagraphStyle("h", parent=_ss["Heading4"], fontSize=10.5, spaceBefore=6, spaceAfter=2),
    "p": ParagraphStyle("p", parent=_ss["BodyText"], fontSize=9.5, leading=12.5, spaceAfter=4),
    "small": ParagraphStyle("s", parent=_ss["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#333333")),
}


def _numbered_canvas(header: dict):
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int):
            w, h = LETTER
            scan = header.get("scan_images", {}).get(self._pageNumber)
            if scan is not None:
                # Scanned page: image only (no text layer) + the watermark drawn on top.
                self.drawImage(ImageReader(scan), 0, 0, width=w, height=h)
                self.saveState()
                self.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.13))
                self.setFont("Helvetica-Bold", 54)
                self.translate(w / 2, h / 2)
                self.rotate(40)
                self.drawCentredString(0, 0, "SYNTHETIC TEST DATA")
                self.restoreState()
                return
            # Watermark (rotated + large; extraction strips it as non-upright text)
            self.saveState()
            self.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.13))
            self.setFont("Helvetica-Bold", 54)
            self.translate(w / 2, h / 2)
            self.rotate(40)
            self.drawCentredString(0, 0, "SYNTHETIC TEST DATA")
            self.restoreState()
            # Header
            self.setFont("Helvetica-Bold", 9)
            self.drawString(0.75 * inch, h - 0.55 * inch, header["facility"])
            self.setFont("Helvetica", 8)
            self.drawString(0.75 * inch, h - 0.70 * inch, header.get("address", ""))
            self.drawRightString(w - 0.75 * inch, h - 0.55 * inch, f"Patient: {header['patient']}")
            self.drawRightString(w - 0.75 * inch, h - 0.70 * inch, f"DOB: {header['dob']}   MRN: {header['mrn']}")
            self.line(0.75 * inch, h - 0.78 * inch, w - 0.75 * inch, h - 0.78 * inch)
            # Footer
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(colors.HexColor("#9b1c1c"))
            self.drawString(0.75 * inch, 0.5 * inch, "SYNTHETIC TEST DATA - fictional record, not a real patient")
            self.setFillColor(colors.black)
            self.setFont("Helvetica", 7.5)
            self.drawRightString(w - 0.75 * inch, 0.5 * inch, f"{header['doc_title']}  |  Page {self._pageNumber} of {total}")

    return NumberedCanvas


def _block(block):
    kind = block[0]
    if kind in ("title", "h", "p", "small"):
        return [Paragraph(escape(block[1]), STYLES[kind])]
    if kind == "kv":  # list of (label, value)
        data = [[Paragraph(f"<b>{escape(k)}</b>", STYLES["p"]), Paragraph(escape(v), STYLES["p"])] for k, v in block[1]]
        t = Table(data, colWidths=[1.8 * inch, 5.0 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("TOPPADDING", (0, 0), (-1, -1), 1)]))
        return [t, Spacer(1, 4)]
    if kind == "sp":
        return [Spacer(1, block[1] if len(block) > 1 else 8)]
    raise ValueError(f"unknown block {kind}")


FRAME_W, FRAME_H = LETTER[0] - 1.5 * inch, LETTER[1] - 1.8 * inch - 12


def _build(path: str, header: dict, pages: list[list[tuple]], blank: set[int] = frozenset()) -> None:
    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=1.0 * inch, bottomMargin=0.8 * inch,
                            title=header["doc_title"], author="Synthetic data generator", subject="SYNTHETIC TEST DATA")
    story = []
    for i, page in enumerate(pages):
        if i:
            story.append(PageBreak())
        if i + 1 in blank:
            story.append(Spacer(1, 1))
            continue
        flow = [f for b in page for f in _block(b)]
        # Guarantee exactly one physical page per logical page so page citations stay exact.
        story.append(KeepInFrame(FRAME_W, FRAME_H, flow, mode="shrink"))
    doc.build(story, canvasmaker=_numbered_canvas(header))


def degrade_scan(img, seed: int):
    """Make a rendered page look scanned: grayscale, slight skew, speckle noise, JPEG artifacts."""
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seed)
    g = img.convert("L").rotate(float(rng.uniform(-1.2, 1.2)), resample=Image.BICUBIC, fillcolor=255, expand=False)
    a = np.asarray(g, dtype=np.int16)
    a = a + rng.normal(0, 9, a.shape).astype(np.int16)
    speck = rng.random(a.shape) < 0.0015
    a[speck] = 0
    g = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    buf = io.BytesIO()
    g.save(buf, format="JPEG", quality=55)
    buf.seek(0)
    return Image.open(buf)


def build_pdf(path: str, header: dict, pages: list[list[tuple]], scan_pages: set[int] | None = None,
              dpi: int = 150) -> int:
    """pages: list of logical pages (lists of blocks). scan_pages: 1-based page numbers to render as
    image-only "scanned" pages (no text layer). Returns the number of pages."""
    scan_pages = set(scan_pages or ())
    if not scan_pages:
        _build(path, header, pages)
        return len(pages)
    import pypdfium2 as pdfium

    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        _build(tmp, header, pages)  # pass 1: normal text rendering
        pdf = pdfium.PdfDocument(tmp)
        images = {}
        for n in sorted(scan_pages):
            bmp = pdf[n - 1].render(scale=dpi / 72).to_pil()
            images[n] = degrade_scan(bmp, seed=n * 7919 + len(pages))
        pdf.close()
    finally:
        os.unlink(tmp)
    _build(path, {**header, "scan_images": images}, pages, blank=scan_pages)  # pass 2: images, no text layer
    return len(pages)

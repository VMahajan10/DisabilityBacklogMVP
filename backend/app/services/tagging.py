"""Tag each page with document type, provider, and date of service.
Cheap rules first; the fast LLM only tags pages the rules can't classify."""
import re
from datetime import date

from pydantic import BaseModel, Field

from app.llm.base import LLMProvider
from app.llm.usage import pmap
from app.prompts import load_prompt

DOC_TYPES = ["fax_cover", "billing", "appointment_reminder", "privacy_notice", "pharmacy", "medication_list",
             "imaging", "pathology", "medical_source_statement", "consultative_exam", "physical_therapy",
             "emergency", "function_report", "nurse_visit", "lab", "progress_note", "operative_note", "other"]
ADMIN_TYPES = {"fax_cover", "billing", "appointment_reminder", "privacy_notice", "pharmacy", "medication_list"}

# (doc_type, pattern) checked against the top of the page first, then the whole page.
RULES = [
    ("fax_cover", r"fax cover|facsimile cover|fax transmittal"),
    ("billing", r"statement of account|billing statement|amount due|balance due|itemized charges"),
    ("appointment_reminder", r"appointment reminder|reminder of your upcoming"),
    ("privacy_notice", r"notice of privacy practices|authorization to release|patient consent form"),
    ("pharmacy", r"pharmacy fill history|prescription fill|rx fill record|pharmacy record"),
    ("medication_list", r"medication list|current medications list"),
    ("pathology", r"pathology report"),
    ("imaging", r"radiology report|imaging report|\bimpression\b.*|^xr |mri .* without contrast"),
    ("medical_source_statement", r"medical source statement"),
    ("consultative_exam", r"consultative (internal medicine )?exam"),
    ("operative_note", r"operative note|operative report"),
    ("function_report", r"function report"),
    ("emergency", r"emergency department|urgent care visit|\bed visit\b"),
    ("physical_therapy", r"physical therapy (initial|discharge|progress|daily|evaluation|re-?evaluation|note|treatment)|\bpt daily note\b"),
    ("lab", r"laboratory results|lab results"),
    ("nurse_visit", r"nurse visit|vitals only|blood pressure check"),
    ("progress_note", r"office visit|follow-up|progress note|consultation|subjective"),
]
_DATE_LABEL = re.compile(r"(?:date of service|exam date|visit date|service date|dos|collected|date completed|date)\s*[:\-]?\s*"
                         r"(\d{1,2}/\d{1,2}/\d{4})", re.I)
_ANY_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_FACILITY = re.compile(r"^(.*?\((?:fictional|fictional facsimile)\))", re.M)


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        m, d, y = (int(x) for x in s.split("/"))
        return date(y, m, d)
    except ValueError:
        return None


def rule_tag(text: str) -> dict:
    # Title area: the first few lines (facility header + document title), not narrative text.
    head = "\n".join(text.splitlines()[:5]).lower()
    doc_type = None
    for t, pat in RULES:
        if re.search(pat, head, re.M):
            doc_type = t
            break
    if doc_type is None:
        low = text.lower()
        for t, pat in RULES:
            if re.search(pat, low, re.M):
                doc_type = t
                break
    prov = None
    m = _FACILITY.search(text[:400])
    if m:
        prov = m.group(1).replace("Patient:", "").strip()
    body = "\n".join(ln for ln in text.splitlines() if "DOB" not in ln)
    dm = _DATE_LABEL.search(body) or _ANY_DATE.search(body)
    return {"doc_type": doc_type, "provider": prov, "service_date": parse_date(dm.group(1)) if dm else None}


class PageTag(BaseModel):
    page_ref: str
    doc_type: str = Field(description="One of: " + ", ".join(DOC_TYPES))
    provider: str | None
    service_date: str | None = Field(description="MM/DD/YYYY or null")


class PageTags(BaseModel):
    tags: list[PageTag]


def llm_tag(pages: list[tuple[str, str]], provider: LLMProvider, batch: int = 20) -> dict[str, dict]:
    """pages: [(ref, text)] -> {ref: tag}. Uses the fast model on the first part of each page."""
    prompt = load_prompt("page_tagging")
    groups = [pages[i:i + batch] for i in range(0, len(pages), batch)]

    def run(g):
        items = "\n\n".join(f"### PAGE {ref}\n{text[:900]}" for ref, text in g)
        return provider.complete_structured(prompt.system, prompt.render_user(items=items), PageTags,
                                            model=provider.fast_model).parsed.tags

    out = {}
    for tags in pmap(run, groups):
        for t in tags:
            out[t.page_ref] = {"doc_type": t.doc_type if t.doc_type in DOC_TYPES else "other",
                               "provider": t.provider, "service_date": parse_date(t.service_date)}
    return out

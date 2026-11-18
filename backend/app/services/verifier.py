"""Citation verifier: does the quoted text actually appear on the cited page?

Exact match after normalization first; otherwise a sliding word-window fuzzy match
(difflib). Returns character offsets into the ORIGINAL page text so the UI can highlight.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app import config

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ", "…": "...",
})
MIN_QUOTE_CHARS = 8


@dataclass
class VerificationResult:
    verified: bool
    score: float
    start: int | None = None  # offsets into the original page text
    end: int | None = None
    reason: str | None = None  # why verification failed


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify quotes/dashes, collapse whitespace. Returns (normalized, index map to original)."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text.translate(_TRANSLATE)):
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
            continue
        out.append(ch.lower())
        idx.append(i)
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026|\[\.\.\.\])\s*")


def verify_quote(page_text: str | None, quote: str, threshold: float | None = None) -> VerificationResult:
    """Verify a quote on a page. A quote with an ellipsis ("...") is treated as an elision:
    every fragment must independently appear on the page, and the highlight spans all fragments."""
    threshold = config.VERIFY_THRESHOLD if threshold is None else threshold
    fragments = [f for f in _ELLIPSIS.split(quote) if f.strip(" \"'.,;")]
    if len(fragments) > 1:
        if page_text is None:
            return VerificationResult(False, 0.0, reason="cited page does not exist")
        results = [_verify_single(page_text, f, threshold) for f in fragments]
        bad = [r for r in results if not r.verified]
        if bad:
            return VerificationResult(False, min(r.score for r in results),
                                      reason=f"{len(bad)} of {len(results)} quoted fragments not found on page")
        return VerificationResult(True, min(r.score for r in results),
                                  min(r.start for r in results), max(r.end for r in results))
    return _verify_single(page_text, quote, threshold)


def _verify_single(page_text: str | None, quote: str, threshold: float) -> VerificationResult:
    if page_text is None:
        return VerificationResult(False, 0.0, reason="cited page does not exist")
    q = normalize(quote).strip(" \"'.")
    if len(q) < MIN_QUOTE_CHARS:
        return VerificationResult(False, 0.0, reason="quote too short to verify")
    norm, idx = normalize_with_map(page_text)
    if not norm:
        return VerificationResult(False, 0.0, reason="cited page has no text")

    pos = norm.find(q)
    if pos >= 0:
        return VerificationResult(True, 1.0, idx[pos], idx[pos + len(q) - 1] + 1)

    # Fuzzy: compare quote against word windows of similar length.
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", norm)]
    n = len(q.split())
    best = (0.0, None, None)
    for size in range(max(1, n - 3), n + 4):
        for i in range(0, max(1, len(words) - size + 1)):
            j = min(len(words), i + size) - 1
            s, e = words[i][0], words[j][1]
            cand = norm[s:e]
            sm = SequenceMatcher(None, q, cand, autojunk=False)
            if sm.real_quick_ratio() <= best[0] or sm.quick_ratio() <= best[0]:
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, s, e)
    score, s, e = best
    if score >= threshold and s is not None:
        return VerificationResult(True, round(score, 3), idx[s], idx[e - 1] + 1)
    return VerificationResult(False, round(score, 3), reason=f"quote not found on page (best match {score:.0%})")

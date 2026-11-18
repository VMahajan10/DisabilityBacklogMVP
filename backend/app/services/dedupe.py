"""Duplicate page detection: exact (hash of normalized text) and near-duplicate (MinHash + LSH,
verified by Jaccard similarity on 5-word shingles). Fax headers, page headers/footers and the
synthetic-data notice are stripped before comparison, and near-duplicates must share the same set of
clinical dates (so an appointment reminder for a different date is NOT a duplicate)."""
import hashlib
import re
from dataclasses import dataclass

import numpy as np

from app import config

_STRIP_LINE = re.compile(
    r"(page \d+ of \d+|synthetic test data|^fax\b|\bfax (received|sent)\b|^from:|^to:|^sent:|^received:|"
    r"patient:|\bdob:|\bmrn:|^p\.\s*\d+/\d+|transmission|^\s*$)", re.I)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_P = (1 << 31) - 1
_PERMS = 128
_BANDS = 32
_rng = np.random.default_rng(12345)
_A = _rng.integers(1, _P, _PERMS, dtype=np.int64)
_B = _rng.integers(0, _P, _PERMS, dtype=np.int64)


def normalize_for_dedupe(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not _STRIP_LINE.search(ln.strip())]
    return re.sub(r"\s+", " ", " ".join(lines)).strip().lower()


def clinical_dates(norm: str) -> frozenset[str]:
    return frozenset(f"{int(m)}/{int(d)}/{y}" for m, d, y in _DATE.findall(norm))


def text_hash(norm: str) -> str:
    return hashlib.sha256(norm.encode()).hexdigest()


def shingles(norm: str, k: int = 5) -> set[str]:
    w = norm.split()
    return {" ".join(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def minhash(sh: set[str]) -> np.ndarray:
    if not sh:
        return np.full(_PERMS, _P, dtype=np.int64)
    x = np.array([int.from_bytes(hashlib.blake2b(s.encode(), digest_size=4).digest(), "little") for s in sh],
                 dtype=np.int64)
    return ((np.outer(_A, x) + _B[:, None]) % _P).min(axis=1)


@dataclass
class PageSig:
    page_id: int
    order: tuple  # (document_id, page_number) - earlier is treated as the original
    norm: str
    hash: str
    dates: frozenset
    sh: set
    sig: np.ndarray | None


def build_sig(page_id: int, order: tuple, text: str) -> PageSig:
    norm = normalize_for_dedupe(text)
    sh = shingles(norm)
    return PageSig(page_id, order, norm, text_hash(norm), clinical_dates(norm), sh,
                   minhash(sh) if len(norm.split()) >= 25 else None)


def find_duplicates(sigs: list[PageSig], threshold: float | None = None) -> dict[int, tuple[int, str, float]]:
    """Return {duplicate_page_id: (original_page_id, 'exact'|'near', similarity)}."""
    threshold = config.NEAR_DUP_JACCARD if threshold is None else threshold
    sigs = sorted(sigs, key=lambda s: s.order)
    out: dict[int, tuple[int, str, float]] = {}
    first_by_hash: dict[str, PageSig] = {}
    for s in sigs:
        if len(s.norm) < 20:
            continue
        if s.hash in first_by_hash:
            out[s.page_id] = (first_by_hash[s.hash].page_id, "exact", 1.0)
        else:
            first_by_hash[s.hash] = s
    rows = _PERMS // _BANDS
    by_id = {s.page_id: s for s in sigs}
    buckets: dict[tuple, list[PageSig]] = {}
    for s in sigs:
        if s.sig is None or s.page_id in out:
            continue
        cands = set()
        for b in range(_BANDS):
            key = (b, s.sig[b * rows:(b + 1) * rows].tobytes())
            for other in buckets.get(key, []):
                cands.add(other.page_id)
            buckets.setdefault(key, []).append(s)
        cands.discard(s.page_id)
        best = None
        for cid in cands:
            o = by_id[cid]
            if o.page_id in out or o.dates != s.dates:
                continue
            j = len(s.sh & o.sh) / max(1, len(s.sh | o.sh))
            if j >= threshold and (best is None or j > best[2]):
                best = (o.page_id, "near", round(j, 3))
        if best:
            out[s.page_id] = best
    return out

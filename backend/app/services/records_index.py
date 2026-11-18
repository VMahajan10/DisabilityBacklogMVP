"""Claimant record chunk index: chunk each (non-duplicate) page, embed, and search with numpy.
Chunks never cross a page boundary, so every hit maps to an exact document + page."""
from dataclasses import dataclass
from threading import Lock

import numpy as np
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models import Page, RecordChunk

CHUNK_CHARS = 1200
OVERLAP = 200


def chunk_page_text(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            sp = text.rfind(" ", start + CHUNK_CHARS // 2, end)
            end = sp if sp > 0 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return out


def index_pages(db: Session, claim_id: int, pages: list[Page], provider: LLMProvider, progress=None) -> int:
    rows = []
    for p in pages:
        if p.duplicate_of_page_id:
            continue
        for i, ch in enumerate(chunk_page_text(p.text)):
            rows.append(RecordChunk(claim_id=claim_id, document_id=p.document_id, page_id=p.id,
                                    page_number=p.page_number, chunk_index=i, text=ch, is_admin=bool(p.is_admin)))
    if progress:
        progress(stage="embedding", chunks_total=len(rows), chunks_embedded=0)
    for i in range(0, len(rows), 200):
        batch = rows[i:i + 200]
        embs = provider.embed([r.text for r in batch])
        for r, e in zip(batch, embs):
            r.embedding = np.asarray(e, dtype=np.float32).tobytes()
        db.add_all(batch)
        db.commit()
        if progress:
            progress(chunks_embedded=min(i + 200, len(rows)))
    invalidate(claim_id)
    return len(rows)


@dataclass
class _Index:
    n: int
    mat: np.ndarray  # normalized float32 [n, d]
    ids: np.ndarray
    doc: np.ndarray
    page: np.ndarray
    admin: np.ndarray


_cache: dict[int, _Index] = {}
_lock = Lock()


def invalidate(claim_id: int):
    with _lock:
        _cache.pop(claim_id, None)


def _load(db: Session, claim_id: int) -> _Index | None:
    n = db.query(RecordChunk).filter(RecordChunk.claim_id == claim_id, RecordChunk.embedding.isnot(None)).count()
    with _lock:
        idx = _cache.get(claim_id)
        if idx and idx.n == n:
            return idx
    rows = (db.query(RecordChunk.id, RecordChunk.document_id, RecordChunk.page_number, RecordChunk.is_admin,
                     RecordChunk.embedding)
            .filter(RecordChunk.claim_id == claim_id, RecordChunk.embedding.isnot(None)).all())
    if not rows:
        return None
    mat = np.vstack([np.frombuffer(r.embedding, dtype=np.float32) for r in rows])
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    idx = _Index(len(rows), mat, np.array([r.id for r in rows]), np.array([r.document_id for r in rows]),
                 np.array([r.page_number for r in rows]), np.array([bool(r.is_admin) for r in rows]))
    with _lock:
        _cache[claim_id] = idx
    return idx


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    page_number: int
    score: float


def search(db: Session, claim_id: int, provider: LLMProvider, queries: list[str], k: int = 6,
           include_admin: bool = False) -> list[list[Hit]]:
    """Return, for each query, the top-k PAGES (best chunk score per page)."""
    if not queries:
        return []
    return search_vectors(db, claim_id, provider.embed(queries), k, include_admin)


def search_vectors(db: Session, claim_id: int, vectors: list[list[float]], k: int = 6,
                   include_admin: bool = False) -> list[list[Hit]]:
    idx = _load(db, claim_id)
    if idx is None or not len(vectors):
        return [[] for _ in vectors]
    q = np.asarray(vectors, dtype=np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9
    scores = q @ idx.mat.T
    if not include_admin:
        scores[:, idx.admin] = -1
    out = []
    for row in scores:
        order = np.argsort(-row)
        seen, hits = set(), []
        for j in order:
            if row[j] < 0:
                break
            key = (int(idx.doc[j]), int(idx.page[j]))
            if key in seen:
                continue
            seen.add(key)
            hits.append(Hit(int(idx.ids[j]), key[0], key[1], float(row[j])))
            if len(hits) >= k:
                break
        out.append(hits)
    return out


def similarity_matrix(db: Session, claim_id: int, vectors: list[list[float]], include_admin: bool = False) -> np.ndarray | None:
    """Cosine similarity [len(vectors), n_chunks] against the claim's (non-admin) chunks."""
    idx = _load(db, claim_id)
    if idx is None or not len(vectors):
        return None
    q = np.asarray(vectors, dtype=np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9
    m = q @ idx.mat.T
    if not include_admin:
        m = m[:, ~idx.admin]
    return m

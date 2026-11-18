"""Minimal in-memory vector search over embeddings persisted in SQLite (~200 listing chunks, ~300 CAL names)."""
import math


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def top_k(query: list[float], items: list[tuple[object, list[float]]], k: int) -> list[tuple[object, float]]:
    scored = [(obj, cosine(query, emb)) for obj, emb in items if emb]
    return sorted(scored, key=lambda t: t[1], reverse=True)[:k]

"""Deterministic provider for tests. Never used at runtime unless LLM_PROVIDER=fake.

`responses` may be a list (consumed in order by any schema) or a dict mapping schema class
name -> list of JSON strings, or -> a callable(system, user) returning a JSON string."""
import hashlib
import json
import math

from pydantic import ValidationError

from app.llm.base import LLMValidationError, StructuredResult, T


class FakeProvider:
    name = "fake"
    model = "fake-model"
    fast_model = "fake-fast"
    embedding_model = "fake-embed"

    def __init__(self, responses=None):
        self.responses = responses if isinstance(responses, dict) else list(responses or [])
        self.calls: list[dict] = []

    def _next(self, schema, system, user) -> str:
        if isinstance(self.responses, dict):
            r = self.responses.get(schema.__name__)
            if callable(r):
                return r(system, user)
            return r.pop(0) if r else "{}"
        return self.responses.pop(0) if self.responses else "{}"

    def complete_structured(self, system: str, user: str, schema: type[T], max_retries: int = 2,
                            model: str | None = None) -> StructuredResult[T]:
        last_err = None
        for attempt in range(1, max_retries + 2):
            self.calls.append({"system": system, "user": user, "schema": schema.__name__, "model": model or self.model})
            raw = self._next(schema, system, user)
            try:
                parsed = schema.model_validate(json.loads(raw))
                return StructuredResult(parsed, raw, self.name, model or self.model, attempt, 0)
            except (ValidationError, json.JSONDecodeError) as e:
                last_err = e
        raise LLMValidationError(str(last_err))

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Bag-of-words hashing embedding: good enough for deterministic retrieval tests.
        vecs = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1
            vecs.append([x / n for x in v])
        return vecs

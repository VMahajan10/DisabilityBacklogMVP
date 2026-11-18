"""Provider-agnostic LLM interface. Every model call in the app goes through this."""
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(RuntimeError):
    """Raised when a provider can't produce schema-valid output after all retries."""


@dataclass
class StructuredResult(Generic[T]):
    parsed: T
    raw_json: str
    provider: str
    model: str
    attempts: int
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    name: str
    model: str
    embedding_model: str

    fast_model: str

    def complete_structured(
        self, system: str, user: str, schema: type[T], max_retries: int = 2, model: str | None = None
    ) -> StructuredResult[T]:
        """Return output parsed and validated against `schema`; retry on validation failure."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

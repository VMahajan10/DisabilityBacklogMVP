import json
import time

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app import config
from app.llm import usage
from app.llm.base import LLMValidationError, StructuredResult, T


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None, embedding_model: str | None = None, client: OpenAI | None = None):
        self.model = model or config.OPENAI_MODEL
        self.embedding_model = embedding_model or config.OPENAI_EMBEDDING_MODEL
        self.fast_model = config.OPENAI_FAST_MODEL
        self._client = client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()  # reads OPENAI_API_KEY from env
        return self._client

    def complete_structured(self, system: str, user: str, schema: type[T], max_retries: int = 2,
                            model: str | None = None) -> StructuredResult[T]:
        model = model or self.model
        tin = tout = 0
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        start = time.monotonic()
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 2):
            completion = self.client.chat.completions.parse(
                model=model, messages=messages, response_format=schema, temperature=0
            )
            u = completion.usage
            if u:
                tin += u.prompt_tokens or 0
                tout += u.completion_tokens or 0
                usage.record(completion.model, "chat", u.prompt_tokens or 0, u.completion_tokens or 0)
            msg = completion.choices[0].message
            raw = msg.content or ""
            if msg.refusal:
                last_err = LLMValidationError(f"Model refused: {msg.refusal}")
            else:
                try:
                    # Re-validate independently of the SDK's parse step.
                    parsed = schema.model_validate(json.loads(raw))
                    return StructuredResult(
                        parsed=parsed, raw_json=raw, provider=self.name, model=completion.model,
                        attempts=attempt, latency_ms=int((time.monotonic() - start) * 1000),
                        input_tokens=tin, output_tokens=tout,
                    )
                except (ValidationError, json.JSONDecodeError) as e:
                    last_err = e
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your output failed validation: {last_err}. Return corrected JSON only."},
            ]
        raise LLMValidationError(f"No valid output after {max_retries + 1} attempts: {last_err}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            resp = self.client.embeddings.create(model=self.embedding_model, input=texts[i : i + 100])
            out += [d.embedding for d in resp.data]
            if resp.usage:
                usage.record(self.embedding_model, "embed", resp.usage.prompt_tokens or 0)
        return out

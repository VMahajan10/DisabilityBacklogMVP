from functools import lru_cache

from app import config
from app.llm.base import LLMProvider


@lru_cache
def get_provider() -> LLMProvider:
    """To add a provider (e.g. FedGenius): write an adapter implementing LLMProvider and register it here."""
    if config.LLM_PROVIDER == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if config.LLM_PROVIDER == "fake":
        from app.llm.fake_provider import FakeProvider

        return FakeProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER}")

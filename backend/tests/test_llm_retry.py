import pytest
from pydantic import BaseModel

from app.llm.base import LLMValidationError
from app.llm.fake_provider import FakeProvider
from app.prompts import load_prompt


class Out(BaseModel):
    answer: str
    n: int


def test_retries_until_valid():
    p = FakeProvider(['{"answer": "x"}', "not json", '{"answer": "ok", "n": 2}'])
    r = p.complete_structured("s", "u", Out, max_retries=2)
    assert r.parsed.n == 2 and r.attempts == 3


def test_raises_after_retries_exhausted():
    p = FakeProvider(['{"answer": 1}'] * 3)
    with pytest.raises(LLMValidationError):
        p.complete_structured("s", "u", Out, max_retries=2)


def test_prompt_loader_versions():
    pr = load_prompt("summary")  # latest version wins
    assert pr.version == "v2" and len(pr.sha) == 64
    v1 = load_prompt("summary", "v1")  # older versions stay loadable for audit/replay
    assert v1.version == "v1" and v1.sha != pr.sha
    assert "{evidence}" in pr.user_template and "EXACTLY" in pr.system

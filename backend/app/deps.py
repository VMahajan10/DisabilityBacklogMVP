from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm.base import LLMProvider
from app.llm.registry import get_provider
from app.models import Claim


def provider_dep() -> LLMProvider:
    return get_provider()


def get_claim(claim_id: int, db: Session = Depends(get_db)) -> Claim:
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    return claim

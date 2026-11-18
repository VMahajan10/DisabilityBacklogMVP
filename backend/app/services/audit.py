import hashlib
import json

from sqlalchemy.orm import Session

from app import config
from app.llm.base import StructuredResult
from app.models import AIRun, AuditEvent
from app.prompts import Prompt


def log_event(db: Session, claim_id: int, actor_type: str, event_type: str, payload: dict | None = None,
              actor: str | None = None, ai_run_id: int | None = None) -> AuditEvent:
    if actor is None:
        actor = {"human": config.DEMO_EXAMINER["name"], "system": "system"}.get(actor_type, "ai")
    ev = AuditEvent(claim_id=claim_id, actor_type=actor_type, actor=actor, event_type=event_type,
                    payload_json=payload or {}, ai_run_id=ai_run_id)
    db.add(ev)
    db.flush()
    return ev


def record_ai_run(db: Session, claim_id: int, kind: str, prompt: Prompt, result: StructuredResult,
                  input_text: str, output: dict) -> AIRun:
    run = AIRun(
        claim_id=claim_id, kind=kind, provider=result.provider, model=result.model,
        prompt_name=prompt.name, prompt_version=prompt.version, prompt_sha=prompt.sha,
        input_hash=hashlib.sha256(input_text.encode()).hexdigest(), output_json=output,
        attempts=result.attempts, latency_ms=result.latency_ms,
        input_tokens=getattr(result, "input_tokens", 0), output_tokens=getattr(result, "output_tokens", 0),
    )
    db.add(run)
    db.flush()
    return run


def log_ai_run_event(db: Session, run: AIRun, verification: dict | None = None) -> AuditEvent:
    return log_event(
        db, run.claim_id, "ai", f"ai_{run.kind}", actor=f"{run.provider}:{run.model}", ai_run_id=run.id,
        payload={
            "prompt": f"{run.prompt_name}/{run.prompt_version}", "prompt_sha": run.prompt_sha,
            "model": run.model, "provider": run.provider, "attempts": run.attempts,
            "latency_ms": run.latency_ms, "input_hash": run.input_hash,
            "verification": verification or {}, "output": json.loads(json.dumps(run.output_json, default=str)),
        },
    )

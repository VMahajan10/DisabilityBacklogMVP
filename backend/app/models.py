from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Claim(Base):
    __tablename__ = "claim"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_number: Mapped[str] = mapped_column(String(32), unique=True)
    claimant_name: Mapped[str] = mapped_column(String(120))
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    alleged_onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="intake")  # intake|in_review|decided
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    synthetic_case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    documents: Mapped[list["Document"]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    filename: Mapped[str] = mapped_column(String(255))
    doc_label: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="ready")  # processing|ready|error
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="documents")
    pages: Mapped[list["Page"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Page.page_number"
    )


class Page(Base):
    """Extracted page text: the ONLY source of truth for citations."""

    __tablename__ = "page"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based
    text: Mapped[str] = mapped_column(Text)
    # Ingestion metadata (scale pipeline)
    ocr: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duplicate_of_page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)  # exact|near
    doc_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_admin: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    tag_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # rule|llm

    document: Mapped[Document] = relationship(back_populates="pages")


class ListingChunk(Base):
    __tablename__ = "listing_chunk"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_code: Mapped[str] = mapped_column(String(16))  # "1.15" or "1.00"
    criterion_id: Mapped[str] = mapped_column(String(32))  # "1.15A", "1.15A1", "1.00C"
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    level: Mapped[str] = mapped_column(String(16))  # intro|listing|criterion|subcriterion
    seq: Mapped[int] = mapped_column(Integer)  # document order
    heading: Mapped[str] = mapped_column(String(500), default="")
    text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(500))
    fetched_at: Mapped[str] = mapped_column(String(40))
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class AIRun(Base):
    __tablename__ = "ai_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    kind: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    prompt_sha: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    output_json: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Citation(Base):
    __tablename__ = "citation"
    id: Mapped[int] = mapped_column(primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_run.id"))
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    item_ref: Mapped[str] = mapped_column(String(64))
    statement: Mapped[str] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Second-stage check (listing match): does this verified quote actually support the claim?
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class QueueAssignment(Base):
    __tablename__ = "queue_assignment"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    ai_suggested_queue: Mapped[str] = mapped_column(String(32))
    ai_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_queue: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    examiner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RecordsRequest(Base):
    __tablename__ = "records_request"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    ai_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_text: Mapped[str] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Determination(Base):
    __tablename__ = "determination"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    examiner_id: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(32))  # allowed|denied|needs_development
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence_reviewed_confirmed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    actor_type: Mapped[str] = mapped_column(String(16))  # ai|human|system
    actor: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(64))
    ai_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CalCondition(Base):
    __tablename__ = "cal_condition"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    poms_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str] = mapped_column(String(500))
    fetched_at: Mapped[str] = mapped_column(String(40))
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class RecordChunk(Base):
    """A searchable chunk of ONE claimant page (chunks never span pages, so hits map to doc + page)."""
    __tablename__ = "record_chunk"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"), index=True)
    document_id: Mapped[int] = mapped_column(Integer)
    page_id: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # float32


class ProcessingJob(Base):
    __tablename__ = "processing_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # ingest|summary|listing_match|missing_evidence|triage
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|done|error
    stage: Mapped[str] = mapped_column(String(64), default="")
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UsageLog(Base):
    """Token usage per model call, for cost reporting."""
    __tablename__ = "usage_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # chat|embed
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

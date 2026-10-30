from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.dialects.mysql import LONGBLOB, DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid4())


DT = DateTime().with_variant(DATETIME(fsp=6), 'mysql', 'mariadb')
BLOB = LargeBinary().with_variant(LONGBLOB(), 'mysql', 'mariadb')


class Base(DeclarativeBase):
    pass


class EnrichmentInput(Base):
    __tablename__ = 'enrichment_inputs'
    source_message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    exact_payload: Mapped[bytes] = mapped_column(BLOB)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    stream_sequence: Mapped[int] = mapped_column(Integer)
    accepted_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class InvalidInput(Base):
    __tablename__ = 'invalid_inputs'
    payload_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    exact_payload: Mapped[bytes] = mapped_column(BLOB)
    stream_sequence: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class EnrichmentJob(Base):
    __tablename__ = 'enrichment_jobs'
    __table_args__ = (Index('ix_enrichment_jobs_due', 'status', 'next_retry_at', 'lease_until'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_message_id: Mapped[str] = mapped_column(ForeignKey('enrichment_inputs.source_message_id'), unique=True)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DT)
    last_error_type: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(String(200))
    failed_at: Mapped[datetime | None] = mapped_column(DT)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DT)


class FetchSnapshot(Base):
    __tablename__ = 'fetch_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey('enrichment_jobs.id'), unique=True)
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DT)
    http_status: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(200))
    content_length: Mapped[int] = mapped_column(Integer)
    response_hash: Mapped[str] = mapped_column(String(64))
    raw_body: Mapped[bytes] = mapped_column(BLOB)
    redirect_count: Mapped[int] = mapped_column(Integer)
    safe_headers: Mapped[dict] = mapped_column(JSON)


class EnrichedDocument(Base):
    __tablename__ = 'enriched_documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_message_id: Mapped[str] = mapped_column(ForeignKey('enrichment_inputs.source_message_id'), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('enrichment_jobs.id'), unique=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DT, default=utcnow)


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (Index('ix_outbox_due', 'status', 'next_attempt_at', 'lease_until'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(String(36), unique=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('enriched_documents.id'), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DT, default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DT)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    last_error: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DT)


class HostSlot(Base):
    __tablename__ = 'fetch_host_slots'
    hostname: Mapped[str] = mapped_column(String(253), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DT)

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Integer, DateTime, JSON, Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
DT = DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
TXT = Text().with_variant(LONGTEXT(),'mysql','mariadb')
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id(): return str(uuid4())
class Base(DeclarativeBase): pass
class EvaluationInput(Base):
    __tablename__ = 'evaluation_inputs'
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    exact_payload: Mapped[str] = mapped_column(TXT)
    provenance: Mapped[dict] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String(16),index=True)
    fixture_label: Mapped[str|None] = mapped_column(String(100))
    fixture_input: Mapped[dict|None] = mapped_column(JSON)
    policy: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
class EvaluationJob(Base):
    __tablename__ = 'evaluation_jobs'
    __table_args__ = (Index('ix_evaluation_due','status','next_attempt_at','lease_until'),)
    id: Mapped[str] = mapped_column(ForeignKey('evaluation_inputs.id'),primary_key=True)
    prepared: Mapped[dict|None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16),default='active')
    next_attempt_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
    lease_token: Mapped[str|None] = mapped_column(String(36))
    lease_until: Mapped[datetime|None] = mapped_column(DT)
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    error: Mapped[str|None] = mapped_column(String(100))
class Evaluation(Base):
    __tablename__ = 'evaluations'
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey('evaluation_inputs.id'),unique=True)
    event_id: Mapped[str] = mapped_column(String(36),index=True)
    origin: Mapped[str] = mapped_column(String(16),index=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
class EvaluationResult(Base):
    __tablename__ = 'evaluation_results'
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('evaluations.id'),primary_key=True)
    horizon_seconds: Mapped[int] = mapped_column(Integer,primary_key=True)
    status: Mapped[str] = mapped_column(String(16),index=True)
    payload: Mapped[dict] = mapped_column(JSON)
class EvaluationRevision(Base):
    __tablename__ = 'evaluation_revisions'
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('evaluations.id'),primary_key=True)
    revision: Mapped[int] = mapped_column(Integer,primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (UniqueConstraint('evaluation_id','revision'),)
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=new_id)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('evaluations.id'),index=True)
    revision: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(String(36),unique=True)
    subject: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16),default='pending')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DT,default=utcnow)
    lease_token: Mapped[str|None] = mapped_column(String(36))
    lease_until: Mapped[datetime|None] = mapped_column(DT)
    last_error: Mapped[str|None] = mapped_column(String(100))
    published_at: Mapped[datetime|None] = mapped_column(DT)
class DeadInput(Base):
    __tablename__ = 'dead_inputs'
    id: Mapped[str] = mapped_column(String(64),primary_key=True)
    payload: Mapped[str] = mapped_column(TXT)
    reason: Mapped[str] = mapped_column(String(100))

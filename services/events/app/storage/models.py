from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import DateTime,ForeignKey,Index,Integer,BigInteger,JSON,LargeBinary,String,Text,UniqueConstraint,Float,Boolean
from sqlalchemy.dialects.mysql import LONGBLOB,DATETIME
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid4())


DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
BLOB=LargeBinary().with_variant(LONGBLOB(),'mysql','mariadb')


class Base(DeclarativeBase):
    pass


class EventInput(Base):
    __tablename__='event_inputs'
    document_id: Mapped[str]=mapped_column(String(36),primary_key=True)
    input_message_id: Mapped[str]=mapped_column(String(36))
    source_id: Mapped[str]=mapped_column(String(64),index=True)
    exact_payload: Mapped[bytes]=mapped_column(BLOB)
    payload: Mapped[dict]=mapped_column(JSON)
    payload_hash: Mapped[str]=mapped_column(String(64))
    stream_sequence: Mapped[int]=mapped_column(BigInteger)
    received_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class DeadInput(Base):
    __tablename__='dead_inputs'
    payload_hash: Mapped[str]=mapped_column(String(64),primary_key=True)
    exact_payload: Mapped[bytes]=mapped_column(BLOB)
    validation_error: Mapped[str]=mapped_column(String(512))
    subject: Mapped[str]=mapped_column(String(100))
    jetstream_metadata: Mapped[dict]=mapped_column(JSON)
    received_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class EventJob(Base):
    __tablename__='event_jobs'
    __table_args__=(Index('ix_jobs_due','status','next_retry_at','lease_until'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    document_id: Mapped[str]=mapped_column(ForeignKey('event_inputs.document_id'),unique=True)
    status: Mapped[str]=mapped_column(String(16),default='pending')
    outcome: Mapped[str|None]=mapped_column(String(32))
    attempt_count: Mapped[int]=mapped_column(Integer,default=0)
    next_retry_at: Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token: Mapped[str|None]=mapped_column(String(36))
    lease_until: Mapped[datetime|None]=mapped_column(DT)
    last_error_type: Mapped[str|None]=mapped_column(String(100))
    failed_at: Mapped[datetime|None]=mapped_column(DT)
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)
    completed_at: Mapped[datetime|None]=mapped_column(DT)


class ExtractionRun(Base):
    __tablename__='extraction_runs'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    job_id: Mapped[str|None]=mapped_column(ForeignKey('event_jobs.id'),unique=True)
    document_id: Mapped[str]=mapped_column(ForeignKey('event_inputs.document_id'),index=True)
    extractor_name: Mapped[str]=mapped_column(String(64))
    extractor_version: Mapped[str]=mapped_column(String(32))
    ruleset_version: Mapped[str]=mapped_column(String(32))
    taxonomy_version: Mapped[str]=mapped_column(String(32))
    entity_registry_version: Mapped[str]=mapped_column(String(32))
    config_hash: Mapped[str]=mapped_column(String(64))
    configuration: Mapped[dict]=mapped_column(JSON)
    input_quality: Mapped[dict]=mapped_column(JSON)
    result_json: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class CandidateRecord(Base):
    __tablename__='event_candidates'
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    run_id: Mapped[str]=mapped_column(ForeignKey('extraction_runs.id'),index=True)
    document_id: Mapped[str]=mapped_column(ForeignKey('event_inputs.document_id'),index=True)
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class Event(Base):
    __tablename__='events'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    exact_event_key: Mapped[str|None]=mapped_column(String(64),unique=True)
    revision: Mapped[int]=mapped_column(Integer,default=0)
    event_type: Mapped[str]=mapped_column(String(100),index=True)
    primary_actor: Mapped[str|None]=mapped_column(String(100),index=True)
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)
    updated_at: Mapped[datetime]=mapped_column(DT,default=utcnow,index=True)


class EventDocument(Base):
    __tablename__='event_documents'
    event_id: Mapped[str]=mapped_column(ForeignKey('events.id'),primary_key=True)
    document_id: Mapped[str]=mapped_column(ForeignKey('event_inputs.document_id'),primary_key=True)
    candidate_id: Mapped[str]=mapped_column(ForeignKey('event_candidates.id'))
    relation: Mapped[str]=mapped_column(String(16))
    evidence: Mapped[dict]=mapped_column(JSON)
    attached_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class EventRevision(Base):
    __tablename__='event_revisions'
    event_id: Mapped[str]=mapped_column(ForeignKey('events.id'),primary_key=True)
    revision: Mapped[int]=mapped_column(Integer,primary_key=True)
    message_id: Mapped[str]=mapped_column(String(36),unique=True)
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class CorrelationSuggestion(Base):
    __tablename__='correlation_suggestions'
    event_a: Mapped[str]=mapped_column(ForeignKey('events.id'),primary_key=True)
    event_b: Mapped[str]=mapped_column(ForeignKey('events.id'),primary_key=True)
    same_event_type: Mapped[bool]=mapped_column(Boolean)
    same_primary_actor: Mapped[bool]=mapped_column(Boolean)
    title_similarity: Mapped[float]=mapped_column(Float)
    time_distance_seconds: Mapped[float|None]=mapped_column(Float)
    time_distance_basis: Mapped[str]=mapped_column(String(32))
    suggestion_reason: Mapped[str]=mapped_column(String(100))
    policy_hash: Mapped[str]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DT,default=utcnow)


class OutboxEvent(Base):
    __tablename__='outbox_events'
    __table_args__=(UniqueConstraint('event_id','revision',name='uq_outbox_event_revision'),Index('ix_outbox_due','status','next_attempt_at','lease_until'))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    event_id: Mapped[str]=mapped_column(ForeignKey('events.id'))
    revision: Mapped[int]=mapped_column(Integer)
    message_id: Mapped[str]=mapped_column(String(36),unique=True)
    subject: Mapped[str]=mapped_column(String(100))
    payload: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(16),default='pending')
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_until: Mapped[datetime|None]=mapped_column(DT)
    lease_token: Mapped[str|None]=mapped_column(String(36))
    last_error: Mapped[str|None]=mapped_column(String(100))
    published_at: Mapped[datetime|None]=mapped_column(DT)

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String,Integer,DateTime,JSON,Text,ForeignKey,Index,UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME,LONGTEXT
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
TXT=Text().with_variant(LONGTEXT(),'mysql','mariadb')
def utcnow():return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id():return str(uuid4())
class Base(DeclarativeBase):pass
class Ruleset(Base):
    __tablename__='v2_rulesets'
    version:Mapped[str]=mapped_column(String(32),primary_key=True)
    configuration:Mapped[dict]=mapped_column(JSON)
    configuration_hash:Mapped[str]=mapped_column(String(64))
class ResearchInput(Base):
    __tablename__='v2_inputs'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    document_id:Mapped[str]=mapped_column(String(36),index=True)
    payload:Mapped[dict]=mapped_column(JSON)
    payload_hash:Mapped[str]=mapped_column(String(64))
    exact_payload:Mapped[str]=mapped_column(TXT)
    provenance:Mapped[dict]=mapped_column(JSON)
    received_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class ResearchRun(Base):
    __tablename__='v2_extraction_runs'
    __table_args__=(Index('ix_routing_due','status','next_attempt_at','lease_until'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    input_id:Mapped[str]=mapped_column(ForeignKey('v2_inputs.id'))
    ruleset_version:Mapped[str]=mapped_column(ForeignKey('v2_rulesets.version'))
    configuration:Mapped[dict]=mapped_column(JSON)
    snapshot:Mapped[dict|None]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    error:Mapped[str|None]=mapped_column(String(100))
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
class ResearchResult(Base):
    __tablename__='v2_results'
    id:Mapped[str]=mapped_column(ForeignKey('v2_extraction_runs.id'),primary_key=True)
    document_id:Mapped[str]=mapped_column(String(36),index=True)
    ruleset_version:Mapped[str]=mapped_column(String(32),index=True)
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class OutboxEvent(Base):
    __tablename__='outbox_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    research_id:Mapped[str]=mapped_column(ForeignKey('v2_results.id'),unique=True)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    subject:Mapped[str]=mapped_column(String(64),default='event.research.v2')
    payload:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
    last_error:Mapped[str|None]=mapped_column(String(100))
    published_at:Mapped[datetime|None]=mapped_column(DT)
class DeadInput(Base):
    __tablename__='dead_inputs'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    payload:Mapped[str]=mapped_column(TXT)
    reason:Mapped[str]=mapped_column(String(100))


class CandidateRecord(Base):
    __tablename__='v2_candidates'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    research_id:Mapped[str]=mapped_column(ForeignKey('v2_results.id'),index=True)
    event_type:Mapped[str]=mapped_column(String(100),index=True)
    payload:Mapped[dict]=mapped_column(JSON)
class ComparisonRecord(Base):
    __tablename__='v1_v2_comparisons'
    research_id:Mapped[str]=mapped_column(ForeignKey('v2_results.id'),primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)

# DI-4 tables never update DI-3 or production canonical history.
class CorrelationPolicy(Base):
    __tablename__ = 'correlation_policies'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    configuration: Mapped[dict] = mapped_column(JSON)
    configuration_hash: Mapped[str] = mapped_column(String(64))

class CorrelationCandidate(Base):
    __tablename__ = 'correlation_candidates'
    __table_args__ = (UniqueConstraint('policy_id', 'candidate_id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey('correlation_policies.id'), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36))
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[dict] = mapped_column(JSON)

class CorrelationEvent(Base):
    __tablename__ = 'correlation_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey('correlation_policies.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)

class CorrelationRevision(Base):
    __tablename__ = 'correlation_revisions'
    event_id: Mapped[str] = mapped_column(ForeignKey('correlation_events.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)

class CorrelationDecision(Base):
    __tablename__ = 'correlation_decisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey('correlation_policies.id'), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    candidate_a: Mapped[str] = mapped_column(String(36), index=True)
    candidate_b: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)

class CorrelationSuggestion(Base):
    __tablename__ = 'correlation_suggestions'
    decision_id: Mapped[str] = mapped_column(ForeignKey('correlation_decisions.id'), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)

class CorrelationProcessed(Base):
    __tablename__ = 'correlation_processed'
    policy_id: Mapped[str] = mapped_column(ForeignKey('correlation_policies.id'), primary_key=True)
    research_id: Mapped[str] = mapped_column(ForeignKey('v2_results.id'), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64))

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
    __tablename__='intelligence_rulesets'
    version:Mapped[str]=mapped_column(String(32),primary_key=True)
    configuration:Mapped[dict]=mapped_column(JSON)
    configuration_hash:Mapped[str]=mapped_column(String(64))
class IntelligenceInput(Base):
    __tablename__='intelligence_inputs'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    event_id:Mapped[str]=mapped_column(String(36),index=True)
    event_revision:Mapped[int]=mapped_column(Integer)
    payload:Mapped[dict]=mapped_column(JSON)
    payload_hash:Mapped[str]=mapped_column(String(64))
    exact_payload:Mapped[str]=mapped_column(TXT)
    provenance:Mapped[dict]=mapped_column(JSON)
    received_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class IntelligenceRun(Base):
    __tablename__='intelligence_runs'
    __table_args__=(UniqueConstraint('input_id','ruleset_version'),Index('ix_intelligence_due','status','next_attempt_at','lease_until'))
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    input_id:Mapped[str]=mapped_column(ForeignKey('intelligence_inputs.id'))
    ruleset_version:Mapped[str]=mapped_column(ForeignKey('intelligence_rulesets.version'))
    configuration:Mapped[dict]=mapped_column(JSON)
    snapshot:Mapped[dict|None]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    error:Mapped[str|None]=mapped_column(String(100))
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
class IntelligenceResult(Base):
    __tablename__='intelligence_results'
    id:Mapped[str]=mapped_column(ForeignKey('intelligence_runs.id'),primary_key=True)
    event_id:Mapped[str]=mapped_column(String(36),index=True)
    event_revision:Mapped[int]=mapped_column(Integer)
    ruleset_version:Mapped[str]=mapped_column(String(32),index=True)
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class OutboxEvent(Base):
    __tablename__='outbox_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    intelligence_id:Mapped[str]=mapped_column(ForeignKey('intelligence_results.id'),unique=True)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    subject:Mapped[str]=mapped_column(String(64),default='event.intelligence.v1')
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

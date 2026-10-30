from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import String,Integer,DateTime,JSON,Text,ForeignKey,Index
from sqlalchemy.dialects.mysql import DATETIME,LONGTEXT
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
TXT=Text().with_variant(LONGTEXT(),'mysql','mariadb')
def utcnow():return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id():return str(uuid4())
class Base(DeclarativeBase):pass
class AnalysisInput(Base):
    __tablename__='analysis_inputs'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    canonical_json:Mapped[str]=mapped_column(TXT)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class AnalysisJob(Base):
    __tablename__='analysis_jobs'
    __table_args__=(Index('ix_analysis_due','status','next_attempt_at','lease_until'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    event_id:Mapped[str]=mapped_column(String(36),index=True)
    event_revision:Mapped[int]=mapped_column(Integer)
    context_id:Mapped[str]=mapped_column(String(36))
    basis:Mapped[str]=mapped_column(String(32))
    run_key:Mapped[str]=mapped_column(String(64))
    configuration:Mapped[dict]=mapped_column(JSON)
    prompt_hash:Mapped[str]=mapped_column(String(64))
    input_id:Mapped[str|None]=mapped_column(ForeignKey('analysis_inputs.id'))
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    invalid_attempts:Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
    error:Mapped[str|None]=mapped_column(String(100))
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class AnalysisRun(Base):
    __tablename__='analysis_runs'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    analysis_id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id'),index=True)
    attempt:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(16),default='started')
    request:Mapped[dict]=mapped_column(JSON)
    response_audit:Mapped[dict|None]=mapped_column(JSON)
    error:Mapped[str|None]=mapped_column(String(100))
    started_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    finished_at:Mapped[datetime|None]=mapped_column(DT)
class AnalysisResult(Base):
    __tablename__='analysis_results'
    id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id'),primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class OutboxEvent(Base):
    __tablename__='outbox_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    analysis_id:Mapped[str]=mapped_column(ForeignKey('analysis_jobs.id'),unique=True)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    subject:Mapped[str]=mapped_column(String(64),default='analysis.completed.v1')
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

from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import String,Integer,DateTime,JSON,Text,ForeignKey,Index
from sqlalchemy.dialects.mysql import DATETIME,LONGTEXT
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb');TXT=Text().with_variant(LONGTEXT(),'mysql','mariadb')
def utcnow():return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id():return str(uuid4())
class Base(DeclarativeBase):pass
class Configuration(Base):
    __tablename__='intelligence_configurations'
    version:Mapped[str]=mapped_column(String(128),primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)
    content_hash:Mapped[str]=mapped_column(String(64))
class IntelligenceInput(Base):
    __tablename__='intelligence_inputs'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)
    payload_hash:Mapped[str]=mapped_column(String(64))
    exact_payload:Mapped[str]=mapped_column(TXT)
    provenance:Mapped[dict]=mapped_column(JSON)
    received_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class IntelligenceJob(Base):
    __tablename__='intelligence_jobs'
    __table_args__=(Index('ix_di_due','status','next_attempt_at','lease_until'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    input_id:Mapped[str]=mapped_column(ForeignKey('intelligence_inputs.id'),index=True)
    version:Mapped[str]=mapped_column(ForeignKey('intelligence_configurations.version'))
    configuration:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    error:Mapped[str|None]=mapped_column(String(100))
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
class IntelligenceRun(Base):
    __tablename__='intelligence_runs'
    id:Mapped[str]=mapped_column(ForeignKey('intelligence_jobs.id'),primary_key=True)
    status:Mapped[str]=mapped_column(String(16))
    payload:Mapped[dict|None]=mapped_column(JSON)
    completed_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class Extracted:
    run_id:Mapped[str]=mapped_column(ForeignKey('intelligence_runs.id'),primary_key=True)
    ordinal:Mapped[int]=mapped_column(Integer,primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)
class DocumentEntity(Extracted,Base):__tablename__='document_entities'
class DocumentMeasurement(Extracted,Base):__tablename__='document_measurements'
class DocumentDate(Extracted,Base):__tablename__='document_dates'
class DocumentRelation(Extracted,Base):__tablename__='document_relations'
class DocumentFact(Extracted,Base):__tablename__='document_facts'
class DocumentTopic(Extracted,Base):__tablename__='document_topics'
class OutboxEvent(Base):
    __tablename__='outbox_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    intelligence_id:Mapped[str]=mapped_column(ForeignKey('intelligence_runs.id'),unique=True)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    subject:Mapped[str]=mapped_column(String(64),default='document.intelligence.v1')
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

"""Independent market context schema; frozen migration metadata."""
from alembic import op
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import String,Integer,DateTime,JSON,LargeBinary,ForeignKey,UniqueConstraint,Index
from sqlalchemy.dialects.mysql import DATETIME,LONGBLOB
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
def utcnow():return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id():return str(uuid4())
class Base(DeclarativeBase):pass
class ContextInput(Base):
    __tablename__='context_inputs'
    __table_args__=(UniqueConstraint('event_id','event_revision','symbol',name='uq_context_input_identity'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    event_id:Mapped[str]=mapped_column(String(36))
    event_revision:Mapped[int]=mapped_column(Integer)
    symbol:Mapped[str]=mapped_column(String(16),default='BTCUSDT')
    input_message_id:Mapped[str]=mapped_column(String(36))
    exact_payload:Mapped[bytes]=mapped_column(LargeBinary().with_variant(LONGBLOB(),'mysql','mariadb'))
    payload:Mapped[dict]=mapped_column(JSON)
    subject:Mapped[str]=mapped_column(String(64))
    jetstream_metadata:Mapped[dict]=mapped_column(JSON)
    received_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class DeadInput(Base):
    __tablename__='dead_inputs'
    payload_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    exact_payload:Mapped[bytes]=mapped_column(LargeBinary().with_variant(LONGBLOB(),'mysql','mariadb'))
    reason:Mapped[str]=mapped_column(String(100))
    subject:Mapped[str]=mapped_column(String(64))
    received_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class MarketContext(Base):
    __tablename__='market_contexts'
    __table_args__=(UniqueConstraint('event_id','event_revision','symbol',name='uq_context_identity'),)
    id:Mapped[str]=mapped_column(ForeignKey('context_inputs.id'),primary_key=True)
    event_id:Mapped[str]=mapped_column(String(36),index=True)
    event_revision:Mapped[int]=mapped_column(Integer)
    symbol:Mapped[str]=mapped_column(String(16),default='BTCUSDT')
    revision:Mapped[int]=mapped_column(Integer)
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    updated_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class MarketContextPoint(Base):
    __tablename__='market_context_points'
    context_id:Mapped[str]=mapped_column(ForeignKey('market_contexts.id'),primary_key=True)
    offset_seconds:Mapped[int]=mapped_column(Integer,primary_key=True)
    payload:Mapped[dict]=mapped_column(JSON)
class ContextJob(Base):
    __tablename__='context_jobs'
    __table_args__=(Index('ix_context_job_due','status','next_attempt_at','lease_until'),)
    id:Mapped[str]=mapped_column(ForeignKey('context_inputs.id'),primary_key=True)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DT)
    last_error:Mapped[str|None]=mapped_column(String(100))
class ContextRevision(Base):
    __tablename__='context_revisions'
    context_id:Mapped[str]=mapped_column(ForeignKey('market_contexts.id'),primary_key=True)
    revision:Mapped[int]=mapped_column(Integer,primary_key=True)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
class OutboxEvent(Base):
    __tablename__='outbox_events'
    __table_args__=(UniqueConstraint('context_id','revision',name='uq_outbox_context_revision'),Index('ix_outbox_due','status','next_attempt_at','lease_until'))
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    context_id:Mapped[str]=mapped_column(ForeignKey('market_contexts.id'))
    revision:Mapped[int]=mapped_column(Integer)
    message_id:Mapped[str]=mapped_column(String(36),unique=True)
    subject:Mapped[str]=mapped_column(String(64))
    payload:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(16),default='pending')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at:Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_until:Mapped[datetime|None]=mapped_column(DT)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    last_error:Mapped[str|None]=mapped_column(String(100))
    published_at:Mapped[datetime|None]=mapped_column(DT)

revision='c35001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():Base.metadata.create_all(op.get_bind(),checkfirst=False)
def downgrade():Base.metadata.drop_all(op.get_bind(),checkfirst=False)

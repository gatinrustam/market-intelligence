"""Initial independent market data schema; frozen migration metadata."""
from alembic import op
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Integer, BigInteger, DateTime, JSON, Numeric, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
def new_id(): return str(uuid4())
DT=DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb')
class Base(DeclarativeBase): pass

class Snapshot(Base):
    __tablename__='market_snapshots_1s'
    __table_args__=(UniqueConstraint('provider','symbol','slot',name='uq_snapshot_slot'),Index('ix_snapshot_time','provider','symbol','observed_at'))
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    provider: Mapped[str]=mapped_column(String(32),default='binance_spot')
    symbol: Mapped[str]=mapped_column(String(20),default='BTCUSDT')
    slot: Mapped[int]=mapped_column(BigInteger)
    observed_at: Mapped[datetime]=mapped_column(DT)
    exchange_event_at: Mapped[datetime]=mapped_column(DT)
    # Exact decimal strings in immutable JSON, never JSON floating-point numbers.
    payload: Mapped[dict]=mapped_column(JSON)

class MarketCandle(Base):
    __tablename__='market_candles'
    provider: Mapped[str]=mapped_column(String(32),primary_key=True,default='binance_spot')
    symbol: Mapped[str]=mapped_column(String(20),primary_key=True,default='BTCUSDT')
    interval: Mapped[str]=mapped_column(String(8),primary_key=True,default='1m')
    open_time: Mapped[datetime]=mapped_column(DT,primary_key=True)
    close_time: Mapped[datetime]=mapped_column(DT)
    open: Mapped[object]=mapped_column(Numeric(38,18))
    high: Mapped[object]=mapped_column(Numeric(38,18))
    low: Mapped[object]=mapped_column(Numeric(38,18))
    close: Mapped[object]=mapped_column(Numeric(38,18))
    base_volume: Mapped[object]=mapped_column(Numeric(38,18))
    quote_volume: Mapped[object]=mapped_column(Numeric(38,18))
    trade_count: Mapped[int]=mapped_column(BigInteger)
    taker_buy_base_volume: Mapped[object]=mapped_column(Numeric(38,18))
    taker_buy_quote_volume: Mapped[object]=mapped_column(Numeric(38,18))
    source: Mapped[str]=mapped_column(String(16))
    collected_at: Mapped[datetime]=mapped_column(DT,default=utcnow)

class BackfillJob(Base):
    __tablename__='backfill_jobs'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    provider: Mapped[str]=mapped_column(String(32),default='binance_spot')
    symbol: Mapped[str]=mapped_column(String(20),default='BTCUSDT')
    interval: Mapped[str]=mapped_column(String(8),default='1m')
    start_at: Mapped[datetime]=mapped_column(DT)
    end_at: Mapped[datetime]=mapped_column(DT)
    cursor_at: Mapped[datetime]=mapped_column(DT)
    status: Mapped[str]=mapped_column(String(16),default='pending')
    pages: Mapped[int]=mapped_column(Integer,default=0)
    candles_seen: Mapped[int]=mapped_column(Integer,default=0)
    lease_token: Mapped[str|None]=mapped_column(String(36))
    lease_until: Mapped[datetime|None]=mapped_column(DT)
    last_error: Mapped[str|None]=mapped_column(String(100))
    updated_at: Mapped[datetime]=mapped_column(DT,default=utcnow)

class OutboxEvent(Base):
    __tablename__='outbox_events'
    __table_args__=(Index('ix_outbox_due','status','next_attempt_at','lease_until'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=new_id)
    message_id: Mapped[str]=mapped_column(String(36),unique=True)
    payload: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(16),default='pending')
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime]=mapped_column(DT,default=utcnow)
    lease_until: Mapped[datetime|None]=mapped_column(DT)
    lease_token: Mapped[str|None]=mapped_column(String(36))
    last_error: Mapped[str|None]=mapped_column(String(100))
    published_at: Mapped[datetime|None]=mapped_column(DT)

revision='m30001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade(): Base.metadata.create_all(op.get_bind(),checkfirst=False)
def downgrade(): Base.metadata.drop_all(op.get_bind(),checkfirst=False)

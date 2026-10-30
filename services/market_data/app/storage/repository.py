from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.domain import Candle, iso
from app.storage.models import Snapshot, MarketCandle, OutboxEvent, BackfillJob, CollectionCheckpoint
from app.logging import log

UTC=timezone.utc
def naive(t): return t.astimezone(UTC).replace(tzinfo=None)
def aware(t): return t.replace(tzinfo=UTC)
def parse(t): return datetime.fromisoformat(t.replace('Z','+00:00'))
def candle_payload(row):
    return Candle(**{k:aware(getattr(row,k)) if k.endswith('_time') else getattr(row,k) for k in Candle.__dataclass_fields__}).payload()

def insert_candle(session,candle,source):
    key=('binance_spot','BTCUSDT','1m',naive(candle.open_time))
    old=session.get(MarketCandle,key)
    if old:
        if any(getattr(old,k)!=(naive(v) if isinstance(v,datetime) else v) for k,v in vars(candle).items()):
            raise ValueError('conflicting canonical candle')
        return False
    values={k:naive(v) if isinstance(v,datetime) else v for k,v in vars(candle).items()}
    # A savepoint contains concurrent WS/REST duplicate insertion without losing a page.
    try:
        with session.begin_nested():
            session.add(MarketCandle(**values,source=source)); session.flush()
    except IntegrityError:
        old=session.get(MarketCandle,key)
        if old is None: raise
        if any(getattr(old,k)!=v for k,v in values.items()): raise ValueError('conflicting canonical candle')
        return False
    return True

class Repository:
    def __init__(self,sessions,contract,interval=1): self.sessions=sessions; self.contract=contract; self.interval=interval
    def save_snapshot(self,payload):
        self.contract.validate(payload)
        observed=parse(payload['timestamps']['observed_at'])
        slot=int(Decimal(str(observed.timestamp()))/Decimal(str(self.interval)))
        try:
            with self.sessions.begin() as session:
                previous=session.scalar(select(Snapshot.observed_at).order_by(Snapshot.observed_at.desc()).limit(1))
                session.add(Snapshot(id=payload['message_id'],slot=slot,observed_at=naive(observed),exchange_event_at=naive(parse(payload['timestamps']['exchange_event_at'])),payload=payload))
                session.add(OutboxEvent(message_id=payload['message_id'],payload=payload))
                session.flush()
            if previous and (naive(observed)-previous).total_seconds()>self.interval*2:
                log('snapshot_gap',previous_observed_at=iso(aware(previous)),observed_at=iso(observed),gap_seconds=(naive(observed)-previous).total_seconds())
            return True
        except IntegrityError:
            with self.sessions() as session:
                if session.scalar(select(Snapshot.id).where(Snapshot.provider=='binance_spot',Snapshot.symbol=='BTCUSDT',Snapshot.slot==slot)): return False
            raise
    def save_candle(self,candle,source='websocket'):
        with self.sessions.begin() as s: return insert_candle(s,candle,source)
    def lookup(self,at,tolerance,mode="nearest",known_at=None):
        if mode not in ("nearest","causal"):raise ValueError("unsupported lookup mode")
        if known_at is not None and (mode!='causal' or at>known_at):raise ValueError('known_at requires causal mode and target <= known_at')
        target=naive(at)
        with self.sessions() as s:
            first=s.scalar(select(func.min(Snapshot.observed_at)))
            realtime={'available':False,'reason':'not_collected'}
            if first is not None and target>=first:
                filters=(Snapshot.provider=='binance_spot',Snapshot.symbol=='BTCUSDT')
                before=s.scalar(select(Snapshot).where(*filters,Snapshot.observed_at<=target).order_by(Snapshot.observed_at.desc()).limit(1))
                after=None if mode=='causal' else s.scalar(select(Snapshot).where(*filters,Snapshot.observed_at>=target).order_by(Snapshot.observed_at).limit(1))
                row=min([r for r in (before,after) if r],key=lambda r:(abs((r.observed_at-target).total_seconds()),r.observed_at))
                delta=abs(row.observed_at-target); ms=(delta.days*86400000000+delta.seconds*1000000+delta.microseconds)/1000
                if ms<=tolerance*1000:
                    p=row.payload
                    realtime={'available':True,'observed_at':p['timestamps']['observed_at'],'distance_ms':ms,
                        'last_trade_price':p['price']['last'],'best_bid':p['price']['bid'],'best_ask':p['price']['ask'],
                        'mid_price':p['price']['mid'],'spread_absolute':p['spread']['absolute'],'spread_bps':p['spread']['bps'],
                        'snapshot':p}
                else: realtime={'available':False,'reason':'no_snapshot_within_tolerance'}
            if mode=='causal':
                bar=s.scalar(select(MarketCandle).where(MarketCandle.provider=='binance_spot',MarketCandle.symbol=='BTCUSDT',MarketCandle.interval=='1m',MarketCandle.open_time<=target,MarketCandle.close_time<=target,*( [MarketCandle.collected_at<=naive(known_at)] if known_at is not None else [])).order_by(MarketCandle.open_time.desc()).limit(1))
            else:
                bar=s.get(MarketCandle,('binance_spot','BTCUSDT','1m',target.replace(second=0,microsecond=0)))
            return {'provider':'binance_spot','symbol':'BTCUSDT','requested_at':iso(at),'realtime':realtime,
                    'candle_1m':{'available':True,**candle_payload(bar)} if bar else {'available':False,'reason':'not_collected'}}
    def candles(self,start,end,limit):
        with self.sessions() as s:
            rows=s.scalars(select(MarketCandle).where(MarketCandle.provider=='binance_spot',MarketCandle.symbol=='BTCUSDT',MarketCandle.interval=='1m',MarketCandle.open_time>=naive(start),MarketCandle.open_time<naive(end)).order_by(MarketCandle.open_time).limit(limit+1)).all()
            return {'provider':'binance_spot','symbol':'BTCUSDT','interval':'1m','candles':[candle_payload(r) for r in rows[:limit]],'next_from':iso(aware(rows[limit].open_time)) if len(rows)>limit else None}
    def stats(self):
        with self.sessions() as s:
            snap=s.scalar(select(func.max(Snapshot.observed_at))); bar=s.scalar(select(func.max(MarketCandle.close_time)))
            jobs=s.scalars(select(BackfillJob).order_by(BackfillJob.updated_at.desc()).limit(10)).all()
            return {'last_snapshot_at':iso(aware(snap)) if snap else None,'last_candle_at':iso(aware(bar)) if bar else None,
                'snapshots_total':s.scalar(select(func.count()).select_from(Snapshot)),
                'candles_total':s.scalar(select(func.count()).select_from(MarketCandle)),
                'outbox_pending':s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status=='pending')),
                'outbox_dead':s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status=='dead')),
                'backfill_status':[{'id':j.id,'status':j.status,'cursor_at':iso(aware(j.cursor_at)),'pages':j.pages,'candles_seen':j.candles_seen,'last_error':j.last_error} for j in jobs]}

    def repair_cursor(self,default):
        with self.sessions.begin() as s:
            row=s.get(CollectionCheckpoint,'candle_repair')
            if row is None:
                first=s.scalar(select(func.min(Snapshot.observed_at)))
                cursor=min(naive(default),first.replace(second=0,microsecond=0)) if first else naive(default)
                row=CollectionCheckpoint(name='candle_repair',cursor_at=cursor);s.add(row)
            return aware(row.cursor_at)
    def advance_repair_cursor(self,cursor):
        with self.sessions.begin() as s:
            row=s.scalar(select(CollectionCheckpoint).where(CollectionCheckpoint.name=='candle_repair').with_for_update())
            if row.cursor_at<naive(cursor): row.cursor_at=naive(cursor)

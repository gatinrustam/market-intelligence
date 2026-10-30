from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from uuid import uuid4

UTC = timezone.utc

def now(): return datetime.now(UTC)
def iso(t): return t.astimezone(UTC).isoformat().replace('+00:00','Z')
def epoch(ms): return datetime.fromtimestamp(int(ms)//1000, UTC).replace(microsecond=int(ms)%1000*1000)
def decimal(value):
    if not isinstance(value, str): raise ValueError('decimal must be a string')
    d=Decimal(value)
    if not d.is_finite() or d < 0 or d.adjusted() > 19 or d.as_tuple().exponent < -18:
        raise ValueError('invalid decimal')
    return d

def fmt(d): return format(d,'f')

@dataclass(frozen=True)
class Trade:
    sequence: int
    price: Decimal
    exchange_at: datetime
    received_at: datetime

@dataclass(frozen=True)
class Book:
    sequence: int
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    received_at: datetime

@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    trade_count: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal
    def payload(self):
        return {k:iso(v) if isinstance(v,datetime) else fmt(v) if isinstance(v,Decimal) else v for k,v in vars(self).items()}

class MarketState:
    def __init__(self):
        self.trade=None; self.book=None; self.connected=False
        self.reconnect_count=0; self.last_market_event_at=None; self.latency=None
        self.latency_total=Decimal(0); self.latency_count=0
        self.trade_updates=0; self.book_updates=0
    def reset(self):
        self.connected=False; self.trade=None; self.book=None
    def apply(self, event):
        name='trade' if isinstance(event,Trade) else 'book'
        previous=getattr(self,name)
        if previous and event.sequence <= previous.sequence: return False
        setattr(self,name,event); self.last_market_event_at=event.received_at
        if isinstance(event,Trade):
            self.trade_updates+=1
            delta=event.received_at-event.exchange_at
            self.latency=Decimal(delta.days*86400000000+delta.seconds*1000000+delta.microseconds)/1000
            self.latency_total+=self.latency; self.latency_count+=1
        else: self.book_updates+=1
        return True
    def snapshot(self, observed, max_age=10):
        t,b=self.trade,self.book
        if not self.connected or t is None or b is None: return None
        if any(not 0 <= (observed-e.received_at).total_seconds() <= max_age for e in (t,b)): return None
        with localcontext() as ctx:
            ctx.prec=60
            mid=(b.bid+b.ask)/2; spread=b.ask-b.bid
            bps=(spread/mid*10000).quantize(Decimal('0.000000000000000001'),rounding=ROUND_HALF_EVEN)
        return {'schema_version':'1.0','message_id':str(uuid4()),'provider':'binance_spot','symbol':'BTCUSDT',
                'timestamps':{'observed_at':iso(observed),'exchange_event_at':iso(t.exchange_at),
                    'trade_received_at':iso(t.received_at),'book_received_at':iso(b.received_at)},
                'price':{'last':fmt(t.price),'bid':fmt(b.bid),'ask':fmt(b.ask),'mid':fmt(mid)},
                'spread':{'absolute':fmt(spread),'bps':fmt(bps)},
                'quantity':{'bid':fmt(b.bid_qty),'ask':fmt(b.ask_qty)},
                'sequence':{'trade':t.sequence,'book':b.sequence},
                'exchange_event_basis':'last_trade','ingestion_latency_ms':fmt(self.latency)}

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.config import Settings
from app.contract import Contract
from app.domain import MarketState, Candle, now, iso, fmt
from app.provider import BinanceSpotProvider
from app.backfill import Backfill
from app.storage.database import make_database
from app.storage.repository import Repository, parse
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.logging import configure_logging, log

class Collector:
    def __init__(self,state,provider,repo,settings):
        self.state=state; self.provider=provider; self.repo=repo; self.settings=settings
        self.candles=asyncio.Queue(maxsize=120)
        self.gap_started=None
    async def receive(self):
        async for event in self.provider.events():
            if isinstance(event,Candle):
                self.state.last_market_event_at=now()
                try: self.candles.put_nowait(event)
                except asyncio.QueueFull: log('candle_queue_overflow',open_time=iso(event.open_time))
            else: self.state.apply(event)
    async def sample_once(self):
        p=self.state.snapshot(now(),self.settings.max_state_age_seconds)
        if p:
            saved=await asyncio.to_thread(self.repo.save_snapshot,p)
            if self.gap_started:
                log('snapshot_sampling_resumed',gap_started_at=iso(self.gap_started),observed_at=p['timestamps']['observed_at'])
                self.gap_started=None
            return saved
        if self.gap_started is None:
            self.gap_started=now()
            log('snapshot_sampling_unavailable',reason='disconnected_or_stale_state',since=iso(self.gap_started))
        return False
    async def sample(self):
        while True:
            await asyncio.sleep(self.settings.snapshot_interval_seconds)
            try: await self.sample_once()
            except Exception as exc: log('snapshot_write_failed',error_type=type(exc).__name__)
    async def store_candles(self):
        while True:
            candle=await self.candles.get()
            while True:
                try:
                    await asyncio.to_thread(self.repo.save_candle,candle)
                    break
                except ValueError as exc:
                    log('candle_conflict',open_time=iso(candle.open_time),error_type=type(exc).__name__); break
                except Exception as exc:
                    log('candle_write_retry',error_type=type(exc).__name__); await asyncio.sleep(5)
            self.candles.task_done()

@asynccontextmanager
async def lifespan(app):
    configure_logging(); settings=Settings(); engine,sessions=make_database(settings.database_url.get_secret_value())
    state=MarketState(); contract=Contract(settings.contract_path); repo=Repository(sessions,contract,settings.snapshot_interval_seconds)
    provider=BinanceSpotProvider(state,settings.rest_interval_seconds); bus=JetStreamBus(settings.nats_url)
    publisher=OutboxPublisher(sessions,bus,contract); collector=Collector(state,provider,repo,settings)
    async def publish():
        while True:
            try:
                if not await publisher.run_once(): await asyncio.sleep(.2)
            except Exception as exc: log('publisher_retry',error_type=type(exc).__name__); await asyncio.sleep(2)
    async def repair():
        # Startup/reconnect recovery uses persisted candle checkpoint, bounded to one day per pass.
        while True:
            try:
                end=now().replace(second=0,microsecond=0)
                start=await asyncio.to_thread(repo.repair_cursor,end-timedelta(minutes=2))
                if start<end:
                    until=min(end,start+timedelta(days=1))
                    await Backfill(sessions,provider).run(start,until)
                    await asyncio.to_thread(repo.advance_repair_cursor,until)
            except Exception as exc: log('candle_repair_retry',error_type=type(exc).__name__)
            await asyncio.sleep(60)
    tasks=[asyncio.create_task(fn(),name=name) for name,fn in [('receiver',collector.receive),('sampler',collector.sample),('candles',collector.store_candles),('publisher',publish),('repair',repair)]]
    app.state.context=(settings,engine,repo,state,bus,tasks)
    try: yield
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True); await bus.close(); engine.dispose()

app=FastAPI(title='Market Data Service',lifespan=lifespan)
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/ready')
async def ready():
    settings,engine,repo,state,bus,tasks=app.state.context
    def database():
        with engine.connect() as c: return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='m30002'
    try: db=await asyncio.to_thread(database)
    except Exception: db=False
    checks={'database':db,'nats':await bus.healthcheck(),'workers':all(not t.done() for t in tasks)}
    return JSONResponse({'ready':all(checks.values()),'checks':checks},status_code=200 if all(checks.values()) else 503)
@app.get('/stats')
async def stats():
    _,_,repo,state,_,_=app.state.context
    return {**await asyncio.to_thread(repo.stats),'provider_connected':state.connected,
            'last_market_event_at':iso(state.last_market_event_at) if state.last_market_event_at else None,
            'reconnect_count':state.reconnect_count,'current_ingestion_latency_ms':fmt(state.latency) if state.latency is not None else None,
            'average_ingestion_latency_ms':fmt(state.latency_total/state.latency_count) if state.latency_count else None,
            'trade_updates':state.trade_updates,'book_updates':state.book_updates}

def utc_time(t):
    if t.tzinfo is None: raise HTTPException(422,'timestamp must include timezone')
    return t
@app.get('/market/snapshot')
async def snapshot(at:datetime,symbol:Literal['BTCUSDT']='BTCUSDT',mode:Literal['nearest','causal']='nearest',known_at:datetime|None=None):
    settings,_,repo,_,_,_=app.state.context
    if known_at is not None:
        utc_time(known_at)
        if mode!='causal' or utc_time(at)>known_at:raise HTTPException(422,'known_at requires causal mode and at <= known_at')
    return await asyncio.to_thread(repo.lookup,utc_time(at),settings.max_snapshot_distance_seconds,mode,known_at)
@app.get('/market/candles')
async def candles(start:datetime=Query(alias='from'),end:datetime=Query(alias='to'),symbol:Literal['BTCUSDT']='BTCUSDT',interval:Literal['1m']='1m',limit:int=Query(1000,ge=1,le=1000)):
    utc_time(start); utc_time(end)
    if start>=end: raise HTTPException(422,'from must precede to')
    return await asyncio.to_thread(app.state.context[2].candles,start,end,limit)

import asyncio
import copy
import json
import os
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import AsyncMock
import httpx
import pytest
from jsonschema.exceptions import ValidationError
from sqlalchemy import select,func
from app.domain import MarketState,Trade,Book,now
from app.provider import normalize,candle,BinanceSpotProvider,retry_delay
from app.storage.models import Snapshot,OutboxEvent,MarketCandle,BackfillJob,utcnow
from app.storage.repository import naive
from app.backfill import Backfill,timestamp
from app.publishers.outbox import OutboxPublisher
from app.publishers.nats import JetStreamBus
from app.config import Settings
from app.main import Collector,app

T=datetime(2026,4,1,tzinfo=timezone.utc)
def state(t=T):
    s=MarketState();s.connected=True
    s.apply(Trade(42,Decimal('70000.12345678'),t-timedelta(milliseconds=25),t))
    s.apply(Book(99,Decimal('70000.10'),Decimal('70000.12'),Decimal('1.00000001'),Decimal('2.3'),t))
    return s

def bar(t=T):
    ms=int(t.timestamp()*1000)
    return candle([ms,'70000.1','70002','69999','70001','1.2',ms+59999,'84000.12',10,'0.7','49000.07'])

def test_normalize_trade():
    event=normalize({'stream':'btcusdt@aggTrade','data':{'e':'aggTrade','s':'BTCUSDT','a':123,'p':'70000.12345678','E':int(T.timestamp()*1000)}},T)
    assert event.price==Decimal('70000.12345678') and event.sequence==123 and event.exchange_at==T

def test_book_has_no_exchange_timestamp():
    b=normalize({'u':19,'s':'BTCUSDT','b':'70000.01','B':'0.00000001','a':'70000.02','A':'3'},T)
    assert b.bid_qty==Decimal('0.00000001') and b.received_at==T and not hasattr(b,'exchange_at')

@pytest.mark.parametrize('value',[1.25,'NaN','Infinity','-1','0.0000000000000000001'])
def test_reject_bad_decimal(value):
    from app.domain import decimal
    with pytest.raises((ValueError,TypeError)): decimal(value)

@pytest.mark.parametrize('kind',['open','wrong_interval','wrong_symbol','closed'])
def test_kline_normalization(kind):
    k={'i':'1m','s':'BTCUSDT','x':kind!='open','t':int(T.timestamp()*1000),'T':int(T.timestamp()*1000)+59999,'o':'2','h':'3','l':'1','c':'2.5','v':'10','q':'25','n':4,'V':'5','Q':'12'}
    if kind=='wrong_interval': k['i']='5m'
    if kind=='wrong_symbol': k['s']='ETHUSDT'
    if kind.startswith('wrong'):
        with pytest.raises(ValueError): normalize({'e':'kline','s':'BTCUSDT','k':k},T)
    else: assert (normalize({'e':'kline','s':'BTCUSDT','k':k},T) is not None)==(kind=='closed')

def test_decimal_mid_spread_latency(contract):
    p=state().snapshot(T);contract.validate(p)
    assert p['price']['mid']=='70000.11'
    assert p['spread']['absolute']=='0.02'
    assert p['spread']['bps']==str((Decimal('0.02')/Decimal('70000.11')*10000).quantize(Decimal('0.000000000000000001')))
    assert p['ingestion_latency_ms']=='25'

@pytest.mark.parametrize('mutation',[lambda p:p.update(extra=True),lambda p:p['price'].update(bid=1.0),lambda p:p['price'].update(extra='1'),lambda p:p.update(symbol='ETHUSDT'),lambda p:p.update(message_id='bad'),lambda p:p['timestamps'].update(observed_at='yesterday'),lambda p:p.pop('sequence')])
def test_strict_contract(contract,mutation):
    p=state().snapshot(T); mutation(p)
    with pytest.raises(ValidationError): contract.validate(p)

def test_duplicate_out_of_order_and_stale_state():
    s=state(); assert not s.apply(Trade(42,Decimal('1'),T,T)); assert not s.apply(Book(98,Decimal('1'),Decimal('2'),Decimal('3'),Decimal('4'),T))
    assert s.snapshot(T)['price']['last']=='70000.12345678'
    assert s.snapshot(T+timedelta(seconds=11)) is None
    s.reset(); assert s.snapshot(T) is None

@pytest.mark.parametrize('count',[1,5])
def test_snapshot_atomic_and_slot_dedup(repo,sessions,count):
    for i in range(count):
        t=T+timedelta(seconds=i)
        assert repo.save_snapshot(state(t).snapshot(t))
        assert not repo.save_snapshot(state(t).snapshot(t+timedelta(milliseconds=100)))
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Snapshot))==count
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==count
        assert s.scalar(select(Snapshot)).payload['price']['last']=='70000.12345678'

def test_atomic_rollback(repo,sessions):
    p=state().snapshot(T)
    with sessions.begin() as s: s.add(OutboxEvent(message_id=p['message_id'],payload=p))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError): repo.save_snapshot(p)
    with sessions() as s: assert s.scalar(select(func.count()).select_from(Snapshot))==0

def test_candle_dedup_immutable(repo,sessions):
    assert repo.save_candle(bar()); assert not repo.save_candle(bar(),'rest')
    from dataclasses import replace
    with pytest.raises(ValueError): repo.save_candle(replace(bar(),close=Decimal('70001.5')))
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MarketCandle))==1
        assert s.scalar(select(MarketCandle)).close==Decimal('70001')

def test_lookup_nearest_tie_tolerance_historical(repo):
    for i in (0,2,20):
        t=T+timedelta(seconds=i);repo.save_snapshot(state(t).snapshot(t))
    assert repo.lookup(T+timedelta(seconds=1),3)['realtime']['observed_at'].startswith('2026-04-01T00:00:00')
    assert repo.lookup(T+timedelta(seconds=1.8),3)['realtime']['distance_ms']==200
    assert repo.lookup(T+timedelta(seconds=5),3)['realtime']['available']
    assert repo.lookup(T+timedelta(seconds=5,microseconds=1),3)['realtime']['reason']=='no_snapshot_within_tolerance'
    old=T-timedelta(minutes=1);repo.save_candle(bar(old),'rest')
    result=repo.lookup(old+timedelta(seconds=30),3)
    assert result['realtime']=={'available':False,'reason':'not_collected'}
    assert result['candle_1m']['available'] and 'best_bid' not in result['candle_1m']
    assert repo.lookup(T-timedelta(microseconds=1),3)['realtime']['reason']=='not_collected'

def test_candle_api_pagination(repo):
    for i in range(3):repo.save_candle(bar(T+timedelta(minutes=i)))
    first=repo.candles(T,T+timedelta(minutes=3),2)
    assert len(first['candles'])==2 and first['next_from']=='2026-04-01T00:02:00Z'

async def test_sampler(repo,sessions,monkeypatch):
    monkeypatch.setattr("app.main.now",lambda:T)
    s=state(T); c=Collector(s,None,repo,Settings())
    assert await c.sample_once()
    assert not await c.sample_once()
    s.reset(); assert not await c.sample_once()

class FakeProvider:
    def __init__(self,fail_at=None): self.calls=[];self.fail_at=fail_at
    async def klines(self,start,end,limit=1000):
        self.calls.append((start,end,limit))
        if self.fail_at==len(self.calls): raise ConnectionError('fixture outage')
        return [bar(datetime.fromtimestamp(ms/1000,timezone.utc)) for ms in range(start,end,60000)]

async def test_backfill_pagination_resume_idempotency(sessions):
    provider=FakeProvider(fail_at=2); importer=Backfill(sessions,provider);end=T+timedelta(minutes=1003)
    with pytest.raises(ConnectionError): await importer.run(T,end)
    with sessions() as s:
        job=s.scalar(select(BackfillJob));assert job.pages==1 and job.cursor_at==naive(T+timedelta(minutes=1000))
        assert s.scalar(select(func.count()).select_from(MarketCandle))==1000
    restarted=FakeProvider(); key=await Backfill(sessions,restarted).run(T,end)
    assert len(restarted.calls)==1 and restarted.calls[0][0]==int((T+timedelta(minutes=1000)).timestamp()*1000)
    await Backfill(sessions,restarted).run(T,end); assert len(restarted.calls)==1
    with sessions() as s:
        assert s.get(BackfillJob,key).status=='completed'
        assert s.scalar(select(func.count()).select_from(MarketCandle))==1003

async def test_incomplete_backfill_preserves_cursor(sessions):
    provider=FakeProvider();provider.klines=AsyncMock(return_value=[])
    with pytest.raises(ValueError): await Backfill(sessions,provider).run(T,T+timedelta(minutes=1))
    with sessions() as s:
        job=s.scalar(select(BackfillJob));assert job.cursor_at==naive(T) and job.status=='pending'

async def test_backfill_lease_restart(sessions):
    b=Backfill(sessions,FakeProvider());end=T+timedelta(minutes=1);job,token=b.claim(T,end)
    with pytest.raises(RuntimeError):b.claim(T,end)
    with sessions.begin() as s:s.get(BackfillJob,job.id).lease_until=utcnow()-timedelta(seconds=1)
    replacement,new_token=b.claim(T,end);assert token!=new_token
    with pytest.raises(RuntimeError):b.commit_page(job.id,token,[bar()],end,end)
    b.commit_page(job.id,new_token,[bar()],end,end)

async def test_outbox_failure_collection_and_restart(repo,sessions,contract):
    p=state().snapshot(T);repo.save_snapshot(p)
    fail=AsyncMock();fail.publish.side_effect=ConnectionError('offline')
    worker=OutboxPublisher(sessions,fail,contract); assert await worker.run_once()
    repo.save_snapshot(state(T+timedelta(seconds=1)).snapshot(T+timedelta(seconds=1)))
    with sessions.begin() as s:
        rows=s.scalars(select(OutboxEvent)).all();assert len(rows)==2 and all(r.status=='pending' for r in rows)
        for r in rows:r.next_attempt_at=utcnow()
    ok=AsyncMock();restarted=OutboxPublisher(sessions,ok,contract)
    assert await restarted.run_once();assert await restarted.run_once()
    with sessions() as s: assert all(r.status=='published' for r in s.scalars(select(OutboxEvent)))
    assert {call.args[0] for call in ok.publish.call_args_list}=={r.message_id for r in rows}

async def test_abandoned_outbox_claim_recovered(repo,sessions,contract):
    repo.save_snapshot(state().snapshot(T));bus=AsyncMock();worker=OutboxPublisher(sessions,bus,contract)
    row=worker.claim();assert worker.claim() is None
    with sessions.begin() as s:s.get(OutboxEvent,row.id).lease_until=utcnow()-timedelta(seconds=1)
    restarted=OutboxPublisher(sessions,bus,contract);assert await restarted.run_once()
    worker.finish(row,error='late old worker')
    with sessions() as s: assert s.get(OutboxEvent,row.id).status=='published'

async def test_real_jetstream_dedup(repo,sessions,contract):
    url=os.environ['TEST_NATS_URL'];assert 'nats-test' in url
    bus=JetStreamBus(url);await bus.connect();await bus.js.purge_stream('MARKET_SNAPSHOTS')
    try:
        p=state().snapshot(T);repo.save_snapshot(p);worker=OutboxPublisher(sessions,bus,contract)
        assert await worker.run_once();await bus.publish(p['message_id'],p)
        info=await bus.js.stream_info('MARKET_SNAPSHOTS');assert info.state.messages==1
        raw=await bus.js.get_msg('MARKET_SNAPSHOTS',seq=info.state.last_seq)
        assert json.loads(raw.data)==p
    finally:await bus.close()

async def test_reconnect_and_refresh(monkeypatch):
    s=state();connections=[];delays=[]
    class WS:
        async def __aenter__(self): connections.append(1);return self
        async def __aexit__(self,*args):pass
        def __aiter__(self):return self
        async def __anext__(self):
            if len(connections)==1:raise ConnectionError('fixture disconnect')
            return json.dumps({'e':'aggTrade','s':'BTCUSDT','a':200,'p':'70001','E':int(T.timestamp()*1000)})
    async def sleep(delay):delays.append(delay)
    monkeypatch.setattr('app.provider.asyncio.sleep',sleep)
    provider=BinanceSpotProvider(s,connector=lambda *a,**k:WS());events=provider.events()
    event=await anext(events);assert s.reconnect_count==1 and len(connections)==2 and s.connected
    assert s.book is None and s.trade is None and 1<=delays[0]<2
    s.apply(event);assert s.snapshot(now()) is None
    await events.aclose();assert not s.connected

def test_reconnect_delay_bounded():
    assert 1<=retry_delay(0)<2;assert 60<=retry_delay(99)<61

@pytest.mark.parametrize('value',['2026-04-01','2026-04-01T04:00:00+04:00','2026-04-01T00:00:00Z'])
def test_backfill_timestamp(value):assert timestamp(value)==T

def test_reject_naive_timestamp():
    with pytest.raises(ValueError):timestamp('2026-04-01T00:00:00')

async def test_api_availability_validation(repo):
    app.state.context=(Settings(),None,repo,state(),None,[])
    repo.save_candle(bar(),'rest')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        r=await client.get('/market/snapshot',params={'at':T.isoformat()})
        assert r.status_code==200 and r.json()['candle_1m']['available'] and not r.json()['realtime']['available']
        for params in ({'at':'2026-04-01T00:00:00'},{'at':T.isoformat(),'symbol':'ETHUSDT'}):
            assert (await client.get('/market/snapshot',params=params)).status_code==422
        assert (await client.get('/market/candles',params={'from':T.isoformat(),'to':(T+timedelta(minutes=1)).isoformat()})).json()['candles']

def test_repair_checkpoint_does_not_skip_hole(repo):
    assert repo.repair_cursor(T)==T
    repo.save_candle(bar(T+timedelta(minutes=20)))
    assert repo.repair_cursor(T+timedelta(minutes=30))==T
    repo.advance_repair_cursor(T+timedelta(minutes=5))
    assert repo.repair_cursor(T+timedelta(minutes=30))==T+timedelta(minutes=5)
    repo.advance_repair_cursor(T)
    assert repo.repair_cursor(T)==T+timedelta(minutes=5)

@pytest.mark.parametrize('status',[429,418])
async def test_rest_rate_limit_retry(monkeypatch,status):
    calls=[];sleeps=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,path,params=None):
            calls.append(params)
            request=httpx.Request('GET','https://data-api.binance.vision'+path)
            if len(calls)==1:return httpx.Response(status,headers={'Retry-After':'60'},request=request)
            ms=int(T.timestamp()*1000)
            if path=='/api/v3/time':return httpx.Response(200,json={'serverTime':ms+60000},request=request)
            return httpx.Response(200,json=[[ms,'2','3','1','2','10',ms+59999,'20',5,'4','8']],request=request)
    async def sleep(seconds):sleeps.append(seconds)
    monkeypatch.setattr('app.provider.httpx.AsyncClient',Client)
    monkeypatch.setattr('app.provider.asyncio.sleep',sleep)
    result=await BinanceSpotProvider(MarketState()).klines(int(T.timestamp()*1000),int(T.timestamp()*1000)+60000)
    assert len(result)==1 and len(calls)==3 and 59<sleeps[1]<=60
    assert calls[-1]['endTime']==int(T.timestamp()*1000)+59999 and calls[-1]['limit']==1000

async def test_backfill_rejects_unclosed_minutes(sessions):
    end=now().replace(second=0,microsecond=0)+timedelta(minutes=1)
    with pytest.raises(ValueError):await Backfill(sessions,FakeProvider()).run(end-timedelta(minutes=1),end)

async def test_sampler_survives_write_failure(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    class Repo:
        def save_snapshot(self,p):
            calls.append(p)
            if len(calls)==1:raise ConnectionError('DB down')
            return True
    c=Collector(state(now()),None,Repo(),SimpleNamespace(max_state_age_seconds=10,snapshot_interval_seconds=.001))
    task=asyncio.create_task(c.sample())
    for _ in range(100):
        if len(calls)>=2:break
        await asyncio.sleep(.005)
    task.cancel();await asyncio.gather(task,return_exceptions=True)
    assert len(calls)>=2 and calls[0]['message_id']!=calls[1]['message_id']

def test_migration_roundtrip(sessions,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect,text
    from app.storage.models import Base
    engine=sessions.kw['bind'];Base.metadata.drop_all(engine)
    with engine.begin() as c:c.execute(text('DROP TABLE IF EXISTS alembic_version'))
    monkeypatch.setenv('MARKET_DATA_DATABASE_URL',os.environ['TEST_DATABASE_URL'])
    config=Config('alembic.ini');command.upgrade(config,'head')
    with engine.connect() as c:
        assert compare_metadata(MigrationContext.configure(c),Base.metadata)==[]
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='m30002'
    command.downgrade(config,'base')
    assert inspect(engine).get_table_names()==['alembic_version']
    command.upgrade(config,'head')
    command.downgrade(config,'base')

@pytest.mark.parametrize('delta',[0,0.2,2.9])
def test_causal_snapshot_nearest_before_or_equal(repo,delta):
    for seconds in (0,3):
        t=T+timedelta(seconds=seconds);repo.save_snapshot(state(t).snapshot(t))
    target=T+timedelta(seconds=delta)
    causal=repo.lookup(target,3,'causal')['realtime']
    assert causal['available'] and causal['observed_at']=='2026-04-01T00:00:00Z'
    assert datetime.fromisoformat(causal['observed_at'].replace('Z','+00:00'))<=target
    if delta==2.9:assert repo.lookup(target,3)['realtime']['observed_at']=='2026-04-01T00:00:03Z'

def test_causal_tolerance_does_not_use_closer_future(repo):
    for seconds in (0,5):
        t=T+timedelta(seconds=seconds);repo.save_snapshot(state(t).snapshot(t))
    r=repo.lookup(T+timedelta(seconds=4),3,'causal')
    assert r['realtime']=={'available':False,'reason':'no_snapshot_within_tolerance'}
    assert repo.lookup(T+timedelta(seconds=4),3)['realtime']['available']

def test_causal_previous_closed_candle_and_exact_boundary(repo):
    repo.save_candle(bar(T-timedelta(minutes=1)));repo.save_candle(bar(T))
    previous=repo.lookup(T,3,'causal')['candle_1m']
    assert previous['open_time']=='2026-03-31T23:59:00Z' and previous['close_time']=='2026-03-31T23:59:59.999000Z'
    assert repo.lookup(T,3)['candle_1m']['open_time']=='2026-04-01T00:00:00Z'
    assert repo.lookup(T+timedelta(seconds=59,milliseconds=999),3,'causal')['candle_1m']['open_time']=='2026-04-01T00:00:00Z'

def test_causal_no_closed_candle_does_not_return_future(repo):
    repo.save_candle(bar(T))
    assert not repo.lookup(T,3,'causal')['candle_1m']['available']

async def test_causal_api_additive_mode(repo):
    app.state.context=(Settings(),None,repo,state(),None,[])
    repo.save_candle(bar(T-timedelta(minutes=1)));repo.save_candle(bar(T))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        response=await c.get('/market/snapshot',params={'at':T.isoformat(),'mode':'causal'})
        assert response.status_code==200 and response.json()['candle_1m']['open_time']=='2026-03-31T23:59:00Z'
        assert (await c.get('/market/snapshot',params={'at':T.isoformat(),'mode':'invalid'})).status_code==422

def test_live_known_at_excludes_late_backfill(repo,sessions):
    from app.storage.repository import naive
    past=bar(T-timedelta(minutes=1));repo.save_candle(past,'rest')
    with sessions.begin() as s:
        r=s.get(MarketCandle,('binance_spot','BTCUSDT','1m',naive(past.open_time)));r.collected_at=naive(T+timedelta(hours=1))
    assert not repo.lookup(T,3,'causal',known_at=T)['candle_1m']['available']
    assert repo.lookup(T,3,'causal')['candle_1m']['available']
    assert repo.lookup(T,3,'causal',known_at=T+timedelta(hours=1))['candle_1m']['available']

def test_live_known_at_selects_latest_already_known_candle(repo,sessions):
    from app.storage.repository import naive
    for minutes in (1,2):repo.save_candle(bar(T-timedelta(minutes=minutes)))
    with sessions.begin() as s:
        for r in s.scalars(select(MarketCandle)):
            r.collected_at=naive(T-timedelta(seconds=1) if r.open_time==naive(T-timedelta(minutes=2)) else T+timedelta(minutes=1))
    assert repo.lookup(T,3,'causal',known_at=T)['candle_1m']['open_time']=='2026-03-31T23:58:00Z'

async def test_known_at_api_validation(repo):
    app.state.context=(Settings(),None,repo,state(),None,[])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        for params in ({'at':T.isoformat(),'known_at':T.isoformat()}, {'at':T.isoformat(),'mode':'causal','known_at':(T-timedelta(seconds=1)).isoformat()}):
            assert (await c.get('/market/snapshot',params=params)).status_code==422

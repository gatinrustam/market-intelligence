import asyncio,copy,json,os
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx,pytest
from sqlalchemy import select,func,text
from jsonschema.exceptions import ValidationError
from app.domain import anchor,OFFSETS,parse,iso,now,resolve_point,empty_point,returns,status
from app.worker import ContextWorker
from app.storage.models import ContextInput,ContextJob,MarketContext,MarketContextPoint,ContextRevision,OutboxEvent,DeadInput,Base,utcnow
from app.storage.repository import identity,LeaseLost
from app.publishers.outbox import OutboxPublisher
from app.publishers.nats import JetStreamBus
from app.market import MarketDataClient
from app.consumers.input import InputConsumer
from app.main import create_app
T=datetime(2026,4,29,18,tzinfo=timezone.utc)

def exact(event,t=T):
    e=copy.deepcopy(event);e['time'].update(event_time=iso(t),event_time_precision='exact',event_time_source='body');return e

def accept(repo,event,subject=None):
    return repo.accept(json.dumps(event).encode(),1,subject or ('event.detected.v1' if event['event']['revision']==1 else 'event.updated.v1'))

def market_data(t,resolution='candle',price='100'):
    base={'provider':'binance_spot','symbol':'BTCUSDT','requested_at':iso(t),'realtime':{'available':False,'reason':'not_collected'},'candle_1m':{'available':False,'reason':'not_collected'}}
    if resolution=='realtime':
        base['realtime']={'available':True,'observed_at':iso(t),'distance_ms':0,'last_trade_price':price,'best_bid':'99','best_ask':'101','spread_bps':'200',
            'snapshot':{'provider':'binance_spot','symbol':'BTCUSDT','message_id':str(uuid4())}}
    if resolution=='candle':
        minute=t.replace(second=0,microsecond=0)-timedelta(minutes=1)
        base['candle_1m']={'available':True,'open_time':iso(minute),'close_time':iso(minute+timedelta(seconds=59,milliseconds=999)),
            'open':price,'high':price,'low':price,'close':price,'base_volume':'12','quote_volume':'1200','trade_count':5,'taker_buy_base_volume':'4','taker_buy_quote_volume':'400'}
    return base
class Market:
    def __init__(self,resolution='candle'):self.resolution=resolution;self.calls=[]
    async def lookup(self,t):self.calls.append(t);return market_data(t,self.resolution,str(Decimal('100')+Decimal(str((t-T).total_seconds()))/1000))
    async def close(self):pass

def force_due(sessions,key):
    with sessions.begin() as s:
        job=s.get(ContextJob,key);job.next_attempt_at=utcnow()-timedelta(seconds=1);job.status='pending'
def context(sessions,key):
    with sessions() as s:return copy.deepcopy(s.get(MarketContext,key).payload)

@pytest.mark.parametrize('precision',['exact','minute','hour'])
def test_event_anchor(event,precision):
    e=exact(event);e['time']['event_time_precision']=precision
    a=anchor(e);assert a['type']=='event_time' and a['at']==iso(T) and a['precision']==precision

def test_publication_anchor(event):
    a=anchor(event);assert a['type']=='source_published_at' and a['at']==iso(T)
@pytest.mark.parametrize('precision,value',[('date','2026-04-29'),('date_range','2026-04-28/2026-04-29')])
def test_imprecise_anchor_not_invented(event,precision,value):
    e=exact(event);e['time'].update(event_time=value,event_time_precision=precision)
    a=anchor(e);assert a['at'] is None and a['type']=='event_time' and a['unavailable_reason']=='imprecise_event_time'

def test_missing_anchor(event):
    event['time']['earliest_source_published_at']=None
    assert anchor(event)['unavailable_reason']=='missing_anchor_time'

@pytest.mark.parametrize('resolution',['realtime','candle','none'])
def test_point_resolution(resolution):
    p=resolve_point(0,T,market_data(T,resolution),T+timedelta(minutes=2),10)
    if resolution=='realtime':assert p['resolution']=='realtime_1s' and p['bid']=='99' and p['candle'] is None
    elif resolution=='candle':assert p['resolution']=='candle_1m' and p['bid'] is None and p['ask'] is None and p['spread_bps'] is None and p['price_basis']=='candle_close'
    else:assert p['available'] is False and p['status']=='unavailable'

def test_open_minute_grace():
    p=resolve_point(0,T,market_data(T,'none'),T+timedelta(seconds=2),10)
    assert p['status']=='pending' and p['reason']=='awaiting_market_data'
    future=market_data(T,'candle');future['candle_1m']['close_time']=iso(T+timedelta(seconds=59))
    with pytest.raises(ValueError):resolve_point(0,T,future,T+timedelta(minutes=2),10)

def test_decimal_returns():
    points=[empty_point(o,T,'unavailable','not_collected') for o in OFFSETS]
    points[2].update(price='0.00000003');points[3].update(price='0.00000004');points[0].update(price='0.00000002')
    computed=returns(points)
    assert computed[3]['return_pct_from_anchor']=='33.333333333333'
    assert computed[0]['return_pct_from_anchor']=='-33.333333333333' and computed[0]['absolute_return_pct']=='33.333333333333'
    assert computed[2]['return_pct_from_anchor']=='0.000000000000' and computed[-1]['return_pct_from_anchor'] is None

async def test_future_points_no_calls_and_later_update(repo,event,sessions,settings,contract):
    e=exact(event);key=identity(e);assert accept(repo,e)=='accepted';market=Market('realtime')
    worker=ContextWorker(repo,market,settings,clock=lambda:T)
    assert await worker.run_once();first=context(sessions,key);contract.validate(first)
    assert first['status']['pending_future_points']==4 and len(market.calls)==3 and first['revision']==1
    with sessions() as s:assert s.scalar(select(func.count()).select_from(MarketContextPoint))==7
    force_due(sessions,key);worker.clock=lambda:T+timedelta(seconds=61)
    assert await worker.run_once();second=context(sessions,key)
    assert second['revision']==2 and second['status']['pending_future_points']==3
    with sessions() as s:
        assert s.get(ContextRevision,(key,1)).payload==first
        assert s.scalar(select(func.count()).select_from(MarketContextPoint))==7
        assert [r.subject for r in s.scalars(select(OutboxEvent).order_by(OutboxEvent.revision))]==['market.context.created.v1','market.context.updated.v1']
    force_due(sessions,key);assert await worker.run_once();assert context(sessions,key)==second

async def test_unavailable_later_backfill(repo,event,sessions,settings):
    key=identity(event);accept(repo,event);market=Market('none');worker=ContextWorker(repo,market,settings,clock=lambda:T+timedelta(hours=2))
    await worker.run_once();first=context(sessions,key)
    assert first['status']['unavailable_points']==7 and not first['status']['complete']
    force_due(sessions,key);await worker.run_once();assert context(sessions,key)==first
    market.resolution='candle';force_due(sessions,key);await worker.run_once();second=context(sessions,key)
    assert second['revision']==2 and second['status']['complete']
    assert all(p['resolution']=='candle_1m' and p['bid'] is None for p in second['points'])

async def test_duplicate_input_scheduler_revision_isolation(repo,event,sessions,settings):
    key=identity(event);accept(repo,event);assert accept(repo,event)=='duplicate'
    e2=copy.deepcopy(event);e2['message_id']=str(uuid4());e2['event'].update(revision=2,change_type='updated');e2['correlation'].update(method='exact_key',exact_event_key='a'*64)
    assert accept(repo,e2)=='accepted';worker=ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2))
    await worker.run_once();await worker.run_once();assert not await worker.run_once()
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(ContextInput))==2
        assert s.scalar(select(func.count()).select_from(MarketContext))==2
        assert s.scalar(select(func.count()).select_from(MarketContextPoint))==14
    assert context(sessions,key)['event']['event_revision']==1 and context(sessions,identity(e2))['event']['event_revision']==2

def test_input_conflict_quarantine(repo,event,sessions):
    accept(repo,event);changed=copy.deepcopy(event);changed['content']['canonical_title']='conflict'
    assert accept(repo,changed)=='identity_conflict'
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(DeadInput))==1
        assert s.get(ContextInput,identity(event)).payload==event

@pytest.mark.parametrize('raw,subject',[(b'{','event.detected.v1'),(b'{"x":1,"x":2}','event.detected.v1'),(b'{"x":NaN}','event.detected.v1'),(b'[]','event.detected.v1')])
def test_invalid_input_quarantine(repo,sessions,raw,subject):
    assert repo.accept(raw,1,subject)=='invalid'
    with sessions() as s:assert s.scalar(select(func.count()).select_from(ContextJob))==0

def test_subject_mismatch(repo,event):assert accept(repo,event,'event.updated.v1')=='invalid'

async def test_missing_anchor_context(repo,event,sessions,settings,contract):
    event['time']['earliest_source_published_at']=None;accept(repo,event);market=Market()
    await ContextWorker(repo,market,settings).run_once();p=context(sessions,identity(event));contract.validate(p)
    assert market.calls==[] and all(p['target_at'] is None for p in p['points'])
    with sessions() as s:assert s.get(ContextJob,identity(event)).status=='completed'

async def test_http_failure_retry_preserves_context(repo,event,sessions,settings):
    accept(repo,event);market=Market('realtime');worker=ContextWorker(repo,market,settings,clock=lambda:T)
    await worker.run_once();key=identity(event);before=context(sessions,key)
    worker.clock=lambda:T+timedelta(minutes=1);market.lookup=AsyncMock(side_effect=httpx.ConnectError('down'));force_due(sessions,key)
    await worker.run_once();assert context(sessions,key)==before
    with sessions() as s:assert s.get(ContextJob,key).last_error=='ConnectError'

async def test_expired_job_restart_and_fencing(repo,event,sessions,settings):
    accept(repo,event);old,_,_=repo.claim();assert repo.claim() is None
    with sessions.begin() as s:s.get(ContextJob,old.id).lease_until=utcnow()-timedelta(seconds=1)
    fresh,_,_=repo.claim();worker=ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2));a,p,next_at=await worker.calculate(event,None)
    with pytest.raises(LeaseLost):repo.finish(old,a,p,next_at)
    repo.finish(fresh,a,p,next_at)
    assert context(sessions,identity(event))['revision']==1

async def test_transaction_rollback(repo,event,sessions,settings,contract,monkeypatch):
    accept(repo,event);job,_,_=repo.claim();a,p,next_at=await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).calculate(event,None)
    monkeypatch.setattr(contract,'validate',lambda p:(_ for _ in ()).throw(ValidationError('fixture')))
    with pytest.raises(ValidationError):repo.finish(job,a,p,next_at)
    with sessions() as s:
        for model in (MarketContext,MarketContextPoint,ContextRevision,OutboxEvent):assert s.scalar(select(func.count()).select_from(model))==0

async def test_outbox_retry_restart_order(repo,event,sessions,settings,contract):
    accept(repo,event);key=identity(event);worker=ContextWorker(repo,Market('realtime'),settings,clock=lambda:T);await worker.run_once()
    force_due(sessions,key);worker.clock=lambda:T+timedelta(minutes=1);await worker.run_once()
    bus=AsyncMock();bus.publish.side_effect=ConnectionError('offline');publisher=OutboxPublisher(sessions,bus,contract);await publisher.run_once()
    assert publisher.claim() is None # revision 2 cannot overtake failed creation
    with sessions.begin() as s:
        for r in s.scalars(select(OutboxEvent)):r.next_attempt_at=utcnow()
    good=AsyncMock();new=OutboxPublisher(sessions,good,contract)
    await new.run_once();await new.run_once()
    assert [c.args[2] for c in good.publish.call_args_list]==['market.context.created.v1','market.context.updated.v1']
    with sessions() as s:assert all(r.status=='published' for r in s.scalars(select(OutboxEvent)))

async def test_outbox_abandoned_lease(repo,event,sessions,settings,contract):
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once()
    worker=OutboxPublisher(sessions,AsyncMock(),contract);row=worker.claim();assert worker.claim() is None
    with sessions.begin() as s:s.get(OutboxEvent,row.id).lease_until=utcnow()-timedelta(seconds=1)
    assert await worker.run_once();worker.finish(row,error='obsolete')
    with sessions() as s:assert s.get(OutboxEvent,row.id).status=='published'

@pytest.mark.parametrize('mutate',[lambda p:p.update(extra=1),lambda p:p['points'][0].update(extra=1),lambda p:p['points'][0].update(price=100),lambda p:p['points'][0].update(bid='1'),lambda p:p['points'][0].update(offset_seconds=0),lambda p:p.update(message_id='x'),lambda p:p['status'].update(complete=False),lambda p:p['points'][0].update(return_pct_from_anchor='99'),lambda p:p['anchor'].update(at='2026-01-01T00:00:00Z')])
async def test_strict_contract(repo,event,sessions,settings,contract,mutate):
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once()
    p=context(sessions,identity(event));contract.validate(p);mutate(p)
    with pytest.raises(ValidationError):contract.validate(p)

async def test_http_adapter_uses_stage3_only():
    client=MarketDataClient('http://market-data:8003');await client.client.aclose()
    def response(request):
        assert request.url.host=='market-data' and request.url.path=='/market/snapshot'
        assert request.url.params['symbol']=='BTCUSDT' and request.url.params['at']==iso(T) and request.url.params['mode']=='causal'
        return httpx.Response(200,json=market_data(T))
    client.client=httpx.AsyncClient(base_url='http://market-data:8003',transport=httpx.MockTransport(response))
    try:assert (await client.lookup(T))['candle_1m']['available']
    finally:await client.close()

async def test_ack_after_commit_and_nak_on_failure(repo,event,sessions):
    from types import SimpleNamespace
    consumer=InputConsumer(None,repo,'TEST')
    m=SimpleNamespace(data=json.dumps(event).encode(),subject='event.detected.v1',metadata=SimpleNamespace(sequence=SimpleNamespace(stream=1,consumer=1),stream='EVENTS',consumer='TEST',num_delivered=1,timestamp=T),ack_sync=AsyncMock(),nak=AsyncMock())
    async def ack(**kwargs):
        with sessions() as s:assert s.get(ContextJob,identity(event)) is not None
    m.ack_sync.side_effect=ack;await consumer.handle(m);m.ack_sync.assert_awaited_once();m.nak.assert_not_awaited()
    repo.accept=lambda *args:(_ for _ in ()).throw(ConnectionError('DB down'))
    await consumer.handle(m);m.nak.assert_awaited_once()

async def test_api(repo,event,sessions,settings):
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once()
    app=create_app(settings);app.state.sessions=sessions;app.state.repo=repo
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        key=identity(event);assert (await client.get('/contexts/'+key)).json()['context_id']==key
        assert len((await client.get('/contexts/'+key+'/revisions')).json())==1
        assert len((await client.get('/events/'+event['event']['id']+'/contexts')).json())==1
        assert (await client.get('/contexts/missing')).status_code==404
        assert (await client.get('/stats')).json()['contexts_total']==1

def test_migration_roundtrip(sessions,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect
    engine=sessions.kw['bind'];Base.metadata.drop_all(engine)
    with engine.begin() as c:c.execute(text('DROP TABLE IF EXISTS alembic_version'))
    monkeypatch.setenv('MARKET_CONTEXT_DATABASE_URL',os.environ['TEST_DATABASE_URL']);cfg=Config('alembic.ini');command.upgrade(cfg,'head')
    with engine.connect() as c:assert compare_metadata(MigrationContext.configure(c),Base.metadata)==[]
    command.downgrade(cfg,'base');assert inspect(engine).get_table_names()==['alembic_version']
    command.upgrade(cfg,'head');command.downgrade(cfg,'base')

async def test_real_jetstream_consume_both_subjects_and_publish(repo,event,sessions,settings,contract):
    from nats.js.api import StreamConfig,StorageType
    from nats.js.errors import NotFoundError
    url=os.environ['TEST_NATS_URL'];assert 'nats-test' in url
    bus=JetStreamBus(url);await bus.connect()
    try:
        try:await bus.js.stream_info('EVENTS')
        except NotFoundError:await bus.js.add_stream(config=StreamConfig(name='EVENTS',subjects=['event.detected.v1','event.updated.v1'],storage=StorageType.FILE))
        await bus.js.purge_stream('EVENTS');await bus.js.purge_stream('MARKET_CONTEXTS')
        durable='CONTEXT_TEST_'+uuid4().hex[:12];consumer=InputConsumer(bus,repo,durable)
        await consumer.subscribe()
        await bus.js.publish('event.detected.v1',json.dumps(event).encode())
        await bus.js.publish('event.detected.v1',json.dumps(event).encode())
        second=copy.deepcopy(event);second['message_id']=str(uuid4());second['event'].update(revision=2,change_type='updated');second['correlation'].update(method='exact_key',exact_event_key='a'*64)
        await bus.js.publish('event.updated.v1',json.dumps(second).encode())
        assert await consumer.run_once()
        worker=ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2))
        await worker.run_once();await worker.run_once()
        publisher=OutboxPublisher(sessions,bus,contract)
        await publisher.run_once();await publisher.run_once()
        info=await bus.js.stream_info('MARKET_CONTEXTS');assert info.state.messages==2
        for sequence in range(info.state.first_seq,info.state.last_seq+1):
            raw=await bus.js.get_msg('MARKET_CONTEXTS',seq=sequence);payload=json.loads(raw.data);contract.validate(payload)
            await bus.publish(payload['message_id'],payload,raw.subject)
        assert (await bus.js.stream_info('MARKET_CONTEXTS')).state.messages==2
        info=await bus.js.consumer_info('EVENTS',durable);assert info.num_ack_pending==0
        assert repo.stats()['inputs_total']==2
        await bus.js.delete_consumer('EVENTS',durable)
    finally:await bus.close()

@pytest.mark.parametrize('field,value',[('symbol','ETHUSDT'),('provider','other'),('requested_at','2026-01-01T00:00:00Z')])
def test_reject_wrong_market_response(field,value):
    data=market_data(T);data[field]=value
    with pytest.raises(ValueError):resolve_point(0,T,data,T+timedelta(hours=2),10)

async def test_available_points_frozen_and_returns_recomputed_when_anchor_arrives(repo,event,sessions,settings):
    e=exact(event);accept(repo,e);market=Market('realtime')
    original=market.lookup
    async def partial(t):return market_data(t,'none') if t==T else await original(t)
    market.lookup=partial;worker=ContextWorker(repo,market,settings,clock=lambda:T+timedelta(hours=2));await worker.run_once()
    key=identity(e);first=context(sessions,key);assert all(p['return_pct_from_anchor'] is None for p in first['points'])
    async def later(t):
        assert t==T
        return market_data(t,'realtime','100')
    market.lookup=later;force_due(sessions,key);await worker.run_once();second=context(sessions,key)
    assert second['status']['complete'] and second['points'][0]['price']==first['points'][0]['price']
    assert second['points'][0]['return_pct_from_anchor']=='-0.900000000000'

async def test_zero_anchor_rejected_as_schema_error(repo,event,sessions,settings,contract):
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once()
    p=context(sessions,identity(event));p['points'][2]['price']='0'
    with pytest.raises(ValidationError):contract.validate(p)

async def test_concurrent_duplicate_ingestion(repo,event,sessions):
    await asyncio.gather(*(asyncio.to_thread(accept,repo,event) for _ in range(4)))
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(ContextInput))==1
        assert s.scalar(select(func.count()).select_from(ContextJob))==1
        assert s.get(ContextInput,identity(event)).exact_payload==json.dumps(event).encode()

@pytest.mark.parametrize('offset',OFFSETS)
def test_future_observation_rejected_at_every_offset(offset):
    target=T+timedelta(seconds=offset)
    data=market_data(target,'realtime');data['realtime']['observed_at']=iso(target+timedelta(microseconds=1))
    with pytest.raises(ValueError):resolve_point(offset,target,data,T+timedelta(hours=3),10)
    data=market_data(target,'candle');data['candle_1m']['close_time']=iso(target+timedelta(microseconds=1))
    with pytest.raises(ValueError):resolve_point(offset,target,data,T+timedelta(hours=3),10)

@pytest.mark.parametrize('offset',OFFSETS)
def test_asof_point_and_role(offset):
    from app.causal import point_role
    target=T+timedelta(seconds=offset);p=resolve_point(offset,target,market_data(target,'realtime'),T+timedelta(hours=2),10)
    assert parse(p['price_at'])<=target
    assert point_role(offset)==('causal' if offset<=0 else 'outcome')
    if offset>0:assert parse(p['price_at'])>T

async def test_policy_research_new_revision_preserves_legacy(repo,event,sessions,settings):
    from app.causal import POLICY,LEGACY_POLICY
    accept(repo,event);worker=ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2));await worker.run_once();key=identity(event)
    with sessions.begin() as s:
        row=s.get(MarketContext,key);legacy=copy.deepcopy(row.payload)
        for p in legacy['points']:
            p['candle']['open_time']=p['target_at'];p['candle']['close_time']=iso(parse(p['target_at'])+timedelta(seconds=59,milliseconds=999));p['price_at']=p['candle']['close_time']
        row.payload=copy.deepcopy(legacy);row.lookup_policy=LEGACY_POLICY
        revision=s.get(ContextRevision,(key,1));revision.payload=copy.deepcopy(legacy);revision.lookup_policy=LEGACY_POLICY
    force_due(sessions,key);await worker.run_once();new=context(sessions,key)
    assert new['revision']==2 and all(parse(p['price_at'])<=parse(p['target_at']) for p in new['points'])
    with sessions() as s:
        assert s.get(ContextRevision,(key,1)).payload==legacy
        assert s.get(ContextRevision,(key,2)).lookup_policy==POLICY
        assert s.get(MarketContextPoint,(key,0)).role=='causal'
        assert s.get(MarketContextPoint,(key,60)).role=='outcome'
    force_due(sessions,key);await worker.run_once();assert context(sessions,key)==new

async def test_decision_view_excludes_all_outcome_information(repo,event,sessions,settings):
    from app.causal import decision_view,POLICY,LEGACY_POLICY
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once()
    p=context(sessions,identity(event));first=decision_view(p,POLICY)
    assert [q['offset_seconds'] for q in first['points']]==[-900,-300,0]
    assert all(q['role']=='causal' and parse(q['price_at'])<=parse(q['target_at'])<=T for q in first['points'])
    changed=copy.deepcopy(p);changed['revision']=999;changed['message_id']=str(uuid4());changed['status']={'future_secret':'OUTCOME_SECRET'};changed['generated_at']='2099-01-01T00:00:00Z'
    for q in changed['points'][3:]:q.update(price='OUTCOME_SECRET',candle={'secret':'OUTCOME_SECRET'},status='OUTCOME_SECRET')
    assert decision_view(changed,POLICY)==first and 'OUTCOME_SECRET' not in json.dumps(first)
    with pytest.raises(ValueError):decision_view(p,LEGACY_POLICY)
    p['points'][0]['price_at']=iso(T+timedelta(seconds=1))
    with pytest.raises(ValueError):decision_view(p,POLICY)

async def test_decision_api_fail_closed_for_legacy(repo,event,sessions,settings):
    from app.causal import LEGACY_POLICY
    accept(repo,event);await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(hours=2)).run_once();key=identity(event)
    app=create_app(settings);app.state.sessions=sessions
    app.state.decisions=AsyncMock();app.state.decisions.build.return_value={'points':[{}, {}, {}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        r=await c.get('/contexts/'+key+'/decision');assert r.status_code==200 and len(r.json()['points'])==3
        with sessions.begin() as s:s.get(MarketContext,key).lookup_policy=LEGACY_POLICY
        assert (await c.get('/contexts/'+key+'/decision')).status_code==409
        assert (await c.get('/contexts/'+key)).status_code==200

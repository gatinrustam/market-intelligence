import copy,json,os
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx,pytest
from pydantic import ValidationError as ConfigError
from jsonschema.exceptions import ValidationError
from sqlalchemy import select,func
from app.config import Settings
from app.domain import HORIZONS,now,parse,iso,digest,identity,context_id,movement,direction,impact,prepare_input,validate_outcomes
from app.storage.models import EvaluationInput,EvaluationJob,Evaluation,EvaluationRevision,EvaluationResult,OutboxEvent,DeadInput,utcnow
from app.storage.repository import Repository
from app.worker import Worker,Upstreams
from app.metrics import metrics
from app.publishers.outbox import OutboxPublisher
from app.publishers.nats import JetStreamBus
from app.consumers.input import InputConsumer
from app.main import create_app


def envelope(analysis,package): return json.dumps({'fixture_label':'test-fixture-v1','analysis':analysis,'decision_input':package}).encode()
def accept(repo,analysis,package): return repo.accept(envelope(analysis,package),1,'fixture.analysis.completed.v1',{'stream':'test'})
def due(sessions):
    with sessions.begin() as s:
        for job in s.scalars(select(EvaluationJob)): job.next_attempt_at=utcnow();job.lease_until=None
        for row in s.scalars(select(OutboxEvent)): row.next_attempt_at=utcnow();row.lease_until=None
class Outcomes:
    def __init__(self,analysis,package): self.analysis=analysis;self.package=package;self.ready=set();self.missing=set();self.calls=0;self.value='100.18'
    async def input(self,analysis): return copy.deepcopy(self.package)
    async def outcomes(self,prepared,analysis):
        self.calls+=1;anchor=parse(analysis['decision']['decision_at']);points=[]
        for n in HORIZONS:
            target=anchor+timedelta(seconds=n);available=n in self.ready
            points.append({'role':'outcome','offset_seconds':n,'target_at':iso(target),'status':'available' if available else 'unavailable' if n in self.missing else 'pending',
                'available':available,'reason':None if available else 'not_collected' if n in self.missing else 'future_target',
                'price':self.value if available else None,'price_at':iso(target-timedelta(milliseconds=1)) if available else None,
                'resolution':'candle_1m' if available else None})
        return {'context_id':prepared['context_id'],'event':analysis['event'],'market':{'provider':'binance_spot','symbol':'BTCUSDT'},'decision_at':analysis['decision']['decision_at'],
            'usage':'evaluation_only','lookup_policy':'causal_asof_fresh_v1','freshness_policy':{'version':'causal_asof_fresh_v1','max_age_seconds':{'candle_1m':60,'realtime_1s':3}},'points':points}

def setup(repo,settings,analysis,package):
    assert accept(repo,analysis,package)=='accepted'
    upstream=Outcomes(analysis,package)
    return Worker(repo,upstream,settings),upstream

@pytest.mark.parametrize('value,expected',[('0','neutral'),('0.049999999999','neutral'),('-0.049999999999','neutral'),('0.05','up'),('-0.05','down'),('2','up'),('-2','down')])
def test_direction_boundaries(settings,value,expected): assert direction(Decimal(value),settings.policy())==expected
@pytest.mark.parametrize('value,expected',[('0','negligible'),('0.099999999999','negligible'),('0.10','small'),('-0.499999999999','small'),('0.50','moderate'),('-1.499999999999','moderate'),('1.50','large'),('-5','large')])
def test_impact_boundaries(settings,value,expected): assert impact(Decimal(value),settings.policy())==expected

def test_decimal_calculation_and_custom_config():
    assert movement('3','3.01')==Decimal('0.333333333333')
    assert movement('100','99.82')==Decimal('-0.180000000000')
    assert movement('100000000000000000.00','100000000000000000.01')==Decimal('0.000000000000')
    settings=Settings(neutral_threshold_pct='0.2',negligible_threshold_pct='0.3')
    assert direction(Decimal('0.18'),settings.policy())=='neutral'
    assert impact(Decimal('0.18'),settings.policy())=='negligible'
@pytest.mark.parametrize('kwargs',[{'neutral_threshold_pct':'0'},{'neutral_threshold_pct':'NaN'},{'small_threshold_pct':'0.01'},{'moderate_threshold_pct':'0.50'}])
def test_invalid_config(kwargs):
    with pytest.raises(ConfigError): Settings(**kwargs)

async def test_pending_incremental_revisions_noop_and_immutable(repo,settings,sessions,analysis,package):
    worker,upstream=setup(repo,settings,analysis,package)
    await worker.run_once();key=identity(analysis['analysis_id']);initial=copy.deepcopy(repo.view(key))
    assert initial['revision']==1 and {p['status'] for p in initial['results']}=={'pending'}
    due(sessions);await worker.run_once();assert repo.view(key)==initial
    upstream.ready={60};due(sessions);await worker.run_once()
    first=copy.deepcopy(repo.view(key));assert first['revision']==2 and first['results'][0]['evaluation']['direction_result']=='hit'
    assert first['results'][0]['actual']['return_pct']=='0.180000000000'
    upstream.ready={60,300};due(sessions);await worker.run_once()
    second=repo.view(key);assert second['revision']==3 and second['results'][1]['status']=='evaluated'
    upstream.value='90';upstream.ready=set(HORIZONS);due(sessions);await worker.run_once()
    last=repo.view(key);assert last['revision']==4 and last['status']['complete']
    assert last['results'][0]==first['results'][0] # terminal observation frozen
    assert last['results'][2]['evaluation']['direction_result']=='miss'
    with sessions() as s:
        assert s.get(EvaluationRevision,(key,1)).payload==initial
        assert s.get(EvaluationRevision,(key,2)).payload==first
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==4
        assert s.scalar(select(func.count()).select_from(EvaluationResult))==4
    assert not await worker.run_once()

async def test_unclear_unavailable_and_later_backfill(repo,settings,sessions,analysis,package):
    analysis['forecast'][0]['direction']='unclear'
    worker,upstream=setup(repo,settings,analysis,package);upstream.ready={60};upstream.missing={300,900,3600}
    await worker.run_once();value=repo.view(identity(analysis['analysis_id']))
    assert value['results'][0]['status']=='not_scored'
    assert value['results'][0]['evaluation']['direction_result']=='not_scored'
    assert value['results'][0]['evaluation']['impact_match'] is True
    assert value['results'][1]['status']=='unavailable' and value['results'][1]['actual'] is None
    assert not value['status']['complete']
    upstream.ready=set(HORIZONS);due(sessions);await worker.run_once()
    assert repo.view(identity(analysis['analysis_id']))['status']['complete']

def test_duplicate_conflict_and_invalid_input(repo,sessions,analysis,package):
    assert accept(repo,analysis,package)=='accepted'
    assert accept(repo,analysis,package)=='duplicate'
    original=copy.deepcopy(analysis)
    analysis['forecast'][0]['direction']='down'
    assert accept(repo,analysis,package)=='dead'
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(EvaluationInput))==1
        assert s.get(EvaluationInput,analysis['analysis_id']).payload==original
    assert repo.accept(b'not json',2,'analysis.completed.v1',{})=='dead'
    assert repo.accept(envelope(original,package),3,'analysis.completed.v1',{})=='dead'
    assert repo.accept(json.dumps(original).encode(),3,'analysis.completed.v1',{})=='dead'

def test_fixture_disabled(settings,sessions,analysis,package):
    settings.fixtures_enabled=False
    assert accept(Repository(sessions,settings),analysis,package)=='dead'

async def test_real_analysis_input_supported(repo,settings,analysis,package):
    analysis['audit']['model']='gpt-6-astra'
    assert repo.accept(json.dumps(analysis).encode(),1,'analysis.completed.v1',{})=='accepted'
    upstream=Outcomes(analysis,package);upstream.ready=set(HORIZONS)
    await Worker(repo,upstream,settings).run_once()
    value=repo.view(identity(analysis['analysis_id']))
    assert value['provenance']['origin']=='model' and value['status']['complete']
    assert value['provenance']['fixture_label'] is None

@pytest.mark.parametrize('mutation',[
    lambda d:d.update(context_id=str(uuid4())),
    lambda d:d.update(decision_at='2020-01-01T00:00:00Z'),
    lambda d:d['points'][0].update(offset_seconds=0),
    lambda d:d['points'][0].update(role='causal'),
    lambda d:d['points'][0].update(price_at='2099-01-01T00:00:00Z'),
    lambda d:d['points'][0].update(price_at='2000-01-01T00:00:00Z'),
    lambda d:d['points'][0].update(price='NaN'),
    lambda d:d['freshness_policy']['max_age_seconds'].update(candle_1m=float('nan')),
    lambda d:d['points'][0].update(available=1),
])
async def test_reject_wrong_causal_stale_future_outcomes(analysis,package,mutation):
    prepared=prepare_input(analysis,package);upstream=Outcomes(analysis,package);upstream.ready={60}
    data=await upstream.outcomes(prepared,analysis);mutation(data)
    with pytest.raises(ValueError):validate_outcomes(analysis,data)

def test_tampered_frozen_input(analysis,package):
    package['market_context']['points'][-1]['price']='999'
    with pytest.raises(ValueError,match='hash'):prepare_input(analysis,package)

async def test_policy_frozen_on_accept_and_restart(repo,settings,sessions,analysis,package):
    worker,upstream=setup(repo,settings,analysis,package);upstream.ready={60}
    job,_,_=repo.claim()
    with sessions.begin() as s:s.get(EvaluationJob,job.id).lease_until=utcnow()-timedelta(seconds=1)
    settings.neutral_threshold_pct=Decimal('2')
    restarted=Repository(sessions,settings)
    await Worker(restarted,upstream,settings).run_once()
    value=restarted.view(identity(analysis['analysis_id']))
    assert value['policy']['neutral_threshold_pct']=='0.05' and value['results'][0]['actual']['direction']=='up'
    assert not repo.finish(job,SimpleNamespace(id=job.id),{},[],None) # obsolete lease cannot write

async def test_aggregate_counts_grouping_and_fixture_exclusion(repo,settings,sessions,analysis,package):
    worker,upstream=setup(repo,settings,analysis,package);upstream.ready=set(HORIZONS);await worker.run_once()
    other=copy.deepcopy(analysis);other['analysis_id']=other['message_id']=str(uuid4())
    other['audit']['model']='fixture/second';other['audit']['prompt_version']='fixture_v2'
    other['forecast'][0].update(direction='down',confidence='high');other['forecast'][1]['direction']='unclear'
    worker2,up2=setup(repo,settings,other,package);up2.ready={60,300};up2.missing={900};await worker2.run_once()
    assert metrics(sessions,['horizon'])['rows']==[]
    rows=metrics(sessions,['horizon'],origin='fixture')['rows'];by={r['group']['horizon']:r for r in rows}
    assert by[60]['n']==2 and by[60]['hits']==1 and by[60]['misses']==1 and by[60]['direction_accuracy_pct']=='50.000000'
    assert by[300]['n']==1 and by[300]['not_scored']==1
    assert by[900]['unavailable']==1 and by[3600]['pending']==1
    conf=metrics(sessions,['confidence'],origin='fixture')['rows']
    assert next(r for r in conf if r['group']['confidence']=='high')['misses']==1
    assert len(metrics(sessions,['model','prompt_version'],origin='fixture')['rows'])==2
    for group in ['source','event_type']:
        assert metrics(sessions,[group],origin='fixture')['rows'][0]['n']==5

async def test_outbox_retry_schema_and_order(repo,settings,sessions,analysis,package):
    worker,up=setup(repo,settings,analysis,package);await worker.run_once()
    up.ready={60};due(sessions);await worker.run_once()
    bus=AsyncMock();bus.publish.side_effect=ConnectionError('offline')
    pub=OutboxPublisher(sessions,bus,repo.output_contract)
    assert await pub.run_once()
    assert not await pub.run_once() # revision 2 cannot overtake revision 1 retry
    due(sessions);bus.publish.side_effect=None
    assert await pub.run_once() and await pub.run_once() and not await pub.run_once()
    assert bus.publish.call_args_list[-2].args[1]['revision']==1
    assert bus.publish.call_args_list[-1].args[1]['revision']==2
    value=copy.deepcopy(repo.view(identity(analysis['analysis_id'])))
    repo.output_contract.validate(value)
    for change in [lambda v:v.update(extra='bad'),lambda v:v['results'][0]['actual'].update(extra='bad'),lambda v:v['results'][0]['actual'].update(return_pct=0.18),lambda v:v['results'].reverse()]:
        bad=copy.deepcopy(value);change(bad)
        with pytest.raises(ValidationError):repo.output_contract.validate(bad)

async def test_read_only_api(repo,settings,sessions,analysis,package):
    worker,up=setup(repo,settings,analysis,package);up.ready=set(HORIZONS);await worker.run_once()
    settings2=Settings(database_url=os.environ['TEST_DATABASE_URL'],workers_enabled=False)
    app=create_app(settings2)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            key=identity(analysis['analysis_id'])
            assert (await client.get('/evaluations/'+key)).json()['evaluation_id']==key
            assert (await client.get('/analyses/'+analysis['analysis_id']+'/evaluation')).status_code==200
            assert len((await client.get('/evaluations/'+key+'/revisions')).json())==1
            assert (await client.get('/metrics')).json()['rows']==[]
            assert len((await client.get('/metrics?origin=fixture')).json()['rows'])==4
            assert (await client.get('/metrics?group_by=invalid')).status_code==422
            assert (await client.get('/evaluations/not-uuid')).status_code==422
            assert (await client.get('/events/'+analysis['event']['event_id']+'/evaluations?origin=all')).json()[0]['evaluation_id']==key
            assert (await client.post('/evaluations/'+key,json={})).status_code==405
            assert (await client.get('/stats')).json()['evaluations']=={'fixture':1}

async def test_jetstream_input_outbox_and_dedup(repo,settings,sessions,analysis,package):
    bus=JetStreamBus(os.environ['TEST_NATS_URL'],fixtures=True);assert 'nats-test' in bus.url
    try:
        await bus.connect();await bus.js.purge_stream('EVALUATIONS');await bus.js.purge_stream('EVALUATION_FIXTURE_INPUTS')
        consumer=InputConsumer(bus,repo,'TEST_'+uuid4().hex,fixture=True)
        await bus.js.publish('fixture.analysis.completed.v1',envelope(analysis,package))
        assert await consumer.run_once()
        up=Outcomes(analysis,package);up.ready=set(HORIZONS);await Worker(repo,up,settings).run_once()
        pub=OutboxPublisher(sessions,bus,repo.output_contract);assert await pub.run_once()
        info=await bus.js.stream_info('EVALUATIONS');raw=await bus.js.get_msg('EVALUATIONS',seq=info.state.last_seq)
        value=json.loads(raw.data);assert value['provenance']['origin']=='fixture';repo.output_contract.validate(value)
        assert raw.subject=='fixture.evaluation.created.v1'
        await bus.js.publish('fixture.analysis.completed.v1',envelope(analysis,package));assert await consumer.run_once()
        with sessions() as s: assert s.scalar(select(func.count()).select_from(EvaluationInput))==1
        await bus.publish(value['message_id'],value,raw.subject)
        assert (await bus.js.stream_info('EVALUATIONS')).state.messages==1
    finally:await bus.close()

@pytest.mark.parametrize('predicted,outcome,expected',[
    ('up','100.18','hit'),('down','99.82','hit'),('neutral','100.04','hit'),
    ('unclear','100.18','not_scored'),('up','100','miss'),('neutral','99.82','miss')])
def test_forecast_correctness_matrix(settings,predicted,outcome,expected):
    from app.domain import result
    value=result({'horizon_seconds':60,'direction':predicted,'impact':'small','confidence':'high'},
        {'available':True,'price':outcome,'price_at':'2026-04-29T18:00:59.999Z','target_at':'2026-04-29T18:01:00Z','resolution':'candle_1m'},
        {'price':'100','price_at':'2026-04-29T17:59:59.999Z'},settings.policy())
    assert value['evaluation']['direction_result']==expected
    assert value['forecast']['confidence']=='high'
    assert value['status']==('not_scored' if predicted=='unclear' else 'evaluated')

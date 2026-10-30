import copy,json,os
from datetime import timedelta
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx,pytest
from sqlalchemy import select,func
from app.domain import canonical,digest,prompt,normalize,validate_output
from app.guard import build_input,Blocked
from app.provider import OpenAIProvider,ProviderError,request_body
from app.worker import Worker
from app.storage.models import AnalysisJob,AnalysisInput,AnalysisResult,AnalysisRun,OutboxEvent,utcnow
from app.storage.contract import Contract
from app.publishers.outbox import OutboxPublisher
from app.publishers.nats import JetStreamBus
from app.main import create_app

def input_value(package,settings):return build_input(package,package['event'],settings)
def enqueue(repo,p):return repo.enqueue(p['event'],p['context_id'],'research_hypothetical',str(uuid4()))
def worker(repo,p,settings,output):
    decision=AsyncMock();decision.fetch.return_value=copy.deepcopy(p)
    provider=AsyncMock();provider.analyze.return_value={'output':output,'audit':{'provider_response_id':'resp_fake','usage':{'input_tokens':50,'output_tokens':100},'latency_ms':1}}
    return Worker(repo,decision,provider,settings),decision,provider

def test_input_exact_immutable_allowlist(package,settings):
    value=input_value(package,settings);before=canonical(value)
    package['outcomes']={'price':'FUTURE'};package['points'][0]['future_nested']={'secret':'FUTURE'}
    assert canonical(input_value(package,settings))==before
    assert len(value['market_context']['points'])==3
    assert all(x['offset_seconds']<=0 for x in value['market_context']['points'])
    assert value['decision']['historical_simulation'] is True
    assert digest(value)==digest(json.loads(before))

@pytest.mark.parametrize('mutation',[
 lambda p:p.update(decision_ready=False),
 lambda p:p.update(historical_simulation=False),
 lambda p:p.update(lookup_policy='causal_asof_v1'),
 lambda p:p['points'].append({**p['points'][-1],'offset_seconds':60}),
 lambda p:p['points'][-1].update(age_seconds=100),
 lambda p:p['points'][-1].update(price_at='2099-01-01T00:00:00Z'),
 lambda p:p['known_information']['evidence'].clear(),
 lambda p:p['known_information']['evidence'][0]['document'].update(message_id=str(uuid4())),
 lambda p:p['known_information']['evidence'][0].update(evidence_available_at='2000-01-01T00:00:00Z'),
])
def test_guard_rejects_invalid(package,settings,mutation):
    mutation(package)
    with pytest.raises(Blocked):input_value(package,settings)

def test_live_evidence_must_be_available(package,settings):
    package.update(decision_mode='live',decision_basis='live_observed',historical_simulation=False)
    with pytest.raises(Blocked):input_value(package,settings)

def test_prompt_and_tools(settings,package):
    request=request_body(settings.configuration(),canonical(input_value(package,settings)))
    assert request['tools']==[] and request['tool_choice']=='none' and request['store'] is False
    assert request['reasoning']=={'effort':'medium'} and request['text']['format']['strict']
    assert 'previous_response_id' not in request and 'conversation' not in request
    assert request['model']=='gpt-6-astra'
    assert 'chain-of-thought' in request['input'][0]['content']

def response_body(output):return {'id':'resp_fake','model':'gpt-6-astra','status':'completed','usage':{'input_tokens':50,'output_tokens':100},'output':[{'type':'reasoning','summary':[{'text':'PRIVATE_REASONING'}]},{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}]}
async def call_provider(settings,package,handler):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=OpenAIProvider('FAKE_SECRET',client=client)
        return await provider.analyze(request_body(settings.configuration(),canonical(input_value(package,settings))))
async def test_valid_provider_no_reasoning_saved(settings,package,output):
    def handler(request):
        body=json.loads(request.content);assert body['tools']==[] and body['tool_choice']=='none'
        assert request.url.path=='/v1/responses'
        return httpx.Response(200,json=response_body(output))
    result=await call_provider(settings,package,handler)
    assert result['output']==output and 'PRIVATE_REASONING' not in canonical(result)
    assert 'FAKE_SECRET' not in canonical(result) and result['audit']['provider_response_id']=='resp_fake'
@pytest.mark.parametrize('status,retry',[(429,True),(500,True),(503,True),(400,False),(401,False),(403,False)])
async def test_provider_errors(settings,package,status,retry):
    with pytest.raises(ProviderError) as caught:await call_provider(settings,package,lambda r:httpx.Response(status,json={'error':{'message':'FAKE_SECRET'}}))
    assert caught.value.transient==retry and 'FAKE_SECRET' not in canonical(caught.value.audit)
@pytest.mark.parametrize('error',[httpx.ReadTimeout,httpx.ConnectError])
async def test_network_errors(settings,package,error):
    def handler(r):raise error('secret')
    with pytest.raises(ProviderError) as caught:await call_provider(settings,package,handler)
    assert caught.value.transient and 'secret' not in str(caught.value)
@pytest.mark.parametrize('mutation',[
 lambda b:b.update(status='incomplete'),
 lambda b:b['output'][-1]['content'][0].update(text='not json'),
 lambda b:b['output'][-1]['content'][0].update(text='{}'),
 lambda b:b['output'].append({'type':'function_call','name':'web'}),
])
async def test_malformed_provider(settings,package,output,mutation):
    body=response_body(output);mutation(body)
    with pytest.raises(ProviderError) as caught:await call_provider(settings,package,lambda r:httpx.Response(200,json=body))
    assert caught.value.invalid
async def test_refusal_not_retry(settings,package):
    with pytest.raises(ProviderError) as caught:await call_provider(settings,package,lambda r:httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'no'}]}]}))
    assert not caught.value.transient and not caught.value.invalid

async def test_success_atomic_outbox_and_restart(repo,sessions,settings,package,output):
    key=enqueue(repo,package);w,d,p=worker(repo,package,settings,output)
    assert await w.run_once()
    view=repo.view(key);assert view['analysis_status']=='completed' and view['input_hash']
    Contract(settings.contracts_dir/'analysis/v1.schema.json').validate(view['analysis'])
    row=repo.input(view['input_hash']);assert view['runs'][0]['request']['input'][1]['content']==row.canonical_json
    package['points'][-1]['price']='1';assert repo.input(row.id).canonical_json==row.canonical_json
    assert not await Worker(repo,d,p,settings).run_once();assert p.analyze.await_count==1
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(AnalysisResult))==1
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==1

async def test_blocked_never_calls_provider(repo,settings,package,output):
    package['decision_ready']=False;key=enqueue(repo,package);w,_,p=worker(repo,package,settings,output)
    await w.run_once();assert repo.view(key)['analysis_status']=='blocked';p.analyze.assert_not_awaited()

def test_duplicate_and_model_prompt_identity(repo,package,settings,monkeypatch):
    e=package['event'];config=settings.configuration()
    a=repo.enqueue(e,package['context_id']);assert repo.enqueue(e,package['context_id'])==a
    b=repo.enqueue(e,package['context_id'],configuration={**config,'model':'gpt-5.6-terra'});assert a!=b
    import app.storage.repository as module
    real=module.prompt;monkeypatch.setattr(module,'prompt',lambda version:real('btc_event_analysis_v1'))
    c=repo.enqueue(e,package['context_id'],configuration={**config,'prompt_version':'btc_event_analysis_v2'});assert c not in (a,b)

@pytest.mark.parametrize('invalid',[False,True])
async def test_bounded_retry_frozen_input(repo,sessions,settings,package,output,invalid):
    key=enqueue(repo,package);w,d,p=worker(repo,package,settings,output)
    p.analyze.side_effect=ProviderError('invalid' if invalid else 'http_429',transient=not invalid,invalid=invalid,audit={'provider_response_id':'resp_bad'})
    limit=settings.max_invalid_attempts if invalid else settings.max_attempts
    for index in range(limit):
        await w.run_once()
        with sessions.begin() as s:s.get(AnalysisJob,key).next_attempt_at=utcnow()-timedelta(seconds=1)
    view=repo.view(key);assert view['analysis_status']=='failed' and len(view['runs'])==limit
    assert d.fetch.await_count==1 and len({r['request']['input'][1]['content'] for r in view['runs']})==1
    assert not await w.run_once()
    with sessions() as s:assert s.scalar(select(func.count()).select_from(OutboxEvent))==0

async def test_expired_lease_and_fencing(repo,sessions,settings,package,output):
    key=enqueue(repo,package);old=repo.claim();value=input_value(package,settings);row=repo.freeze(old,value)
    run=repo.start_run(old,request_body(old.configuration,row.canonical_json))
    with sessions.begin() as s:s.get(AnalysisJob,key).lease_until=utcnow()-timedelta(seconds=1)
    fresh=repo.claim();assert fresh.lease_token!=old.lease_token
    assert not repo.finish(old,run,error='old_owner')
    assert repo.view(key)['runs'][0]['status']=='abandoned'
    assert repo.finish(fresh,error='test_end')

async def test_research_rerun_exact_input_api(repo,sessions,settings,package,output):
    key=enqueue(repo,package);w,_,_=worker(repo,package,settings,output);await w.run_once()
    app=create_app(settings);app.state.repo=repo;app.state.sessions=sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        body={'run_key':str(uuid4()),'model':'gpt-5.6-terra'}
        a=await c.post('/analyses/'+key+'/research',json=body);assert a.status_code==202
        b=await c.post('/analyses/'+key+'/research',json=body);assert a.json()==b.json()
        new=a.json()['analysis_id'];assert new!=key
        assert repo.view(new)['input_hash']==repo.view(key)['input_hash']
        assert (await c.get('/analyses/'+new+'/input')).json()['canonical_json']==repo.input(repo.view(key)['input_hash']).canonical_json
        bad=await c.post('/analyses/'+key+'/research',json={**body,'prompt_version':'does_not_exist'});assert bad.status_code==422
    w,d,p=worker(repo,package,settings,output);await w.run_once();d.fetch.assert_not_awaited()
    assert repo.view(new)['analysis_status']=='completed'

async def test_outbox_outage_recovery_and_duplicate(repo,sessions,settings,package,output):
    key=enqueue(repo,package);w,_,_=worker(repo,package,settings,output);await w.run_once()
    bus=AsyncMock();bus.publish.side_effect=ConnectionError('outage')
    pub=OutboxPublisher(sessions,bus,Contract(settings.contracts_dir/'analysis/v1.schema.json'))
    assert await pub.run_once()
    with sessions.begin() as s:
        out=s.scalar(select(OutboxEvent));assert out.status=='pending';out.next_attempt_at=utcnow()-timedelta(seconds=1)
    bus.publish.side_effect=None;assert await pub.run_once();assert not await pub.run_once()
    with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='published'

@pytest.mark.jetstream
async def test_real_jetstream_outbox(repo,sessions,settings,package,output):
    bus=JetStreamBus(os.environ['TEST_NATS_URL'])
    try:
        await bus.connect();await bus.js.purge_stream('ANALYSES')
        key=enqueue(repo,package);w,_,_=worker(repo,package,settings,output);await w.run_once()
        pub=OutboxPublisher(sessions,bus,Contract(settings.contracts_dir/'analysis/v1.schema.json'));assert await pub.run_once()
        first=await bus.js.get_msg('ANALYSES',seq=(await bus.js.stream_info('ANALYSES')).state.first_seq);payload=json.loads(first.data)
        assert payload==repo.view(key)['analysis'] and first.subject=='analysis.completed.v1'
        await bus.publish(payload['message_id'],payload,first.subject)
        assert (await bus.js.stream_info('ANALYSES')).state.messages==1
    finally:await bus.close()

@pytest.mark.parametrize('mutation',[
 lambda p:p.update(extra=True),lambda p:p['forecast'][0].update(confidence='87%'),
 lambda p:p['forecast'][0].update(direction='BUY'),lambda p:p['forecast'].reverse(),
 lambda p:p['decision'].update(extra='future'),lambda p:p['audit'].update(input_hash='bad')])
def test_strict_contract(repo,settings,package,output,mutation):
    key=enqueue(repo,package);job=repo.claim();row=repo.freeze(job,input_value(package,settings));payload=normalize(job,row,output)
    mutation(payload)
    with pytest.raises(Exception):Contract(settings.contracts_dir/'analysis/v1.schema.json').validate(payload)

def test_valid_live_marker(package,settings):
    from app.domain import parse,iso
    decision=parse(package['live_inputs_available_at'])
    package.update(decision_at=iso(decision),as_of=iso(decision),decision_mode='live',decision_basis='live_observed',historical_simulation=False,market_availability_basis='locally_collected_by_decision_at',content_assumption='exact_observed_inputs_available_by_decision_at')
    for p in package['points']:
        t=decision+timedelta(seconds=p['offset_seconds'])
        p.update(target_at=iso(t),price_at=iso(t),resolution='realtime_1s',age_seconds=0,max_age_seconds=3,candle=None)
    value=input_value(package,settings)
    assert value['decision']['historical_simulation'] is False
    package['known_information']['evidence'][0]['evidence_available_at']=iso(decision+timedelta(seconds=1))
    with pytest.raises(Blocked):input_value(package,settings)

async def test_input_consumer_acks_only_after_commit(repo,package):
    from app.consumers.input import InputConsumer
    from types import SimpleNamespace
    from app.domain import now
    msg=AsyncMock();msg.data=canonical(package['known_information']['canonical_event']).encode();msg.subject='event.detected.v1'
    msg.metadata=SimpleNamespace(sequence=SimpleNamespace(stream=1,consumer=1),stream='EVENTS',consumer='test',num_delivered=1,timestamp=now())
    consumer=InputConsumer(AsyncMock(),repo,'test')
    await consumer.handle(msg);msg.ack_sync.assert_awaited_once()
    await consumer.handle(msg);assert sum(repo.stats()['jobs'].values())==1
    failed=AsyncMock();failed.accept=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=RuntimeError('db'))
    msg.reset_mock();await InputConsumer(AsyncMock(),failed,'test').handle(msg)
    msg.ack_sync.assert_not_awaited();msg.nak.assert_awaited_once()

@pytest.mark.jetstream
async def test_new_only_consumer_does_not_replay_backlog(repo,package):
    from app.consumers.input import InputConsumer
    from nats.js.api import StreamConfig,StorageType
    from nats.js.errors import NotFoundError
    bus=JetStreamBus(os.environ['TEST_NATS_URL']);durable='analysis-test-'+uuid4().hex
    try:
        await bus.connect()
        try:await bus.js.stream_info('EVENTS')
        except NotFoundError:await bus.js.add_stream(config=StreamConfig(name='EVENTS',subjects=['event.detected.v1','event.updated.v1'],storage=StorageType.FILE))
        raw=canonical(package['known_information']['canonical_event']).encode()
        await bus.js.publish('event.detected.v1',raw)
        consumer=InputConsumer(bus,repo,durable);await consumer.subscribe()
        await bus.js.publish('event.detected.v1',raw)
        assert await consumer.run_once()
        info=await bus.js.consumer_info('EVENTS',durable)
        assert info.delivered.consumer_seq==1 and info.num_ack_pending==0
    finally:
        if bus.js:await bus.js.delete_consumer('EVENTS',durable)
        await bus.close()

def test_prompt_manifest_detects_modification(monkeypatch,tmp_path):
    import app.domain as module
    from pathlib import Path
    import shutil
    root=tmp_path/'prompts';shutil.copytree(Path(module.__file__).parent/'prompts',root)
    monkeypatch.setattr(module,'__file__',str(tmp_path/'domain.py'))
    (root/'btc_event_analysis_v1.txt').write_text('changed prompt')
    with pytest.raises(ValueError,match='modified'):prompt('btc_event_analysis_v1')

async def test_read_only_analysis_catalogue(repo,sessions,settings,package,output):
    key=enqueue(repo,package);w,_,_=worker(repo,package,settings,output);await w.run_once()
    app=create_app(settings);app.state.repo=repo;app.state.sessions=sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        data=(await c.get('/analyses')).json();assert data['total']==1
        row=data['items'][0];assert row['analysis_id']==key and row['analysis_status']=='completed'
        assert row['latency_ms']==1 and row['usage']['input_tokens']==50 and row['created_at'].endswith('+00:00')
        assert 'request' not in row and 'api_key' not in canonical(row)
        assert (await c.get('/analyses',params={'offset':1})).json()['items']==[]
        assert (await c.get('/analyses',params={'limit':101})).status_code==422

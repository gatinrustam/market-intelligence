import copy,json,os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx,pytest
from jsonschema import ValidationError
from sqlalchemy import select,func
from nats.js.api import StreamConfig,StorageType
from nats.js.errors import NotFoundError
from app.domain import features,identity,canonical,digest,Rules
from app.storage.repository import Repository
from app.storage.models import IntelligenceInput,IntelligenceRun,IntelligenceResult,OutboxEvent,DeadInput,utcnow
from app.worker import Worker,EventsClient
from app.publishers.outbox import OutboxPublisher
from app.publishers.nats import JetStreamBus
from app.consumers.input import InputConsumer
from app.main import create_app

def accept(repo,snapshot):
    event=snapshot['event']
    return repo.accept(canonical(event).encode(),1,'event.detected.v1' if event['event']['revision']==1 else 'event.updated.v1',{'stream':'EVENTS'})
def worker(repo,snapshot):return Worker(repo,SimpleNamespace(snapshot=AsyncMock(return_value=snapshot)))
@pytest.mark.parametrize('event_type,source,relevance,specificity',[
 ('central_bank.policy_statement','fed_monetary_policy','high','specific'),
 ('central_bank.policy_statement','ecb_press','medium','specific'),
 ('central_bank.speech','ecb_press','medium','commentary'),
 ('central_bank.interview','ecb_press','low','commentary'),
 ('regulator.enforcement','sec_press_releases','low','specific'),
 ('regulator.personnel','sec_press_releases','low','general'),
 ('unknown','other','none','unknown')])
def test_controlled_classification(snapshot,rules,event_type,source,relevance,specificity):
    snapshot['event']['taxonomy']['event_type']=event_type
    for r in snapshot['event']['evidence']['documents']:r['source_id']=source
    value,_=features(snapshot,rules)
    assert (value['relevance'],value['event_specificity'])==(relevance,specificity)
def test_digital_asset_topic_not_accidental_body_word(snapshot,rules):
    snapshot['event']['taxonomy']['event_type']='regulator.enforcement'
    snapshot['documents'][0]['content']['body']='Bitcoin crypto digital assets'
    assert features(snapshot,rules)[0]['relevance']=='low'
    snapshot['event']['taxonomy']['topics']=['digital_assets']
    result,matched=features(snapshot,rules)
    assert result['relevance']=='high' and 'topic.digital_assets' in matched

def test_configured_explicit_crypto_source_rule(snapshot,rules):
    rules['rules'].append({'id':'crypto.source','sources':['fed_monetary_policy'],'topics_any':[],'event_types':[],'canonical_rule_ids':[],'minimum_relevance':'high','relevance':None,'specificity':None})
    snapshot['event']['taxonomy']['event_type']='unknown'
    assert features(snapshot,rules)[0]['relevance']=='high'

def test_no_expectations_no_surprise(snapshot,rules):
    result,_=features(snapshot,rules)
    assert result['surprise']=={'status':'unavailable','value':None}
    assert all(v is None for v in result['expectations'].values())

def test_quality_partial_corroborated_and_untrusted(snapshot,rules,examples):
    assert features(snapshot,rules)[0]['information_quality']=='high'
    assert features(examples['SEC'],rules)[0]['information_quality']=='medium'
    snapshot['event']['evidence']['quality']='medium'
    snapshot['event']['lifecycle']['status']='corroborated'
    snapshot['event']['evidence']['independent_source_count']=2
    assert features(snapshot,rules)[0]['information_quality']=='high'
    snapshot['documents'][0]['enrichment']['status']='partial'
    assert features(snapshot,rules)[0]['information_quality']=='medium'
    snapshot['documents'][0]['content']['body']=''
    assert features(snapshot,rules)[0]['information_quality']=='low'

@pytest.mark.parametrize('status',['failed','partial'])
def test_partial_quality_never_high(snapshot,rules,status):
    snapshot['documents'][0]['enrichment']['status']=status
    snapshot['event']['lifecycle']['status']='corroborated';snapshot['event']['evidence']['independent_source_count']=3
    assert features(snapshot,rules)[0]['information_quality']!='high'

def test_revision_history_novelty(snapshot,rules):
    assert features(snapshot,rules)[0]['novelty']=='new'
    snapshot['previous']=copy.deepcopy({'event':snapshot['event'],'documents':snapshot['documents']})
    snapshot['event']['event'].update(revision=2,change_type='updated');snapshot['event']['correlation']['method']='exact_key'
    assert features(snapshot,rules)[0]['novelty']=='duplicate_like'
    snapshot['documents'][0]['integrity']['content_hash']='a'*64
    assert features(snapshot,rules)[0]['novelty']=='update'
    snapshot['event']['correlation']['method']='unsupported'
    assert features(snapshot,rules)[0]['novelty']=='unknown'

async def test_duplicate_input_noop_immutable_result(repo,sessions,snapshot):
    assert accept(repo,snapshot)=='accepted';assert accept(repo,snapshot)=='duplicate'
    w=worker(repo,snapshot);assert await w.run_once();assert not await w.run_once()
    key=identity(snapshot['event']['event'],repo.configuration['version']);before=repo.view(key)
    assert accept(repo,snapshot)=='duplicate';assert not await w.run_once();assert repo.view(key)==before
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(IntelligenceResult))==1
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==1
    bad=copy.deepcopy(snapshot);bad['event']['content']['canonical_title']='different immutable revision'
    assert accept(repo,bad)=='dead';assert repo.view(key)==before

async def test_ruleset_version_isolation_and_mutation_block(repo,sessions,settings,rules,snapshot):
    accept(repo,snapshot);await worker(repo,snapshot).run_once()
    old=repo.view(identity(snapshot['event']['event'],'1.0'))
    changed=copy.deepcopy(rules);changed['default_relevance']='high'
    with pytest.raises(ValueError):Repository(sessions,settings,changed).register()
    changed['version']='2.0';other=Repository(sessions,settings,changed);other.register()
    assert accept(other,snapshot)=='accepted';await worker(other,snapshot).run_once()
    assert other.view(identity(snapshot['event']['event'],'2.0'))['basis']['ruleset_version']=='2.0'
    assert repo.view(old['intelligence_id'])==old

async def test_restart_expired_lease_and_stale_worker_fenced(repo,sessions,settings,rules,snapshot):
    accept(repo,snapshot);run,event=repo.claim()
    with sessions.begin() as s:s.get(IntelligenceRun,run.id).lease_until=utcnow()-timedelta(seconds=1)
    restarted=Repository(sessions,settings,rules);await worker(restarted,snapshot).run_once()
    assert restarted.view(run.id) is not None
    assert not repo.finish(run,snapshot)

async def test_outbox_outage_retry_strict_schema(repo,sessions,snapshot):
    accept(repo,snapshot);await worker(repo,snapshot).run_once()
    bus=AsyncMock();bus.publish.side_effect=ConnectionError('offline');pub=OutboxPublisher(sessions,bus,repo.output_contract)
    assert await pub.run_once()
    with sessions.begin() as s:
        row=s.scalar(select(OutboxEvent));assert row.status=='pending';row.next_attempt_at=utcnow()
    bus.publish.side_effect=None;assert await pub.run_once();assert not await pub.run_once()
    value=repo.view(identity(snapshot['event']['event'],'1.0'));repo.output_contract.validate(value)
    for mutate in [lambda p:p.update(extra=1),lambda p:p['basis'].update(extra=1),lambda p:p.update(relevance='certain'),lambda p:p['surprise'].update(value='2'),lambda p:p['expectations'].update(consensus='2')]:
        bad=copy.deepcopy(value);mutate(bad)
        with pytest.raises(ValidationError):repo.output_contract.validate(bad)

async def test_read_api_exact_revision_and_missing(repo,settings,snapshot):
    accept(repo,snapshot);await worker(repo,snapshot).run_once();key=identity(snapshot['event']['event'],'1.0')
    app=create_app(settings);app.state.repo=repo;app.state.sessions=repo.sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/intelligence/'+key)).json()['intelligence_id']==key
        assert (await c.get('/intelligence/'+key+'/input')).json()['input_hash']==repo.view(key)['basis']['input_hash']
        url='/events/'+snapshot['event']['event']['id']+'/intelligence'
        assert len((await c.get(url,params={'event_revision':1,'ruleset_version':'1.0'})).json())==1
        assert (await c.get(url,params={'event_revision':2})).json()==[]
        assert (await c.get('/intelligence/'+str(uuid4()))).status_code==404
        assert (await c.post('/events/'+snapshot['event']['event']['id']+'/research',json={'event_revision':1,'ruleset_version':'1.0'})).json()['intelligence_id']==key
        assert (await c.get('/stats')).json()['distributions']['relevance']=={'high':1}

async def test_evidence_revision_guard(settings,snapshot):
    client=EventsClient(settings);await client.client.aclose()
    bad=copy.deepcopy(snapshot['documents'][0]);bad['message_id']=str(uuid4())
    client.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'document':bad})),base_url='http://test')
    try:
        with pytest.raises(ValueError):await client.snapshot(snapshot['event'])
    finally:await client.close()

async def test_jetstream_input_publication_and_dedup(repo,sessions,snapshot):
    bus=JetStreamBus(os.environ['TEST_NATS_URL']);assert 'nats-test' in bus.url
    try:
        await bus.connect()
        try:await bus.js.stream_info('EVENTS')
        except NotFoundError:await bus.js.add_stream(config=StreamConfig(name='EVENTS',subjects=['event.detected.v1','event.updated.v1'],storage=StorageType.FILE))
        await bus.js.purge_stream('EVENTS');await bus.js.purge_stream('EVENT_INTELLIGENCE')
        consumer=InputConsumer(bus,repo,'EI_TEST_'+uuid4().hex)
        await bus.js.publish('event.detected.v1',canonical(snapshot['event']).encode());assert await consumer.run_once()
        await worker(repo,snapshot).run_once();pub=OutboxPublisher(sessions,bus,repo.output_contract);assert await pub.run_once()
        info=await bus.js.stream_info('EVENT_INTELLIGENCE');msg=await bus.js.get_msg('EVENT_INTELLIGENCE',seq=info.state.last_seq)
        value=json.loads(msg.data);assert value==repo.view(identity(snapshot['event']['event'],'1.0'))
        await bus.publish(value['message_id'],value,msg.subject)
        assert (await bus.js.stream_info('EVENT_INTELLIGENCE')).state.messages==1
    finally:await bus.close()

def test_named_sec_digital_market_action_is_configured(examples,rules):
    value,matched=features(examples['SEC'],rules)
    assert value['relevance']=='medium' and value['event_specificity']=='specific'
    assert 'sec.tokenized_nms_exemption' in matched
    examples['SEC']['event']['content']['canonical_title']='An unrelated personnel update'
    assert features(examples['SEC'],rules)[0]['relevance']=='low'

async def test_availability_requires_confirmed_publication(repo,settings,snapshot):
    accept(repo,snapshot);await worker(repo,snapshot).run_once();key=identity(snapshot['event']['event'],'1.0')
    app=create_app(settings);app.state.repo=repo;app.state.sessions=repo.sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/intelligence/'+key+'/availability')).status_code==409
        bus=AsyncMock();await OutboxPublisher(repo.sessions,bus,repo.output_contract).run_once()
        body=(await c.get('/intelligence/'+key+'/availability')).json()
        assert body['intelligence']==repo.view(key)
        assert body['availability_basis']=='confirmed_jetstream_publication'

def test_personnel_title_exception_does_not_reclassify_enforcement_body(examples):
    from pathlib import Path
    from app.domain import load_rules
    rules=load_rules(Path('/workspace/config/event_intelligence/rules.v1.1.json'))
    snapshot=examples['SEC'];snapshot['event']['taxonomy']['event_type']='regulator.enforcement'
    snapshot['event']['content']['canonical_title']='SEC Announces Departure of Principal Deputy Director of Enforcement Sam Waldon'
    value,matched=features(snapshot,rules)
    assert (value['relevance'],value['event_specificity'])==('low','general')
    assert 'sec.personnel_announcement' in matched
    assert snapshot['event']['taxonomy']['event_type']=='regulator.enforcement'
    snapshot['event']['content']['canonical_title']='SEC Charges Company with Fraud'
    assert features(snapshot,rules)[0]['event_specificity']=='specific'

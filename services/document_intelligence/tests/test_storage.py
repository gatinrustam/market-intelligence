import copy,json,os
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx,pytest
from sqlalchemy import select,func
from nats.js.api import StreamConfig,StorageType
from nats.js.errors import NotFoundError
from app.domain import canonical,identity,digest
from app.worker import Worker
from app.storage.models import IntelligenceJob,IntelligenceRun,IntelligenceInput,DocumentFact,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.main import create_app

def accept(repo,doc):return repo.accept(canonical(doc).encode(),1,'document.enriched.v1',{'stream':'DOCUMENT_ENRICHED'})

async def test_duplicate_atomic_persistence_and_research_isolation(repo,sessions,pipeline,document,configuration,settings):
    doc=document('The Federal Reserve kept interest rates at 5%.');key=identity(doc,configuration)
    assert accept(repo,doc)=='accepted' and accept(repo,doc)=='duplicate'
    assert await Worker(repo,pipeline).run_once();assert accept(repo,doc)=='duplicate'
    original=repo.view(key)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(IntelligenceRun))==1
        assert s.scalar(select(func.count()).select_from(DocumentFact))==1
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==1
        assert s.get(IntelligenceInput,doc['document_id']).exact_payload==canonical(doc)
    c=copy.deepcopy(configuration);c['rules']['version']='1.1';new=Repository(sessions,settings,c)
    assert accept(new,doc)=='accepted'
    assert identity(doc,c)!=key and repo.view(key)==original
    assert accept(repo,{**doc,'content':{**doc['content'],'title':'Conflicting input'}})=='dead'

async def test_expired_lease_recovers_and_stale_worker_cannot_commit(repo,sessions,pipeline,document,configuration):
    doc=document('The Federal Reserve kept interest rates unchanged.');accept(repo,doc)
    stale,_=repo.claim()
    with sessions.begin() as s:s.get(IntelligenceJob,stale.id).lease_until=utcnow()-timedelta(seconds=1)
    fresh,_=repo.claim();out=pipeline.analyze(doc)
    assert not repo.finish(stale,out) and repo.finish(fresh,out)
    assert repo.view(fresh.id)==out

async def test_failed_storage_rolls_back_result_and_outbox(repo,sessions,pipeline,document,monkeypatch):
    doc=document('The Federal Reserve kept interest rates unchanged.');accept(repo,doc);job,_=repo.claim();out=pipeline.analyze(doc)
    broken=copy.deepcopy(out);broken['facts'][0]['evidence']['text']='not in document'
    with pytest.raises(ValueError):repo.finish(job,broken)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(IntelligenceRun))==0
        assert s.scalar(select(func.count()).select_from(OutboxEvent))==0
        assert s.get(IntelligenceJob,job.id).status=='pending'
    assert repo.finish(job,out)

async def test_core_failure_is_terminal_not_partial(repo,pipeline,document,monkeypatch):
    doc=document('The Federal Reserve kept interest rates unchanged.');accept(repo,doc)
    def fail(*a):raise ValueError('core failure')
    monkeypatch.setattr(pipeline.components['entities'],'extract',fail)
    await Worker(repo,pipeline).run_once();assert repo.stats()['jobs']=={'failed':1}
    assert repo.stats()['outbox']=={}

async def test_outbox_failure_retry_after_new_publisher(repo,sessions,pipeline,document):
    accept(repo,document('Binance suspended Bitcoin withdrawals.'));await Worker(repo,pipeline).run_once()
    bus=AsyncMock();bus.publish.side_effect=ConnectionError('offline');await OutboxPublisher(sessions,bus,repo.output_contract).run_once()
    assert repo.stats()['outbox']=={'pending':1}
    with sessions.begin() as s:
        row=s.scalar(select(OutboxEvent));row.next_attempt_at=utcnow()
    bus=AsyncMock();pub=OutboxPublisher(sessions,bus,repo.output_contract);assert await pub.run_once();assert not await pub.run_once()
    assert repo.stats()['outbox']=={'published':1};bus.publish.assert_awaited_once()

def test_configuration_version_cannot_be_redefined(repo,settings,configuration,sessions):
    c=copy.deepcopy(configuration);c['rules']['topics'].append('invented')
    with pytest.raises(ValueError):Repository(sessions,settings,c).register()

async def test_read_api_exact_input_and_immutable_result(repo,sessions,pipeline,document,settings,configuration):
    doc=document('The SEC charged Example Corp with securities fraud.');accept(repo,doc);await Worker(repo,pipeline).run_once();key=identity(doc,configuration)
    app=create_app(settings);app.state.repo=repo;app.state.sessions=sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/documents/'+doc['document_id']+'/intelligence')).json()==[repo.view(key)]
        assert (await c.get('/intelligence/'+key+'/input')).json()['exact_payload']==canonical(doc)
        assert (await c.get('/intelligence/'+str(uuid4()))).status_code==404
        assert (await c.post('/documents/'+doc['document_id']+'/research')).json()['intelligence_id']==key
        assert len((await c.get('/jobs')).json())==1
        metadata=(await c.get('/intelligence/'+key+'/metadata')).json()
        assert metadata['intelligence_hash']==digest(repo.view(key))
        assert metadata['body_hash']==repo.view(key)['document']['body_hash']
        assert metadata['title']==doc['content']['title'] and 'body' not in metadata and 'content' not in metadata
        assert (await c.get('/intelligence/'+str(uuid4())+'/metadata')).status_code==404

async def test_jetstream_input_ack_and_output_exact_idempotency(repo,sessions,pipeline,document):
    bus=JetStreamBus(os.environ['TEST_NATS_URL']);assert 'nats-test' in bus.url
    try:
        await bus.connect()
        try:await bus.js.stream_info('DOCUMENT_ENRICHED')
        except NotFoundError:await bus.js.add_stream(config=StreamConfig(name='DOCUMENT_ENRICHED',subjects=['document.enriched.v1'],storage=StorageType.FILE))
        await bus.js.purge_stream('DOCUMENT_ENRICHED');await bus.js.purge_stream('DOCUMENT_INTELLIGENCE')
        doc=document('Binance temporarily suspended Bitcoin withdrawals.');await bus.js.publish('document.enriched.v1',canonical(doc).encode())
        consumer=InputConsumer(bus,repo,'DI_TEST_'+uuid4().hex);assert await consumer.run_once()
        await Worker(repo,pipeline).run_once();assert await OutboxPublisher(sessions,bus,repo.output_contract).run_once()
        info=await bus.js.stream_info('DOCUMENT_INTELLIGENCE');message=await bus.js.get_msg('DOCUMENT_INTELLIGENCE',seq=info.state.last_seq);value=json.loads(message.data)
        assert value==repo.view(value['intelligence_id']);await bus.publish(value['message_id'],value,message.subject)
        assert (await bus.js.stream_info('DOCUMENT_INTELLIGENCE')).state.messages==1
    finally:await bus.close()

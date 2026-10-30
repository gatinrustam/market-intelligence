import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from unittest.mock import AsyncMock,Mock
import pytest
from sqlalchemy import select,func,update
from jsonschema.exceptions import ValidationError
from app.storage.models import EventInput,EventJob,ExtractionRun,CandidateRecord,Event,EventDocument,EventRevision,CorrelationSuggestion,OutboxEvent,DeadInput,utcnow
from app.storage.repository import LeaseLost
from app.publishers.outbox import OutboxPublisher
from app.extraction.quality import quality_gate
from app.extraction.rules import RuleBasedEventExtractor
from app.correlation.core import EventCore
from app.workers.process import EventWorker

pytestmark=pytest.mark.integration


def count(repo,model):
 with repo.sessions() as s:
  return s.scalar(select(func.count()).select_from(model))


def rows(repo,model):
 with repo.sessions() as s:
  return list(s.scalars(select(model)))


def accept(repo,doc):
 return repo.accept(json.dumps(doc,ensure_ascii=False,indent=3).encode(),1)


def different(doc,title=None,source=None):
 result=copy.deepcopy(doc)
 result['document_id']=str(uuid4());result['message_id']=str(uuid4());result['lineage']['source_message_id']=str(uuid4())
 if title is not None: result['content']['title']=title
 if source is not None: result['source']['id']=source
 return result


async def test_pipeline_duplicate_exact_input(repository,worker,document,output_contract):
 raw=json.dumps(document,indent=3).encode()
 assert repository.accept(raw,9)=='accepted'
 assert repository.accept(raw,10)=='duplicate'
 await worker.run_once()
 assert not await worker.run_once()
 assert repository.accept(raw,11)=='duplicate'
 assert not await worker.run_once()
 for model in (EventInput,EventJob,ExtractionRun,CandidateRecord,Event,EventDocument,EventRevision,OutboxEvent):
  assert count(repository,model)==1
 assert rows(repository,EventInput)[0].exact_payload==raw
 payload=rows(repository,Event)[0].payload
 output_contract.validate(payload)
 assert payload['event']['revision']==1 and payload['event']['id']!=document['document_id']
 assert payload['event']['change_type']=='created'
 assert 'body' not in payload['content']
 assert payload['evidence']['documents'][0]['source_message_id']==document['lineage']['source_message_id']


async def test_same_document_new_transport_id(repository,worker,document):
 accept(repository,document);await worker.run_once()
 document['message_id']=str(uuid4())
 assert accept(repository,document)=='duplicate'
 assert count(repository,EventRevision)==1


def test_identity_conflict_and_dead_input(repository,document):
 accept(repository,document)
 document['content']['title']='Conflicting mutation'
 assert accept(repository,document)=='identity_conflict'
 assert repository.accept(b'{invalid',2)=='invalid'
 assert repository.accept(b'{invalid',2)=='invalid'
 assert repository.accept(b'{"x":1,"x":2}',3)=='invalid'
 assert count(repository,DeadInput)==3 and count(repository,EventJob)==1
 assert all(r.subject=='document.enriched.v1' and r.validation_error and r.jetstream_metadata for r in rows(repository,DeadInput))


async def test_empty_no_event(repository,worker,document):
 document['content'].update(title=' ',body='',body_length=0)
 document['enrichment'].update(status='failed',failure_reason='missing_url')
 accept(repository,document);await worker.run_once()
 assert count(repository,ExtractionRun)==1 and count(repository,Event)==count(repository,OutboxEvent)==0
 assert rows(repository,ExtractionRun)[0].result_json['outcome']=='no_event'
 assert rows(repository,EventJob)[0].outcome=='no_event'


@pytest.mark.parametrize('name,expected,quality',[('sec','regulator.meeting','medium'),('ecb','central_bank.speech','high')])
async def test_structural_sources(repository,worker,name,expected,quality):
 from pathlib import Path
 doc=json.loads((Path(__file__).parent/'fixtures'/f'{name}.json').read_text())
 accept(repository,doc);await worker.run_once()
 p=rows(repository,Event)[0].payload
 assert p['taxonomy']['event_type']==expected and p['evidence']['quality']==quality


async def test_exact_supporting_revision_same_source(repository,worker,document):
 document['content']['title']='Federal Reserve issues FOMC statement April 29, 2026'
 accept(repository,document);await worker.run_once()
 first=copy.deepcopy(rows(repository,EventRevision)[0].payload)
 second=different(document,'FOMC statement April 29, 2026 — supporting release')
 accept(repository,second);await worker.run_once()
 assert count(repository,Event)==1 and count(repository,EventRevision)==2 and count(repository,EventDocument)==2
 revisions=sorted(rows(repository,EventRevision),key=lambda r:r.revision)
 assert revisions[0].payload==first
 latest=revisions[-1].payload
 assert latest['event']['revision']==2 and latest['event']['change_type']=='updated'
 assert latest['event']['id']==first['event']['id']
 assert latest['content']['canonical_title']==first['content']['canonical_title']
 assert latest['lifecycle']['status']=='detected' and latest['evidence']['independent_source_count']==1
 assert latest['evidence']['documents'][1]['relation']=='supporting'
 assert {o.subject for o in rows(repository,OutboxEvent)}=={'event.detected.v1','event.updated.v1'}
 assert rows(repository,EventJob)[0].status=='completed'
 assert {r.result_json['outcome'] for r in rows(repository,ExtractionRun)}=={'event_created','event_correlated'}


async def test_independent_source_corroboration(repository,document,bundle,settings,output_contract):
 bundle.sources.sources['fed_secondary']=bundle.sources.sources['fed_monetary_policy'].model_copy()
 for rule in bundle.rules.rules:
  if 'fed_monetary_policy' in rule.source_id: rule.source_id.append('fed_secondary')
 extractor=RuleBasedEventExtractor(bundle)
 worker=EventWorker(repository,extractor,EventCore(repository,output_contract,bundle),bundle,settings)
 document['content']['title']='FOMC statement April 29, 2026'
 accept(repository,document);await worker.run_once()
 second=different(document,source='fed_secondary')
 second['timestamps']['published_at']='2026-04-30T12:00:00Z'
 accept(repository,second);await worker.run_once()
 assert count(repository,Event)==1
 payload=rows(repository,Event)[0].payload
 assert payload['lifecycle']['status']=='corroborated' and payload['evidence']['independent_source_count']==2
 assert payload['time']['latest_source_published_at']==second['timestamps']['published_at']
 output_contract.validate(payload)


async def test_critical_false_merges(repository,worker,document):
 titles=['FOMC statement April 29, 2026','FOMC statement June 17, 2026',
         'Federal Reserve releases economic projections from June 17, 2026 FOMC meeting']
 for title in titles:
  accept(repository,different(document,title));await worker.run_once()
 assert count(repository,Event)==3
 assert len({r.exact_event_key for r in rows(repository,Event)})==3
 assert count(repository,CorrelationSuggestion)==0


async def test_same_generic_title_different_publication_no_merge(repository,worker,document):
 accept(repository,document);await worker.run_once()
 second=different(document);second['timestamps']['published_at']='2026-06-17T18:00:00Z'
 accept(repository,second);await worker.run_once()
 assert count(repository,Event)==2
 assert all(e.exact_event_key is None for e in rows(repository,Event))


async def test_fuzzy_suggestion_only(repository,worker,document):
 accept(repository,document);await worker.run_once()
 second=different(document);second['timestamps']['published_at']='2026-04-29T19:00:00Z'
 accept(repository,second);await worker.run_once()
 assert count(repository,Event)==2 and count(repository,CorrelationSuggestion)==1
 suggestion=rows(repository,CorrelationSuggestion)[0]
 assert suggestion.title_similarity==1.0 and suggestion.time_distance_seconds==3600
 assert suggestion.same_event_type and suggestion.same_primary_actor
 assert all(r.revision==1 for r in rows(repository,Event))


def test_input_insert_race(repository,document):
 with ThreadPoolExecutor(max_workers=4) as pool:
  list(pool.map(lambda _:accept(repository,document),range(4)))
 assert count(repository,EventInput)==count(repository,EventJob)==1


def test_claim_race(repository,document):
 accept(repository,document)
 with ThreadPoolExecutor(max_workers=4) as pool:
  claims=list(pool.map(lambda _:repository.claim(),range(4)))
 assert sum(c is not None for c in claims)==1


def test_exact_key_multi_worker_race(repository,core,extractor,document,bundle):
 document['content']['title']='FOMC statement April 29, 2026'
 for _ in range(4): accept(repository,different(document))
 claims=[repository.claim() for _ in range(4)]
 def complete(claim):
  job,doc=claim
  return core.complete(job,doc,extractor.extract(doc),quality_gate(doc,bundle.sources.quality),extractor.name,extractor.version)
 with ThreadPoolExecutor(max_workers=4) as pool:
  results=list(pool.map(complete,claims))
 assert count(repository,Event)==1 and count(repository,EventRevision)==4
 assert sorted(r.revision for r in rows(repository,EventRevision))==[1,2,3,4]
 assert count(repository,EventDocument)==4 and count(repository,OutboxEvent)==4
 assert rows(repository,Event)[0].payload['lifecycle']['status']=='detected'


async def test_restart_fencing(repository,worker,core,extractor,document,bundle):
 accept(repository,document)
 stale,_=repository.claim()
 with repository.sessions.begin() as s:
  s.execute(update(EventJob).values(lease_until=utcnow()-timedelta(seconds=1)))
 await worker.run_once()
 with pytest.raises(LeaseLost):
  core.complete(stale,document,extractor.extract(document),quality_gate(document,bundle.sources.quality),extractor.name,extractor.version)
 assert count(repository,EventRevision)==1 and count(repository,ExtractionRun)==1
 assert not await worker.run_once()


async def test_atomic_rollback_then_retry(repository,worker,document,monkeypatch,output_contract):
 original=output_contract.validate
 monkeypatch.setattr(output_contract,'validate',Mock(side_effect=RuntimeError('test failure')))
 accept(repository,document);await worker.run_once()
 for model in (ExtractionRun,CandidateRecord,Event,EventDocument,EventRevision,OutboxEvent): assert count(repository,model)==0
 with repository.sessions.begin() as s:
  s.execute(update(EventJob).values(next_retry_at=utcnow()-timedelta(seconds=1)))
 monkeypatch.setattr(output_contract,'validate',original)
 await worker.run_once()
 assert count(repository,EventRevision)==count(repository,ExtractionRun)==1


async def test_poison_extractor_bounded_then_next_job(repository,worker,extractor,document,settings,monkeypatch):
 original=extractor.extract
 monkeypatch.setattr(extractor,'extract',Mock(side_effect=ValueError('poison')))
 accept(repository,document)
 for _ in range(settings.max_attempts):
  await worker.run_once()
  with repository.sessions.begin() as s:
   s.execute(update(EventJob).values(next_retry_at=utcnow()-timedelta(seconds=1)))
 assert rows(repository,EventJob)[0].status=='failed'
 assert rows(repository,ExtractionRun)[0].result_json['outcome']=='failed'
 assert count(repository,Event)==0 and not await worker.run_once()
 monkeypatch.setattr(extractor,'extract',original)
 accept(repository,different(document));await worker.run_once()
 assert count(repository,Event)==1


async def test_output_outage_order_stable_revision(repository,worker,document,output_contract):
 document['content']['title']='FOMC statement April 29, 2026'
 accept(repository,document);await worker.run_once()
 accept(repository,different(document));await worker.run_once()
 bus=AsyncMock();bus.publish.side_effect=ConnectionError()
 publisher=OutboxPublisher(repository.sessions,bus,output_contract)
 await publisher.run_once()
 assert not await publisher.run_once() # revision2 waits for pending revision1 even when1 is backing off
 before={r.revision:r.message_id for r in rows(repository,OutboxEvent)}
 assert count(repository,EventRevision)==2
 with repository.sessions.begin() as s:
  s.execute(update(OutboxEvent).values(next_attempt_at=utcnow()-timedelta(seconds=1)))
 bus.publish.side_effect=None
 fresh=OutboxPublisher(repository.sessions,bus,output_contract)
 assert await fresh.run_once() and await fresh.run_once()
 assert all(r.status=='published' and r.message_id==before[r.revision] for r in rows(repository,OutboxEvent))
 assert [c.args[1]['event']['revision'] for c in bus.publish.call_args_list]==[1,1,2]
 assert count(repository,EventRevision)==2


async def test_publisher_stale_token(repository,worker,document,output_contract):
 accept(repository,document);await worker.run_once()
 publisher=OutboxPublisher(repository.sessions,AsyncMock(),output_contract)
 old=publisher.claim()
 with repository.sessions.begin() as s:
  s.execute(update(OutboxEvent).values(lease_until=utcnow()-timedelta(seconds=1)))
 fresh=publisher.claim()
 publisher.finish(old)
 assert rows(repository,OutboxEvent)[0].status=='pending'
 publisher.finish(fresh)
 assert rows(repository,OutboxEvent)[0].status=='published'


async def test_alternate_research_run_preserves_history(repository,worker,document,bundle):
 accept(repository,document);await worker.run_once()
 original=rows(repository,ExtractionRun)[0]
 with repository.sessions.begin() as s:
  repository.record_run(s,None,document,bundle,quality_gate(document,bundle.sources.quality),
   {'outcome':'no_event','candidates':[]},'research_fixture','2.0')
 assert count(repository,ExtractionRun)==2 and count(repository,EventRevision)==1
 with repository.sessions() as s:
  assert s.get(ExtractionRun,original.id).result_json==original.result_json


@pytest.mark.parametrize('mutation',[
 lambda p:p['taxonomy'].update(event_type='fake.type'),lambda p:p['taxonomy'].update(topics=['bullish']),
 lambda p:p['taxonomy'].update(confidence=.93),lambda p:p.pop('actors'),
 lambda p:p['event'].update(revision=2),lambda p:p['evidence'].update(document_count=99),
 lambda p:p['lifecycle'].update(status='corroborated'),lambda p:p['actors'][0].update(resolution='unresolved'),
 lambda p:p['time'].update(event_time_precision='date_range',event_time='2026-06-17/2026-04-29',event_time_source='title')])
async def test_invalid_contract(repository,worker,document,output_contract,mutation):
 accept(repository,document);await worker.run_once()
 p=copy.deepcopy(rows(repository,Event)[0].payload);mutation(p)
 with pytest.raises(ValidationError): output_contract.validate(p)


def test_migration_roundtrip(database):
 from alembic import command
 from alembic.config import Config
 from alembic.autogenerate import compare_metadata
 from alembic.migration import MigrationContext
 from app.storage.models import Base
 with database[0].connect() as conn:
  assert compare_metadata(MigrationContext.configure(conn),Base.metadata)==[]
 command.downgrade(Config('alembic.ini'),'base');command.upgrade(Config('alembic.ini'),'head')
 with database[0].connect() as conn:
  assert compare_metadata(MigrationContext.configure(conn),Base.metadata)==[]


def test_multiple_candidates_document_relation(repository,core,extractor,document,bundle):
 accept(repository,document);job,doc=repository.claim()
 first=extractor.extract(doc)[0]
 second=first.model_copy(deep=True)
 second.candidate_id=str(uuid4());second.event_type='central_bank.projections'
 second.matched_rule_ids=['synthetic.multi_candidate'];second.exact_event_key=None
 core.complete(job,doc,[first,second],quality_gate(doc,bundle.sources.quality),extractor.name,extractor.version)
 assert count(repository,ExtractionRun)==1 and count(repository,CandidateRecord)==2
 assert count(repository,Event)==count(repository,EventDocument)==count(repository,OutboxEvent)==2
 assert len(rows(repository,ExtractionRun)[0].result_json['events'])==2


def test_duplicate_candidates_same_exact_event_one_revision(repository,core,extractor,document,bundle):
 document['content']['title']='FOMC statement April 29, 2026'
 accept(repository,document);job,doc=repository.claim()
 first=extractor.extract(doc)[0];second=first.model_copy(deep=True);second.candidate_id=str(uuid4())
 core.complete(job,doc,[first,second],quality_gate(doc,bundle.sources.quality),extractor.name,extractor.version)
 assert count(repository,CandidateRecord)==2 and count(repository,EventRevision)==count(repository,EventDocument)==1


async def test_restart_attempt_budget_terminal(repository,worker,document,settings):
 accept(repository,document)
 for _ in range(settings.max_attempts):
  assert repository.claim()
  with repository.sessions.begin() as s:
   s.execute(update(EventJob).values(lease_until=utcnow()-timedelta(seconds=1)))
 await worker.run_once()
 assert rows(repository,EventJob)[0].status=='failed'
 assert rows(repository,ExtractionRun)[0].result_json['outcome']=='failed'
 assert count(repository,Event)==0


def test_invalid_candidate_key_cannot_merge(repository,core,extractor,document,bundle):
 accept(repository,document);job,doc=repository.claim()
 candidate=extractor.extract(doc)[0];candidate.exact_event_key='f'*64
 with pytest.raises(ValueError,match='invalid_exact_key'):
  core.complete(job,doc,[candidate],quality_gate(doc,bundle.sources.quality),extractor.name,extractor.version)
 assert count(repository,Event)==count(repository,EventRevision)==0


@pytest.mark.parametrize('kind',['nonfinite','surrogate'])
def test_nonstandard_json_quarantined(repository,document,kind):
 if kind=='nonfinite':
  document['timestamps']['ingestion_delay_seconds']=float('nan')
 else:
  document['content']['title']='invalid surrogate '+chr(0xd800)
 raw=json.dumps(document).encode()
 assert repository.accept(raw,1)=='invalid'
 assert count(repository,DeadInput)==1 and count(repository,EventJob)==0

async def test_immutable_document_input_projection(database,repository,document,settings):
    import json,httpx
    from app.main import create_app
    raw=json.dumps(document).encode()
    repository.accept(raw,17)
    app=create_app(settings);app.state.sessions=database[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/documents/'+document['document_id']+'/input')
        assert response.status_code==200
        p=response.json();assert p['document']==document and p['stream_sequence']==17
        assert p['input_received_at'].endswith('+00:00')
        import hashlib
        assert p['payload_sha256']==hashlib.sha256(raw).hexdigest()
        assert (await client.get('/documents/missing/input')).status_code==404

async def test_read_only_event_catalogue(repository,worker,document,database,settings):
 import httpx
 from app.main import create_app
 accept(repository,document);await worker.run_once()
 app=create_app(settings);app.state.sessions=database[1]
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
  data=(await c.get('/events',params={'limit':1})).json()
  assert data['total']==1 and data['items'][0]['content']['canonical_title']==document['content']['title']
  assert (await c.get('/events',params={'offset':1})).json()['items']==[]
  assert (await c.get('/events',params={'limit':101})).status_code==422
 assert count(repository,Event)==1

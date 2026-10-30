import copy,json
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.domain import build_result
from app.storage.repository import Repository
from app.storage.models import SemanticRun,SemanticResult,OutboxEvent,HumanLabel,utcnow
from app.schema import LabelRequest
from app.main import create_app
from conftest import observation

def complete(repo,snapshot,configuration):
    assert repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})=='accepted'
    run,_=repo.claim();result=build_result(snapshot['intelligence'],snapshot,configuration,observation(snapshot));assert repo.finish(run,snapshot,result);return run.id

def test_atomic_outbox_and_duplicate(repo,examples,configuration,sessions):
    key=complete(repo,examples['Fed'],configuration)
    assert repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),2,'document.intelligence.v1',{})=='duplicate'
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(SemanticResult))==1
        assert s.scalar(select(OutboxEvent)).subject=='article.semantic.v1'
    assert repo.view(key)['facts']==examples['Fed']['intelligence']['facts']

def test_rerun_version_preserves_old_result(repo,examples,configuration,sessions,settings):
    key=complete(repo,examples['Fed'],configuration);before=repo.detail(key)
    new=copy.deepcopy(configuration);new['version']='semantic_pipeline_test_rerun'
    other=Repository(sessions,settings,new);other.register();key2=complete(other,examples['Fed'],new)
    assert key!=key2 and repo.detail(key)==before
    assert repo.for_document(examples['Fed']['document']['document_id'])[0]['machine']['semantic_id']==key2
    new['concept_threshold']=.2
    with pytest.raises(ValueError):other.register()

def test_stale_worker_cannot_commit(repo,examples,configuration,sessions):
    snapshot=examples['Fed'];repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{});old,_=repo.claim()
    with sessions.begin() as s:s.get(SemanticRun,old.id).lease_until=utcnow()-timedelta(seconds=1)
    current,_=repo.claim();result=build_result(snapshot['intelligence'],snapshot,configuration,observation(snapshot))
    assert not repo.finish(old,snapshot,result);assert repo.finish(current,snapshot,result)

def test_review_is_separate_idempotent_and_conflict_checked(repo,examples,configuration):
    key=complete(repo,examples['Fed'],configuration);before=repo.view(key)
    body=LabelRequest(request_id=uuid4(),expected_revision=0,status='reviewed',reviewer='test-reviewer',semantic_correct=True,gold_important=True,gold_assets=['USD','rates'])
    assert repo.label(key,body)['revision']==1;assert repo.label(key,body)['revision']==1
    assert repo.view(key)==before and len(repo.detail(key)['labels'])==1
    with pytest.raises(ValueError):repo.label(key,body.model_copy(update={'request_id':uuid4()}))

def test_unknown_gold_claim_rejected(repo,examples,configuration):
    key=complete(repo,examples['Fed'],configuration)
    with pytest.raises(ValueError):repo.label(key,LabelRequest(request_id=uuid4(),expected_revision=0,status='reviewed',reviewer='test',correct_claim_ids=[uuid4()]))
    assert repo.detail(key)['labels']==[]

def test_insight_read_only_and_review_auth(repo,examples,configuration,settings):
    key=complete(repo,examples['Fed'],configuration);did=examples['Fed']['document']['document_id']
    with TestClient(create_app(settings)) as client:
        rows=client.get('/documents/'+did+'/insight').json();assert rows[0]['insight']['semantic_id']==key
        assert rows[0]['insight']['key_claims']
        assert client.post('/documents/'+did+'/insight',json={}).status_code==405
        label={'request_id':str(uuid4()),'expected_revision':0,'reviewer':'test','status':'reviewed'}
        assert client.post('/reviews/'+key+'/labels',json=label).status_code==401
        assert client.post('/reviews/'+key+'/labels',json=label,headers={'Authorization':'Bearer test-semantic-token'}).status_code==200
        label['request_id']=str(uuid4())
        assert client.post('/reviews/'+key+'/labels',json=label,headers={'Authorization':'Bearer test-semantic-token'}).status_code==409

@pytest.mark.asyncio
async def test_outbox_retry_preserves_message(repo,examples,configuration,sessions):
    from app.publishers.outbox import OutboxPublisher
    key=complete(repo,examples['Fed'],configuration)
    class Bus:
        fail=True
        async def publish(self,*args):
            if self.fail:raise ConnectionError()
    bus=Bus();publisher=OutboxPublisher(sessions,bus,repo.output_contract);await publisher.run_once()
    with sessions.begin() as s:row=s.scalar(select(OutboxEvent));assert row.status=='pending';row.next_attempt_at=utcnow()-timedelta(seconds=1)
    bus.fail=False;await publisher.run_once()
    with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='published'


def test_precision_labels_are_append_only_and_validate_concepts(repo,examples,configuration):
    key=complete(repo,examples['Fed'],configuration);before=repo.view(key)
    body=LabelRequest(request_id=uuid4(),expected_revision=0,status='reviewed',reviewer='pilot',concepts_correct=False,gold_concepts=['interest_rates'],false_positives=['etf'])
    assert repo.label(key,body)['revision']==1
    assert repo.label(key,body)['revision']==1
    assert repo.detail(key)['labels'][0]['false_positives']==['etf']
    bad=body.model_copy(update={'request_id':uuid4(),'expected_revision':1,'gold_concepts':['invented_concept']})
    with pytest.raises(ValueError):repo.label(key,bad)
    next_label=body.model_copy(update={'request_id':uuid4(),'expected_revision':1,'concepts_correct':True})
    assert repo.label(key,next_label)['revision']==2
    assert len(repo.detail(key)['labels'])==2 and repo.view(key)==before

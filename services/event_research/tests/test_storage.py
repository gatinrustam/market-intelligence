import copy,json
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.domain import identity,digest
from app.storage.models import ResearchInput,ResearchRun,ResearchResult,CandidateRecord,ComparisonRecord,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.outbox import OutboxPublisher
from app.worker import Worker

def complete(repo,snapshot):
    assert repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})=='accepted'
    run,_=repo.claim();assert repo.finish(run,snapshot);return run.id

def test_idempotency_atomic_results(repo,examples,sessions):
    key=complete(repo,examples['Fed']);assert repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),2,'document.intelligence.v1',{})=='duplicate'
    with sessions() as s:
        for model in (ResearchInput,ResearchRun,ResearchResult,CandidateRecord,ComparisonRecord,OutboxEvent):assert s.scalar(select(func.count()).select_from(model))>=1
        assert s.scalar(select(func.count()).select_from(ResearchResult))==1
    assert repo.detail(key)['comparison']['flags']['fact_based']
def test_ruleset_isolation_and_redefinition_rejected(repo,examples,sessions,settings,rules):
    key=complete(repo,examples['Fed']);old=repo.detail(key);new=copy.deepcopy(rules);new['version']='2.1';other=Repository(sessions,settings,new);key2=complete(other,examples['Fed']);assert key!=key2;assert repo.detail(key)==old
    new['fact_mapping'][0]['event_type']='different.type'
    with pytest.raises(ValueError):other.register()
def test_conflicting_input_is_dead(repo,examples):
    key=complete(repo,examples['Fed']);bad=copy.deepcopy(examples['Fed']['intelligence']);bad['processing']['warnings'].append({'component':'input','code':'different'})
    assert repo.accept(json.dumps(bad).encode(),2,'document.intelligence.v1',{})=='dead';assert repo.view(key)
def test_expired_worker_cannot_commit(repo,examples,sessions):
    repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),1,'document.intelligence.v1',{});old,_=repo.claim()
    with sessions.begin() as s:s.get(ResearchRun,old.id).lease_until=utcnow()-timedelta(seconds=1)
    new,_=repo.claim();assert not repo.finish(old,examples['Fed']);assert repo.finish(new,examples['Fed'])
@pytest.mark.asyncio
async def test_outbox_retry(repo,examples,sessions):
    complete(repo,examples['Fed'])
    class Bus:
        fail=True
        async def publish(self,*args):
            if self.fail:raise ConnectionError()
    bus=Bus();pub=OutboxPublisher(sessions,bus,repo.output_contract);await pub.run_once()
    with sessions.begin() as s:
        row=s.scalar(select(OutboxEvent));assert row.status=='pending';row.next_attempt_at=utcnow()-timedelta(seconds=1)
    bus.fail=False;await pub.run_once()
    with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='published'
@pytest.mark.asyncio
async def test_v1_outage_retries_no_invented_baseline(repo,examples):
    repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),1,'document.intelligence.v1',{})
    class Down:
        async def snapshot(self,di):raise ConnectionError()
    await Worker(repo,Down()).run_once();assert repo.stats()['runs']=={'pending':1};assert repo.stats()['metrics']['documents_total']==0

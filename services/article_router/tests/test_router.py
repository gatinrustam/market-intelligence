import copy,json
from uuid import uuid4
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.domain import build_result,identity,digest
from app.schema import Output,LabelRequest
from app.storage.models import RoutingInput,RoutingRun,RoutingResult,ReviewItem,HumanLabel,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.outbox import OutboxPublisher

def result(examples,rules,name='Fed'):return build_result(examples[name]['intelligence'],examples[name],rules)
def complete(repo,snapshot):
    assert repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})=='accepted'
    run,di=repo.claim();assert repo.finish(run,snapshot)
    return run.id

def test_fed_rate_important(examples,rules):
    r=result(examples,rules);assert r['classification']['route']=='important';assert r['features']['macro_relevance']=='high';assert r['features']['high_value_fact_count']>=1

def test_generic_ecb_review(examples,rules):assert result(examples,rules,'Speech')['classification']['route']=='review'
def test_personnel_metadata_overrides_mistyped_canonical(examples,rules):
    examples['Personnel']['event_intelligence']=[{'basis':{'matched_rule_ids':['sec.personnel_announcement']},'novelty':'new','event_specificity':'general'}]
    assert result(examples,rules,'Personnel')['classification']['route']=='low'
def test_crypto_regulation_important_without_invented_fact(examples,rules):
    r=result(examples,rules,'Crypto');assert r['classification']['route']=='important';assert r['features']['crypto_relevance']=='high';assert r['features']['financial_fact_count']==0
@pytest.mark.parametrize('kind',['withdrawal_suspension','security_incident','stablecoin_depeg'])
def test_crypto_critical(examples,rules,kind):
    examples['Fed']['intelligence']['facts'][0]['fact_type']='crypto.'+kind
    assert result(examples,rules)['classification']['route']=='critical'
def test_official_source_independent_partial_quality(examples,rules):
    r=result(examples,rules,'Personnel');assert r['features']['source_quality']=='official_primary';assert r['features']['document_quality']=='low';assert r['features']['financial_fact_count']==0
@pytest.mark.parametrize('novelty,expected',[('duplicate_like','duplicate_like'),('update','supporting_update'),('new','new')])
def test_pinned_novelty(examples,rules,novelty,expected):
    examples['Fed']['event_intelligence']=[{'basis':{'matched_rule_ids':[]},'novelty':novelty,'event_specificity':'specific'}]
    assert result(examples,rules)['features']['novelty']==expected

def test_novelty_unknown_and_repeated(examples,rules):
    assert result(examples,rules)['features']['novelty']=='unknown'
    examples['Fed']['repeated_source_item']=True;assert result(examples,rules)['features']['novelty']=='repeated_source_item'
def test_length_alone_not_density(examples,rules):
    s=examples['Speech'];s['document']['content']['body']+='word '*10000;s['intelligence']['facts']=[];s['intelligence']['measurements']=[]
    assert result(examples,rules,'Speech')['features']['information_density']=='low'
def test_each_feature_explained_strict_schema(examples,rules,repo):
    r=result(examples,rules);repo.output_contract.validate(r);assert set(r['features'])==set(r['basis']['feature_basis'])
    r['features']['opaque_score']=1
    with pytest.raises(Exception):repo.output_contract.validate(r)
def test_duplicate_input_and_atomic_outbox(repo,examples,sessions):
    key=complete(repo,examples['Fed']);raw=json.dumps(examples['Fed']['intelligence']).encode()
    assert repo.accept(raw,2,'document.intelligence.v1',{})=='duplicate'
    with sessions() as s:
        for model in (RoutingInput,RoutingRun,RoutingResult,ReviewItem,OutboxEvent):assert s.scalar(select(func.count()).select_from(model))==1
        assert s.get(ReviewItem,key).status=='new'
def test_conflicting_input_dead(repo,examples):
    complete(repo,examples['Fed']);examples['Fed']['intelligence']['language_detector']='changed'
    assert repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),2,'document.intelligence.v1',{})=='dead'
def test_version_isolation_and_freeze(repo,examples,settings,sessions,rules):
    key=complete(repo,examples['Fed']);before=repo.view(key)
    new=copy.deepcopy(rules);new['version']='2.0';other=Repository(sessions,settings,new);other.register();key2=complete(other,examples['Fed'])
    assert key!=key2;assert repo.view(key)==before
    new['default_route']='archive'
    with pytest.raises(ValueError):other.register()
def test_labels_append_only_machine_preserved(repo,examples):
    key=complete(repo,examples['Fed']);before=repo.detail(key)
    body=LabelRequest(request_id=uuid4(),expected_revision=0,status='reviewed',reviewer='test',usefulness='useful',priority_override='critical',facts_correct=True,send_to_llm=True)
    assert repo.label(key,body)['revision']==1;assert repo.label(key,body)['revision']==1
    after=repo.detail(key);assert before['machine']==after['machine'];assert before['snapshot']==after['snapshot'];assert len(after['labels'])==1
    with pytest.raises(ValueError):repo.label(key,body.model_copy(update={'request_id':uuid4()}))
    with pytest.raises(ValueError):repo.label(key,body.model_copy(update={'comment':'changed'}))
    assert repo.label(key,body.model_copy(update={'request_id':uuid4(),'expected_revision':1,'status':'dismissed'}))['revision']==2
    assert len(repo.detail(key)['labels'])==2
@pytest.mark.asyncio
async def test_outbox_failure_then_recovery(repo,examples,sessions):
    key=complete(repo,examples['Fed'])
    class Bus:
        failed=True
        async def publish(self,*args):
            if self.failed:raise ConnectionError()
    bus=Bus();pub=OutboxPublisher(sessions,bus,repo.output_contract);await pub.run_once()
    with sessions.begin() as s:
        row=s.scalar(select(OutboxEvent));assert row.status=='pending';row.next_attempt_at=utcnow()-timedelta(seconds=1)
    bus.failed=False;await pub.run_once()
    with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='published'
    assert repo.view(key)
def test_stale_worker_cannot_finish(repo,examples,sessions):
    repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),1,'document.intelligence.v1',{})
    old,_=repo.claim()
    with sessions.begin() as s:s.get(RoutingRun,old.id).lease_until=utcnow()-timedelta(seconds=1)
    new,_=repo.claim();assert not repo.finish(old,examples['Fed']);assert repo.finish(new,examples['Fed'])

def test_archive_retains_service_notice(examples,rules):
    snapshot=examples['Personnel'];snapshot['document']['content']['title']='RSS feed maintenance notice'
    assert result(examples,rules,'Personnel')['classification']['route']=='archive'
def test_strong_fact_prevents_personnel_low(examples,rules):
    examples['Fed']['events'][0]['taxonomy']['event_type']='regulator.personnel'
    assert result(examples,rules)['classification']['route']=='important'
def test_new_di_identity_avoids_version_collision(examples,rules):
    di=examples['Fed']['intelligence'];first=identity(di,rules);di['intelligence_id']=str(uuid4())
    assert identity(di,rules)!=first
def test_concurrent_review_cannot_lose_update(repo,examples):
    from concurrent.futures import ThreadPoolExecutor
    key=complete(repo,examples['Fed'])
    def save(_):
        try:return repo.label(key,LabelRequest(request_id=uuid4(),expected_revision=0,status='reviewed',reviewer='concurrent'))['revision']
        except ValueError:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(save,range(2)))
    assert sorted(map(str,outcomes))==['1','conflict'];assert len(repo.detail(key)['labels'])==1


def test_russian_registry_revision_only_extends_source_quality(settings):
    from app.domain import load_configuration
    old=load_configuration(settings.model_copy(update={'rules_path':settings.rules_path.parent/'rules.v1.json'}))
    new=load_configuration(settings.model_copy(update={'rules_path':settings.rules_path.parent/'rules.v1.1.json'}))
    assert new['version']!=old['version']
    for source in ('cbr_events_ru','cbr_press_ru','moex_news_ru'):
        assert new['source_quality'][source]=='official_primary'
    assert {k:v for k,v in new.items() if k not in ('version','source_quality')}=={k:v for k,v in old.items() if k not in ('version','source_quality')}
    assert all(new['source_quality'][k]==v for k,v in old['source_quality'].items())


def test_crypto_promotions_retained_outside_high_value(examples,rules):
    snapshot=copy.deepcopy(examples['Fed']);snapshot['document']['source']['id']='binance_news'
    snapshot['document']['content']['title']='Earn rewards in our trading tournament'
    assert build_result(snapshot['intelligence'],snapshot,rules)['classification']['route']=='archive'
    snapshot['document']['content']['title']='New announcement'
    snapshot['document']['classification']={'categories':['crypto','content_hint:promotional']}
    assert build_result(snapshot['intelligence'],snapshot,rules)['classification']['route']=='archive'


def test_crypto_catalogue_metadata_and_incident_identity(repo,examples):
    snapshot=copy.deepcopy(examples['Fed']);snapshot['document']['source'].update(id='kraken_status_incidents',external_id='incident/abc/update/def/version')
    snapshot['document']['classification']={'categories':['crypto','exchange','incidents']}
    complete(repo,snapshot)
    row=repo.articles(0,10)['items'][0]
    assert row['incident_id']=='abc'
    assert row['source_metadata']['source_role']=='exchange'
    assert 'incidents' in row['categories']

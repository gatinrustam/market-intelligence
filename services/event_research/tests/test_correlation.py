import copy
import os
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import pytest
from sqlalchemy import select, func
from fastapi.testclient import TestClient
from app.correlation.domain import load_policy, fingerprint, correlate, projection, measurement
from app.correlation.repository import CorrelationRepository
from app.storage.models import CorrelationSuggestion, CorrelationCandidate, CorrelationDecision, CorrelationProcessed
from app.domain import build_result
from app.main import create_app
from tests.correlation_fixtures import rate, corpus

@pytest.fixture
def policy():return load_policy('/workspace/config/event_research/correlation.v1.json')
@pytest.fixture
def corr(sessions,policy):
    r=CorrelationRepository(sessions,policy);r.register();return r

def compare(a,b,p):return correlate(a,b,fingerprint(a,p),fingerprint(b,p),p)

def test_three_formulations_merge_with_revisions_and_provenance(corr):
    rows=corpus()['same_event'];first=corr.ingest([rows[0]])[0];before=copy.deepcopy(corr.revisions(first['event_id']))
    other=corr.ingest(rows[1:]);event=corr.events()[0]
    assert len(corr.events())==1 and event['document_count']==3 and event['independent_source_count']==2
    assert all(r['event_id']==first['event_id'] for r in other)
    assert event['revision']==3 and corr.revisions(first['event_id'])[:1]==before
    assert len(event['merge_decision_ids'])==3 and len(event['candidate_ids'])==3
    assert corr.stats()['exact_merges']==2
    detail=corr.for_document(rows[0]['document']['document_id'])[0]
    assert detail['document']==rows[0]['document']
    assert len(detail['decisions'])==2
    assert all('explicit_event_time' in d['matched_fields'] and d['ruleset_version'] for d in detail['decisions'])

@pytest.mark.parametrize('field,value,conflict',[
    ('value','4.25','measurements'),('date','2026-09-21T18:00:00Z','explicit_event_time'),
    ('type','central_bank.projections','event_type'),('action','cut','action'),('actor','organization:ecb','primary_actor')])
def test_conflicts_override_identical_titles(corr,field,value,conflict):
    a,b=rate('a'),rate('b')
    if field=='value':b['candidate']['measurements'][0]['measurement']['min']=value;b['candidate']['measurements'][0]['measurement']['max']='4.50'
    elif field=='date':b['candidate']['event_time']=value
    elif field=='type':b['candidate']['event_type']=value
    elif field=='action':b['facts'][0]['action']=value
    else:b['facts'][0]['primary_actor']=value
    corr.ingest([a,b]);assert len(corr.events())==2
    d=corr.decisions()[0];assert d['mode']=='separate' and conflict in d['conflicting_fields'] and d['features']['title_similarity']==1

def test_missing_date_suggestion_is_persisted_but_never_merged(corr,sessions):
    a,b=corpus()['missing_date'];corr.ingest([a,b]);assert len(corr.events())==2
    assert corr.decisions()[0]['mode']=='suggestion';assert not corr.decisions()[0]['auto_merge']
    with sessions() as s:assert s.scalar(select(func.count()).select_from(CorrelationSuggestion))==1

def test_same_actor_publication_and_title_do_not_establish_identity(corr):
    a,b=rate('a'),rate('b')
    for row in [a,b]:row['facts']=[];row['candidate']['measurements']=[];row['candidate']['classification_basis']='fallback_rule'
    corr.ingest([a,b]);assert corr.decisions()[0]['mode']=='insufficient_data';assert len(corr.events())==2

def test_unit_normalization_and_timezones(policy):
    a,b=rate('a'),rate('b',date='2026-09-20T20:00:00+02:00')
    b['candidate']['measurements'][0]['measurement'].update(unit='basis_points',min='350',max='375')
    assert compare(a,b,policy)['mode']=='exact_match'
    b['candidate']['measurements'][0]['measurement'].update(unit='fraction',min='0.035',max='0.0375')
    assert compare(a,b,policy)['mode']=='exact_match'

def test_rate_level_is_not_a_rate_change(policy):
    a,b=rate('a'),rate('b');b['candidate']['measurements'][0]['measurement'].update(kind='percentage_points',unit='pp')
    assert compare(a,b,policy)['mode']=='separate'

def test_unsupported_unit_and_unresolved_actor_cannot_merge(policy):
    a,b=rate('a'),rate('b');b['candidate']['measurements'][0]['measurement']['unit']='unknown'
    assert compare(a,b,policy)['mode']=='insufficient_data'
    b=rate('b');b['facts'][0]['primary_actor']=None
    assert compare(a,b,policy)['mode']=='insufficient_data'

def test_duplicate_is_idempotent_and_changed_payload_rejected(corr):
    a=rate('a');first=corr.ingest([a])[0];before=corr.events()
    assert corr.ingest([a])[0]['status']=='duplicate';assert corr.events()==before
    a['metadata']['title']='changed'
    with pytest.raises(ValueError):corr.ingest([a])
    assert corr.events()==before

def test_concurrent_first_exact_identity_has_one_event(corr):
    rows=corpus()['same_event'];barrier=Barrier(3)
    def accept(row):barrier.wait();return corr.ingest([row])[0]
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(accept,rows))
    assert len({r['event_id'] for r in results})==1
    assert corr.events()[0]['revision']==3 and corr.events()[0]['document_count']==3

def test_duplicate_document_does_not_inflate_source_count(corr):
    a,b,c=corpus()['same_event'];b['document']=copy.deepcopy(a['document']);b['candidate']['document_id']=a['document']['document_id'];b['metadata']['source']=a['metadata']['source']
    corr.ingest([a,b,c]);assert corr.events()[0]['document_count']==2 and corr.events()[0]['independent_source_count']==1

@pytest.mark.parametrize('field',['ruleset_version','fingerprint_version'])
def test_versions_are_isolated_and_old_revisions_immutable(corr,sessions,policy,field):
    rows=corpus()['same_event'];corr.ingest(rows);old=corr.events();new=copy.deepcopy(policy);new[field]+='_new'
    other=CorrelationRepository(sessions,new);other.register();other.ingest(rows)
    assert other.events()[0]['event_id']!=old[0]['event_id'];assert corr.events()==old
    new['publication_proximity_seconds']+=1
    with pytest.raises(ValueError):CorrelationRepository(sessions,new).register()

def test_other_extraction_ruleset_is_rejected(corr):
    a=rate('a');a['input_ruleset_version']='3.0'
    with pytest.raises(ValueError):corr.ingest([a])
    assert corr.events()==[]

def test_publication_change_does_not_change_fingerprint(policy):
    a=rate('a');b=copy.deepcopy(a);b['metadata']['published_at']='2027-01-01T00:00:00Z'
    assert fingerprint(a,policy)==fingerprint(b,policy)

def test_projection_preserves_linked_facts_and_excludes_full_text(examples,rules,policy):
    snapshot=examples['Fed'];result=build_result(snapshot['intelligence'],snapshot,rules)
    row=projection(result,snapshot)[0]
    assert row['facts'][0]['action']=='hold'
    assert row['facts'][0]['primary_actor']=='organization:federal_reserve'
    assert 'intelligence' not in row and 'body' not in row['metadata']
    assert row['candidate']==result['candidates'][0]
    assert not fingerprint(row,policy)['exact_key']
    result['basis']['input_hash']='wrong'
    with pytest.raises(ValueError):projection(result,snapshot)

def test_research_worker_keeps_v1_and_v2_snapshot_immutable(repo,corr,examples):
    snapshot=examples['Fed'];old=copy.deepcopy(snapshot)
    repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})
    run,_=repo.claim();repo.finish(run,snapshot);before=repo.detail(run.id)
    assert corr.run_once() and not corr.run_once()
    assert repo.detail(run.id)==before and snapshot==old
    assert corr.stats()['documents_processed']==1

@pytest.mark.parametrize('name,events,mode',[
    ('same_event',1,'exact_match'),('different_values',2,'separate'),('same_meeting_different_types',2,'separate'),
    ('sec_different_actions',2,'separate'),('missing_date',2,'suggestion')])
def test_requested_synthetic_corpus(corr,name,events,mode):
    corr.ingest(corpus()[name]);assert len(corr.events())==events;assert all(d['mode']==mode for d in corr.decisions())
    if os.getenv('CORRELATION_FIXTURE_REPORT'):
        path=Path(os.environ['CORRELATION_FIXTURE_REPORT']);path.mkdir(exist_ok=True,parents=True)
        (path/(name+'.json')).write_text(json.dumps({'synthetic':True,'name':name,'inputs':corpus()[name],
            'events':corr.events(),'decisions':corr.decisions(),'stats':corr.stats()},ensure_ascii=False,indent=2))

def test_api_is_read_only_and_exposes_history(settings,sessions,corr):
    row=rate('api');corr.ingest([row]);app=create_app(settings)
    with TestClient(app) as client:
        assert client.get('/correlation/stats').json()['documents_processed']==1
        data=client.get('/documents/'+row['document']['document_id']+'/correlation').json()
        eid=data[0]['event']['event_id']
        assert len(client.get('/correlation/events/'+eid+'/revisions').json())==1
        assert client.get('/correlation/decisions?mode=invalid').status_code==422
        assert client.post('/correlation/events',json={}).status_code==405
        assert client.get('/correlation/events/00000000-0000-4000-8000-000000000000/revisions').status_code==404

def test_date_only_conflict_blocks_suggestion(policy):
    a,b=rate('a',date=None),rate('b',date=None)
    a['candidate']['dates']=[{'date':{'kind':'date','normalized':'2026-04-29'}}]
    b['candidate']['dates']=[{'date':{'kind':'date','normalized':'2026-09-20'}}]
    d=compare(a,b,policy)
    assert d['mode']=='separate' and 'explicit_dates' in d['conflicting_fields']

def test_exact_time_with_ambiguous_linked_dates_fails_closed(policy):
    a,b=rate('a'),rate('b')
    for row in [a,b]:row['candidate']['dates']=[{'date':{'kind':'date','normalized':'2026-01-01'}}]
    assert compare(a,b,policy)['mode']=='insufficient_data'

def test_processed_document_without_candidates_is_counted(repo,corr,examples):
    snapshot=copy.deepcopy(examples['Fed'])
    snapshot['intelligence']['facts']=[]
    snapshot['metadata'].update(title='',body_length=0)
    repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})
    run,_=repo.claim();repo.finish(run,snapshot)
    assert corr.run_once() and not corr.run_once()
    assert corr.stats()['documents_processed']==1 and corr.stats()['events_before_correlation']==0

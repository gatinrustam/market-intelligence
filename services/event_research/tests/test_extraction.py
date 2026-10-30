import copy,json
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from app.domain import build_result,comparison,digest,identity,validate_links
from app.schema import Output
CLOCK=lambda:datetime(2026,9,20,tzinfo=timezone.utc)
def extract(s,r):return build_result(s['intelligence'],s,r,clock=CLOCK)
def test_fact_overrides_title_and_conflict_is_explicit(examples,rules):
    s=examples['Proposal'];s['metadata']['title']='SEC Charges Company';s['v1_basis']=[{'event_type':'regulator.enforcement','classification_basis':'exact_rule','rule_ids':['sec.enforcement']}]
    p=extract(s,rules);assert p['candidates'][0]['event_type']=='regulator.rule_proposal';assert p['candidates'][0]['classification_basis']=='primary_fact'
    assert p['conflicts'][0]['kind']=='classification_conflict';assert {a['event_type'] for a in p['conflicts'][0]['alternatives']}=={'regulator.enforcement','regulator.rule_proposal'}
@pytest.mark.parametrize('name,typ',[('Fed','central_bank.policy_statement'),('Proposal','regulator.rule_proposal'),('Enforcement','regulator.enforcement')])
def test_primary_fact_mapping(examples,rules,name,typ):
    s=examples[name];p=extract(s,rules);assert p['candidates'][0]['event_type']==typ;assert p['candidates'][0]['primary_fact_ids'];assert p['candidates'][0]['fact_references'][0]['extraction']['extractor_version']=='1.0'
@pytest.mark.parametrize('name,typ',[('Projections','central_bank.projections'),('Speech','central_bank.speech'),('Interview','central_bank.interview'),('Crypto','regulator.rule_proposal')])
def test_fallback_without_facts(examples,rules,name,typ):
    p=extract(examples[name],rules);assert p['candidates'][0]['event_type']==typ;assert p['candidates'][0]['classification_basis']=='fallback_rule';assert p['candidates'][0]['primary_fact_ids']==[];assert p['candidates'][0]['measurements']==[]
def test_personnel_corrected_by_rule_not_labels(examples,rules):
    p=extract(examples['Personnel'],rules);assert p['candidates'][0]['event_type']=='regulator.personnel';assert p['conflicts'];assert p['candidates'][0]['classification_basis']=='fallback_rule'
def test_multiple_fact_types_not_merged(examples,rules):
    s=examples['Fed'];f=copy.deepcopy(s['intelligence']['facts'][0]);f['fact_id']=str(uuid4());f['fact_type']='economic_data.inflation';s['intelligence']['facts'].append(f)
    p=extract(s,rules);assert {c['event_type'] for c in p['candidates']}=={'central_bank.policy_statement','central_bank.data_release'};assert len({c['candidate_id'] for c in p['candidates']})==2
    assert comparison(p,s)['flags']['multiple_candidates']
def test_measurements_only_linked_to_fact(examples,rules):
    s=examples['Fed'];p=extract(s,rules);actual={m['measurement']['measurement_id'] for c in p['candidates'] for m in c['measurements']};expected={m['measurement_id'] for f in s['intelligence']['facts'] for m in f['values']}
    assert actual==expected;assert len(actual)<len(s['intelligence']['measurements'])
def test_unresolved_entities_keep_di_id(examples,rules):
    s=examples['Proposal'];p=extract(s,rules);actors=p['candidates'][0]['actors'];unresolved=[a for a in actors if a['resolution']=='unresolved'];assert unresolved
    assert all(any(e['entity_id']==a['entity_id'] and not e['registry'] for e in s['intelligence']['entities']) for a in unresolved)
def test_event_time_not_publication_or_date_only(examples,rules):
    p=extract(examples['Fed'],rules);assert all(c['event_time'] is None and c['event_time_basis']=='unavailable' for c in p['candidates'])
    assert examples['Fed']['metadata']['published_at']
def test_explicit_linked_datetime_only(examples,rules):
    s=examples['Fed'];f=s['intelligence']['facts'][0]
    s['intelligence']['dates']=[{'date_id':str(uuid4()),'kind':'date','raw':f['evidence']['text'],'normalized':'2026-04-29T18:00:00Z','evidence':f['evidence'],'extraction':f['extraction']}]
    assert extract(s,rules)['candidates'][0]['event_time']=='2026-04-29T18:00:00Z'
    s['intelligence']['dates'][0]['evidence']=copy.deepcopy(f['evidence']);s['intelligence']['dates'][0]['evidence']['sentence_id']+=1
    assert extract(s,rules)['candidates'][0]['event_time'] is None

def test_no_event_for_rejected_empty_document(examples,rules):
    s=examples['Speech'];s['metadata']['document_status']='rejected';s['metadata']['title']='';s['metadata']['body_length']=0
    p=extract(s,rules);assert p['candidates']==[];assert comparison(p,s)['flags']['no_event']
def test_forward_looking_fact_not_asserted_event(examples,rules):
    s=examples['Fed'];s['intelligence']['relations'][0]['modality']='forward_looking';p=extract(s,rules)
    assert p['candidates'][0]['classification_basis']=='fallback_rule';assert p['basis']['ignored_facts']
def test_invalid_fact_link_fails_closed(examples):
    s=examples['Fed'];s['intelligence']['facts'][0]['values'][0]['value']='999'
    with pytest.raises(ValueError):validate_links(s['intelligence'])
def test_human_labels_evaluation_only(examples,rules):
    s=examples['Personnel'];before=extract(s,rules)
    s['human_reviews']=[{'routing_id':str(uuid4()),'reviewed_v1_types':['regulator.enforcement'],'labels':[{'request_id':str(uuid4()),'revision':1,'event_type_correct':False,'facts_correct':True,'comment':'review test'}]}]
    after=extract(s,rules);assert before==after
    evaluation=comparison(after,s)['human_evaluation'][0];assert evaluation['v2_differs_from_v1'];assert evaluation['v2_conflict_visible'];assert evaluation['scope']=='evaluation_only_not_ground_truth'
def test_v1_snapshot_unchanged(examples,rules):
    s=examples['Fed'];before=copy.deepcopy(s);extract(s,rules);assert before==s

def test_strict_schema_and_no_full_body(examples,rules,repo):
    p=extract(examples['Fed'],rules);repo.output_contract.validate(p)
    assert 'body' not in p['document'];p['candidates'][0]['invented_score']=1
    with pytest.raises(Exception):repo.output_contract.validate(p)
def test_crypto_mapping(examples,rules):
    s=examples['Fed'];s['intelligence']['facts'][0]['fact_type']='crypto.withdrawal_suspension'
    assert extract(s,rules)['candidates'][0]['event_type']=='market_infrastructure.withdrawal_suspension'

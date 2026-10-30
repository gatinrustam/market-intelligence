import copy,json
import pytest
from app.domain import chunk_document,build_result,insight,identity,digest
from app.schema import Output
from app.storage.contract import Contract
from conftest import observation

@pytest.mark.parametrize('body',['Первое предложение. Второе!\n\nАбзац с ё и emoji 🚀.  ','  Leading whitespace\n\n  sentence. trailing  ','x'*1701,''])
def test_chunking_is_lossless_nonoverlapping_and_bounded(body):
    chunks=chunk_document('11111111-1111-4111-8111-111111111111',body,[{'sentence_id':0,'start_char':0,'end_char':len(body)}] if body else [],48,len)
    assert ''.join(c['text'] for c in chunks)==body
    assert all(c['text']==body[c['start_char']:c['end_char']] and c['token_count']<=48 for c in chunks)
    assert all(a['end_char']==b['start_char'] for a,b in zip(chunks,chunks[1:]))
    assert chunks==chunk_document('11111111-1111-4111-8111-111111111111',body,[{'sentence_id':0,'start_char':0,'end_char':len(body)}] if body else [],48,len)

def test_di_facts_have_priority_and_exact_evidence(examples,configuration,settings):
    snapshot=examples['Fed'];o=observation(snapshot);r=build_result(snapshot['intelligence'],snapshot,configuration,o)
    assert r['facts']==snapshot['intelligence']['facts'];assert r['article_type']=='primary_announcement'
    assert r['claims'][0]['extractor']=='di'
    body=snapshot['document']['content']['body']
    for claim in r['claims']:
        e=claim['evidence'];assert body[e['start_char']:e['end_char']]==e['text']
    assert all('text' not in c for c in r['chunks']) and 'body' not in r['document']
    Contract(settings.contracts_dir/'article/semantic/v1.schema.json').validate(r)
    invalid=copy.deepcopy(r);invalid['body']=body
    with pytest.raises(Exception):Output.model_validate(invalid)

def test_semantic_conflict_retains_both_layers(examples,configuration):
    s=examples['Fed'];r=build_result(s['intelligence'],s,configuration,observation(s,'personnel'))
    assert r['article_type']=='primary_announcement' and r['conflicts'][0]['status']=='conflict'
    assert r['facts']==s['intelligence']['facts'] and r['semantic_concepts'][0]['concept_id']=='personnel'

@pytest.mark.parametrize('bge,gliner,status',[(False,True,'failed'),(True,False,'partial')])
def test_failure_keeps_di_available(examples,configuration,bge,gliner,status):
    s=examples['Fed'];o=observation(s,bge=bge,gliner=gliner);r=build_result(s['intelligence'],s,configuration,o)
    assert r['status']==status and r['facts']==s['intelligence']['facts']
    assert r['routing']['production_switch'] is False

def test_below_threshold_matches_are_audit_only(examples,configuration):
    s=examples['Personnel'];r=build_result(s['intelligence'],s,configuration,observation(s,'crypto_exchange',.1))
    assert r['semantic_concepts']==[] and r['affected_assets']==[]

def test_bitcoin_mention_without_semantic_context_does_not_assign_btc(examples,configuration):
    s=examples['Crypto'];r=build_result(s['intelligence'],s,configuration,observation(s,'administrative'))
    assert not any(a['asset']=='BTC' for a in r['affected_assets'])

def test_assets_have_evidence_and_model_similarity_not_probability(examples,configuration):
    s=examples['Fed'];r=build_result(s['intelligence'],s,configuration,observation(s))
    assert {a['asset'] for a in r['affected_assets']}=={'rates','USD'}
    assert all(a['evidence'] and a['basis'] for a in r['affected_assets'])
    assert 'similarity' in r['top_matches'][0] and 'probability' not in r['top_matches'][0]
    assert set(r['information_value'])=={'market_relevance','crypto_relevance','macro_relevance','event_specificity','information_density','actionability','source_quality','document_quality','semantic_strength','fact_support'}
    assert all(f['reasons'] for f in r['information_value'].values())

def test_title_alone_cannot_create_article_type(examples,configuration):
    s=examples['Personnel'];s['document']['content']['title']='Interview: Bitcoin hack'
    r=build_result(s['intelligence'],s,configuration,observation(s,similarity=.1))
    assert r['article_type']=='unknown'

def test_partial_document_is_never_claimed_as_full_article(examples,configuration):
    s=examples['Crypto'];r=build_result(s['intelligence'],s,configuration,observation(s,'crypto_regulation'))
    assert r['document']['body_characters']==len(s['document']['content']['body'])
    assert r['status']=='partial';assert any('partial/RSS' in x for x in r['warnings'])

def test_version_changes_identity_and_provenance(examples,configuration):
    di=examples['Fed']['intelligence'];new=copy.deepcopy(configuration);new['version']='semantic_pipeline_test_rerun'
    assert identity(di,new)!=identity(di,configuration)
    r=build_result(di,examples['Fed'],configuration,observation(examples['Fed']))
    assert r['provenance']['semantic_model_revision']==configuration['models']['bge']['revision']
    assert insight(r)['semantic_id']==r['semantic_id']

def test_gliner_relation_requires_named_subject_before_explicit_predicate(examples,configuration):
    s=copy.deepcopy(examples['Personnel']);body='Acme acquired Beta in a cash transaction.'
    s['document']['content']['body']=body
    for name in ('entities','facts','relations','measurements','dates','topics'):s['intelligence'][name]=[]
    s['intelligence']['sentences']=[{'sentence_id':0,'start_char':0,'end_char':len(body)}]
    o=observation(s,'merger_acquisition')
    o['entities']=[{'start_char':0,'end_char':4,'label':'company','score':.9},
        {'start_char':14,'end_char':18,'label':'company','score':.85}]
    r=build_result(s['intelligence'],s,configuration,o)
    relation=r['relations'][0]
    assert relation['subject']=='Acme' and relation['object']=='Beta' and relation['predicate']=='acquired'
    assert relation['extractor']=='gliner' and relation['confidence']==.85 and relation['status']=='candidate'
    assert r['claims'][0]['evidence']['text']==body
    o['entities']=o['entities'][1:]
    r=build_result(s['intelligence'],s,configuration,o)
    assert r['relations']==[]

def test_full_claim_policy_keeps_late_relation_object_in_evidence(examples,configuration):
    s=copy.deepcopy(examples['Personnel']);body='Acme '+('very '*150)+'acquired Beta in a cash transaction.'
    s['document']['content']['body']=body
    for name in ('entities','facts','relations','measurements','dates','topics'):s['intelligence'][name]=[]
    s['intelligence']['sentences']=[{'sentence_id':0,'start_char':0,'end_char':len(body)}]
    o=observation(s,'merger_acquisition');start=body.index('Beta')
    o['entities']=[{'start_char':0,'end_char':4,'label':'company','score':.9},{'start_char':start,'end_char':start+4,'label':'company','score':.9}]
    configuration['claim_excerpt_limit']=None
    result=build_result(s['intelligence'],s,configuration,o)
    assert result['relations'][0]['evidence']['text']==body
    assert result['claims'][0]['evidence']['text']==body

def test_named_asset_needs_supported_relation_not_just_topic_and_mention(examples,configuration):
    s=copy.deepcopy(examples['Personnel']);body='Acme acquired Bitcoin for corporate reserves.'
    s['document']['content']['body']=body
    for name in ('entities','facts','relations','measurements','dates','topics'):s['intelligence'][name]=[]
    s['intelligence']['sentences']=[{'sentence_id':0,'start_char':0,'end_char':len(body)}]
    o=observation(s,'treasury_purchase');o['entities']=[{'start_char':14,'end_char':21,'label':'cryptocurrency','score':.9}]
    r=build_result(s['intelligence'],s,configuration,o)
    assert 'BTC' not in {a['asset'] for a in r['affected_assets']}
    o['entities'].append({'start_char':0,'end_char':4,'label':'company','score':.9})
    r=build_result(s['intelligence'],s,configuration,o)
    assert 'BTC' in {a['asset'] for a in r['affected_assets']}

def test_explicit_interview_format_does_not_erase_di_facts(examples,configuration):
    s=copy.deepcopy(examples['Fed']);original=s['document']['content']['body'];prefix='- INTERVIEW\n'
    # Replace a same-length metadata prefix so original fact offsets stay valid.
    s['document']['content']['body']=prefix+original[len(prefix):]
    r=build_result(s['intelligence'],s,configuration,observation(s))
    assert r['article_type']=='interview'
    assert r['facts']==s['intelligence']['facts']

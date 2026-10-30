import copy,json
import pytest
from app.domain import build_result,load_configuration,chunk_document
from app.reranking import useful_sentence
from conftest import observation

def precision(settings):return load_configuration(settings)

def rewritten(examples,body):
    s=copy.deepcopy(examples['Fed']);s['document']['content']['title']='Research document';s['document']['content']['body']=body
    d=s['intelligence']
    for key in ('facts','entities','relations','measurements','topics','dates'):d[key]=[]
    d['sentences']=[{'sentence_id':0,'start_char':0,'end_char':len(body),'text':body}]
    return s

def test_fed_etf_false_positive_rejected_even_with_high_cosine(settings,examples):
    s=examples['Fed'];o=observation(s,'etf',.99)
    r=build_result(s['intelligence'],s,precision(settings),o)
    assert r['reranking']['status']=='complete'
    assert 'etf' not in {x['concept_id'] for x in r['semantic_concepts']}
    assert next(d for d in r['reranking']['decisions'] if d['concept_id']=='etf')['decision']=='rejected'
    assert r['facts']==s['intelligence']['facts']

@pytest.mark.parametrize('cid',['crypto_exchange','exchange_outage','institutional_crypto','treasury_purchase'])
def test_cash_and_lagarde_context_does_not_create_crypto_links(settings,examples,cid):
    s=rewritten(examples,'The ECB discusses the digital euro and the legal tender status of banknotes. Cash remains available to everyone.')
    r=build_result(s['intelligence'],s,precision(settings),observation(s,cid,.9))
    assert r['reranking']['status']=='complete'
    assert cid not in {x['concept_id'] for x in r['semantic_concepts']}
    assert 'crypto_market' not in {x['asset'] for x in r['affected_assets']}

def test_negative_examples_can_reject_a_positive_hit(settings,examples):
    s=rewritten(examples,'The SEC proposed new regulation of crypto assets and investment contracts.')
    o=observation(s,'crypto_regulation',.75)
    for m in o['matches']:m.update(positive_similarity=.75,negative_similarity=.8,semantic_margin=-.05)
    r=build_result(s['intelligence'],s,precision(settings),o)
    decision=next(x for x in r['reranking']['decisions'] if x['concept_id']=='crypto_regulation')
    assert decision['decision']=='rejected' and decision['summary']['negative_evidence']

def test_one_weak_topic_without_entity_or_relation_is_review(settings,examples):
    s=rewritten(examples,'The commentary discusses inflation and its uncertain consequences for the economy.')
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'inflation',.53))
    decision=next(x for x in r['reranking']['decisions'] if x['concept_id']=='inflation')
    assert decision['decision']=='review'
    assert r['routing']['semantic_suggested_route']!='important'

@pytest.mark.parametrize('text',['What do you say to economists who argue that interest rates are too high?', 'Detailed information: Smith et al., Journal of Economics, Issue 2, 2025.', 'Follow us on our social media accounts for important updates.'])
def test_nonclaims_filtered(text):
    assert useful_sentence({'sentence_id':0,'start_char':0,'end_char':len(text)},text,'')[0] is None

def test_sentence_type_does_not_leak_from_inflation_chunk(settings,examples):
    s=rewritten(examples,'The company has reported revenue of 123 million dollars for the latest financial year.')
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'inflation',.9))
    assert all(cl['type']!='inflation' for cl in r['claims'])

def test_reranker_failure_keeps_base_facts(settings,examples,monkeypatch):
    import app.reranking
    def broken(*args):raise RuntimeError('fault injection')
    monkeypatch.setattr(app.reranking,'rerank',broken)
    s=examples['Fed'];r=build_result(s['intelligence'],s,precision(settings),observation(s))
    assert r['reranking']['status']=='failed' and r['facts']==s['intelligence']['facts'] and r['claims']
    assert 'reranker_failed:RuntimeError' in r['warnings']

def test_frozen_rerank_replay_is_equal_including_recorded_timing(settings,examples):
    s=examples['Fed'];o=observation(s);o['reranking_seconds']=.123
    r=build_result(s['intelligence'],s,precision(settings),o);replay=build_result(s['intelligence'],s,precision(settings),o)
    replay['generated_at']=r['generated_at'];assert replay==r
    assert r['reranking']['latency_seconds']==.123

def test_baseline_storage_is_immutable_and_reranking_separate(settings,sessions,examples):
    from app.storage.repository import Repository
    c=precision(settings);repo=Repository(sessions,settings,c);repo.register();s=examples['Fed'];o=observation(s);o['baseline_matches']=copy.deepcopy(o['matches'])
    first=repo.ensure_baseline(s['intelligence'],s,o);o['matches']=[]
    assert repo.ensure_baseline(s['intelligence'],s,o)==first
    snapshot={**s,'baseline':first};new=build_result(s['intelligence'],snapshot,c,observation(s))
    assert new['comparison']['baseline_id']==first['semantic_id']
    assert new['semantic_id']!=first['semantic_id'] and repo.view(first['semantic_id'])==first


def test_precision_replay_is_stable_across_python_hash_seeds(settings,examples,tmp_path):
    import os,subprocess,sys
    s=copy.deepcopy(examples['Fed']);c=precision(settings);o=observation(s)
    s['baseline']=build_result(s['intelligence'],s,c['baseline_configuration'],o)
    path=tmp_path/'replay.json';path.write_text(json.dumps({'snapshot':s,'configuration':c,'observed':o}))
    code="import json,sys;from app.domain import build_result,digest;x=json.load(open(sys.argv[1]));s=x['snapshot'];r=build_result(s['intelligence'],s,x['configuration'],x['observed']);assert r['reranking']['status']=='complete';r['generated_at']='fixed';print(digest(r))"
    outputs=[subprocess.check_output([sys.executable,'-c',code,str(path)],env={**os.environ,'PYTHONHASHSEED':str(seed)}) for seed in (1,2,42)]
    assert len(set(outputs))==1


def test_moex_bond_issuer_ao_is_not_equity_evidence(settings,examples):
    s=rewritten(examples,'Московская Биржа решила приостановить торги облигациями АО Банк Пример в соответствии с правилами листинга.')
    s['document']['source']['id']='moex_news_ru';s['document']['content']['language']='ru';s['intelligence']['language']='ru'
    # Explicit canonical organization allows the trading-suspension concept;
    # the legal suffix АО must not manufacture an equity market link.
    s['intelligence']['entities']=[{'entity_id':'test-org','canonical_name':'Московская Биржа','type':'organization','evidence':{'start_char':0,'end_char':16}}]
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'trading_suspension',.95))
    assert r['reranking']['status']=='complete'
    assert 'RU_equities' not in {x['asset'] for x in r['affected_assets']}


def test_banknote_inventory_is_not_us_equity_exposure(settings,examples):
    s=rewritten(examples,'For instance, in addition to logistical stocks to meet demand for banknotes under normal circumstances, we hold a strategic contingency stock for use when demand for banknotes unexpectedly increases.')
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'cash_policy',.9))
    assert r['reranking']['status']=='complete'
    assert 'US_equities' not in {a['asset'] for a in r['affected_assets']}


def test_explicit_united_states_stock_market_evidence_is_retained(settings,examples):
    s=rewritten(examples,'ECB staff warned of a hypothetical AI-related stock market correction in the United States.')
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'equities',.9))
    assert 'US_equities' in {a['asset'] for a in r['affected_assets']}


def test_speech_metadata_removed_but_exact_body_offsets_retained():
    text='The future of cash\nKeynote speech by Jane Doe\nBrussels, 14 September 2026\nMore than 31 billion euro banknotes are in circulation today.'
    clean,reason=useful_sentence({'sentence_id':0,'start_char':0,'end_char':len(text)},text,'Jane Doe: The future of cash')
    assert reason is None and clean['text']=='More than 31 billion euro banknotes are in circulation today.'
    assert text[clean['start_char']:clean['end_char']]==clean['text']


def test_speech_outline_not_a_key_claim():
    text='In my remarks today, I would like to explain why safeguarding the role of cash matters.'
    assert useful_sentence({'sentence_id':0,'start_char':0,'end_char':len(text)},text,'')[0] is None


def test_personnel_pattern_does_not_match_purpose(settings):
    import re
    rule=precision(settings)['reranking']['concepts']['personnel']['anchors']
    assert not re.search(rule,'Его предназначение показать сценарий политики.',re.I)
    assert re.search(rule,'Банк России назначил нового директора.',re.I)


def test_open_day_does_not_turn_educational_rate_mentions_into_market_event(settings,examples):
    s=rewritten(examples,'Банк России откроет свои двери. День открытых дверей поможет узнать, как изменение ключевой ставки влияет на инфляцию.')
    s['document']['content']['title']='Банк России откроет свои двери';s['intelligence']['language']='ru'
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'interest_rates',.99))
    assert r['reranking']['status']=='complete' and r['article_type']=='administrative'
    assert r['routing']['semantic_suggested_route']=='low' and r['affected_assets']==[]
    assert not {'interest_rates','inflation'}&{x['concept_id'] for x in r['semantic_concepts']}


def test_futures_on_foreign_shares_not_mapped_to_russian_equities(settings,examples):
    s=rewritten(examples,'Московская Биржа изменила риск-параметры на срочном рынке для фьючерсных контрактов на акции зарубежных компаний.')
    s['document']['source']['id']='moex_news_ru';s['intelligence']['language']='ru'
    s['intelligence']['entities']=[{'entity_id':'test-org','canonical_name':'Московская Биржа','type':'organization','evidence':{'start_char':0,'end_char':16}}]
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'risk_parameters',.95))
    assert r['reranking']['status']=='complete' and all(x['asset']!='RU_equities' for x in r['affected_assets'])


def test_split_futures_table_cannot_create_equity_link_in_later_sentence(settings,examples):
    body='На срочном рынке изменены параметры фьючерсных контрактов. Московская Биржа изменила риск-параметры на акции иностранных компаний.'
    s=rewritten(examples,body);split=body.index('Московская')
    s['document']['source']['id']='moex_news_ru';s['intelligence']['language']='ru'
    s['intelligence']['sentences']=[{'sentence_id':0,'start_char':0,'end_char':split,'text':body[:split]},{'sentence_id':1,'start_char':split,'end_char':len(body),'text':body[split:]}]
    s['intelligence']['entities']=[{'entity_id':'test-org','canonical_name':'Московская Биржа','type':'organization','evidence':{'start_char':split,'end_char':split+16}}]
    r=build_result(s['intelligence'],s,precision(settings),observation(s,'risk_parameters',.95))
    assert r['reranking']['status']=='complete' and all(a['asset']!='RU_equities' for a in r['affected_assets'])


def test_crypto_ontology_additive_and_bilingual(settings):
    c=precision(settings)
    old=load_configuration(settings,'policy.precision.v5.frozen.json')
    current={x['id']:x for x in c['ontology']['concepts']}
    for concept in old['ontology']['concepts']:
        assert current[concept['id']]==concept
    for key in ('exchange_listing','exchange_delisting','deposit_suspension','corporate_btc_purchase','corporate_btc_sale','corporate_btc_holdings','crypto_derivatives','custody'):
        assert current[key]['descriptions']['en'] and current[key]['descriptions']['ru']
        assert key in c['reranking']['concepts']


def test_crypto_promotional_hint_caps_semantic_route(settings,examples):
    s=copy.deepcopy(examples['Fed'])
    s['document']['source']['id']='binance_news'
    s['document']['classification']={'categories':['crypto','content_hint:promotional']}
    r=build_result(s['intelligence'],s,precision(settings),observation(s))
    assert r['reranking']['status']=='complete'
    assert r['routing']['semantic_suggested_route']=='archive'
    assert r['information_value']['market_relevance']['level']=='low'


def test_crypto_product_fact_is_not_labelled_as_an_outage(settings,examples):
    snapshot=copy.deepcopy(examples['Fed'])
    snapshot['intelligence']['facts']=[snapshot['intelligence']['facts'][0]]
    snapshot['intelligence']['facts'][0]['fact_type']='crypto.stablecoin_change'
    result=build_result(snapshot['intelligence'],snapshot,precision(settings),observation(snapshot))
    assert result['reranking']['status']=='complete'
    assert result['article_type']=='primary_announcement'

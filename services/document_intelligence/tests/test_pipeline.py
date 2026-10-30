import copy
import pytest
from app.pipeline import validate_spans
from app.schema import Output
from app.storage.contract import Contract

@pytest.mark.parametrize('text,language,kind,action',[
 ('The Federal Reserve kept the federal funds target range unchanged at 5.25% to 5.50%.','en','monetary_policy.rate_decision','hold'),
 ('The SEC charged Example Corp with securities fraud.','en','regulation.enforcement','charge'),
 ('Binance temporarily suspended Bitcoin withdrawals.','en','crypto.withdrawal_suspension','suspend'),
 ('ФРС сохранила процентную ставку на уровне 5,25–5,50%.','ru','monetary_policy.rate_decision','hold'),
 ('Биржа Binance временно приостановила вывод биткоина.','ru','crypto.withdrawal_suspension','suspend'),
 ('SEC предъявила обвинения компании Пример.','ru','regulation.enforcement','charge'),
])
def test_required_bilingual_fixtures(pipeline,document,settings,text,language,kind,action):
    doc=document(text);out=pipeline.analyze(doc)
    assert out['language']==language
    assert any(f['fact_type']==kind and f['action']==action for f in out['facts'])
    validate_spans(out,text);Contract(settings.contracts_dir/'document/intelligence/v1.schema.json').validate(out)
    assert out==pipeline.analyze(doc)
    if action=='hold':assert out['facts'][0]['values'][0]['min']=='5.25' and out['facts'][0]['values'][0]['max']=='5.50'

@pytest.mark.parametrize('text',[
 'Bitcoin was mentioned during an unrelated conference.',
 'The company did not suspend withdrawals.',
 'Binance did not suspend Bitcoin withdrawals.',
 'Binance never suspended Bitcoin withdrawals.',
 'Биржа Binance не приостановила вывод биткоина.',
 'If Binance suspended Bitcoin withdrawals, users would notice.',
 'The Federal Reserve may lower interest rates.',
 'The Federal Reserve did not decide to lower interest rates.',
])
def test_negation_incidental_and_hypothetical_are_not_facts(pipeline,document,text):
    out=pipeline.analyze(document(text));assert out['facts']==[] and out['topics']==[]
    assert not any(k in out for k in ('relevance','send_to_astra','signal'))

def test_missing_rate_is_not_invented(pipeline,document):
    out=pipeline.analyze(document('The Federal Reserve kept interest rates unchanged.'))
    assert out['facts'][0]['action']=='hold' and out['facts'][0]['values']==[]

@pytest.mark.parametrize('text,expected',[
 ('The rate changed by 25 basis points.','0.25'),('The rate changed by 25 bps.','0.25'),
 ('Ставка изменилась на 25 б.п.','0.25'),('The rate changed by 0.25 percentage points.','0.25'),('Ставка изменилась на 0,25 п.п.','0.25'),
 ('The rate changed by 1/4 percentage point.','0.25'),
])
def test_normalized_rate_changes(pipeline,document,text,expected):
    out=pipeline.analyze(document(text));assert len(out['measurements'])==1
    assert out['measurements'][0]['value']==expected and out['measurements'][0]['unit']=='percentage_points'

def test_unicode_fraction_original_offsets(pipeline,document):
    text='The Federal Reserve kept interest rates at 3‑1/2 to 3‑3/4 percent.'
    out=pipeline.analyze(document(text));assert out['measurements'][0]['min']=='3.5' and out['measurements'][0]['max']=='3.75'
    validate_spans(out,text)

def test_money_quantity_price_ratio_dates_no_inferred_year(pipeline,document):
    out=pipeline.analyze(document('Coinbase purchased 25 BTC for USD 500 million on April 29, 2026. The price was $1,000. The ratio was 2:1 on May 5 at 18:30 UTC during Q2 2026.'))
    assert {m['kind'] for m in out['measurements']}=={'quantity','money','price','ratio'}
    assert any(m['value']=='500000000' for m in out['measurements'])
    assert any(d['normalized']=='2026-04-29' for d in out['dates'])
    assert any(d['raw']=='May 5' and d['normalized'] is None for d in out['dates'])
    assert any(d['kind']=='time' for d in out['dates'])

def test_unsupported_language_preserves_processing_result(pipeline,document):
    out=pipeline.analyze(document('La banque centrale européenne a décidé de maintenir les taux directeurs inchangés afin de préserver la stabilité des prix.'))
    assert out['language']=='unsupported' and out['processing']['status']=='unsupported' and out['facts']==[]

def test_partial_component_preserves_entities_and_measurements(pipeline,document,monkeypatch):
    def fail(*a):raise RuntimeError('optional rule failed')
    monkeypatch.setattr(pipeline.components['relations'],'extract',fail)
    out=pipeline.analyze(document('The Federal Reserve kept interest rates at 5%.'))
    assert out['processing']['status']=='partial' and out['entities'] and out['measurements']
    assert out['facts']==[] and out['processing']['warnings']==[{'component':'relations','code':'RuntimeError'}]

def test_strict_schema_and_exact_span_tamper(pipeline,document,settings):
    doc=document('The Federal Reserve kept interest rates unchanged.');out=pipeline.analyze(doc)
    bad=copy.deepcopy(out);bad['facts'][0]['evidence']['text']='invented'
    with pytest.raises(ValueError):validate_spans(bad,doc['content']['body'])
    bad=copy.deepcopy(out);del bad['entities'][0]['extraction']
    with pytest.raises(Exception):Contract(settings.contracts_dir/'document/intelligence/v1.schema.json').validate(bad)
    bad=copy.deepcopy(out);bad['signal']='BUY'
    with pytest.raises(Exception):Output.model_validate(bad)

def test_no_article_body_or_sentence_text_in_message(pipeline,document):
    out=pipeline.analyze(document('The Federal Reserve kept interest rates unchanged.'))
    assert 'body' not in out and 'body' not in out['document']
    assert all(set(s)=={'sentence_id','start_char','end_char'} for s in out['sentences'])

@pytest.mark.parametrize('text,value',[
 ('Инфляция составила 5,250 процента.','5.250'),
 ('The inflation rate was -0.3 percent.','-0.3'),
 ('The inflation rate was −0.3 percent.','-0.3'),
])
def test_decimal_locale_and_negative_values(pipeline,document,text,value):
    out=pipeline.analyze(document(text));assert out['measurements'][0]['value']==value

@pytest.mark.parametrize('text',[
 'The meeting is on 10 September 2026 from 2026-09-10 to 2026-09-12 at 14:45 CET during Q3 2026.',
 'Заседание состоится 10 сентября 2026 в 14:45 UTC в 3 квартал 2026.',
])
def test_explicit_dates_periods_and_ranges(pipeline,document,text):
    out=pipeline.analyze(document(text));assert any(d['normalized']=='2026-09-10' for d in out['dates'])
    assert {'date','time','period'}<={d['kind'] for d in out['dates']}
    validate_spans(out,text)

def test_multisentence_aliases_link_canonical_entities(pipeline,document):
    out=pipeline.analyze(document('The Federal Reserve released a statement. The FOMC kept interest rates unchanged.'))
    assert {e['entity_id'] for e in out['entities'] if e['evidence']['text'] in ('Federal Reserve','FOMC')}=={'organization:federal_reserve'}
    assert out['facts'][0]['evidence']['sentence_id']==1

@pytest.mark.parametrize('text,kind',[
 ('Inflation rose to 3.3 percent.','economic_data.inflation'),
 ('GDP grew by 2.5 percent.','economic_data.gdp'),
 ('Wages increased by 3 percent.','economic_data.wages'),
 ('Employment increased by 2 percent.','economic_data.employment'),
 ('The SEC approved a Bitcoin ETF.','crypto.etf_action'),
])
def test_additional_domain_rules_require_context(pipeline,document,text,kind):
    out=pipeline.analyze(document(text));assert any(f['fact_type']==kind for f in out['facts'])

def test_economic_mention_without_explicit_value_has_no_reported_fact(pipeline,document):
    out=pipeline.analyze(document('Inflation remained elevated.'))
    assert not out['facts']

@pytest.mark.parametrize('text',[
 "Inflation remains elevated relative to the Committee's 2 percent goal.",
 'Inflation is above its 2 percent target.',
 'Inflation is projected to be 3.3 percent next year.',
])
def test_target_or_forecast_is_not_an_observed_inflation_value(pipeline,document,text):
    assert pipeline.analyze(document(text))['facts']==[]

def test_coordinated_shock_does_not_inherit_inflation_subject(pipeline,document):
    out=pipeline.analyze(document('Today, inflation is at 3.3 percent, and there has been a major shock.'))
    assert len(out['facts'])==1

def test_multiple_economic_values_do_not_confuse_threshold_and_actual(pipeline,document):
    out=pipeline.analyze(document('Today, inflation is well above 2 percent, at 3.3 percent.'))
    assert len(out['measurements'])==2 and out['facts']==[]

def test_clock_time_is_not_ratio_due_to_substring_in_considerations(pipeline,document):
    out=pipeline.analyze(document('The President will comment on the considerations underlying these decisions at 14:45 CET today.'))
    assert out['measurements']==[] and out['dates'][0]['kind']=='time'

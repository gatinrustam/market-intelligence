import copy,json
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx,pytest
from app.domain import digest,identity
from app.guard import build_input,Blocked
from app.intelligence import attach,PROMPT
from app.worker import Worker
from app.main import create_app

@pytest.fixture
def envelope(package,settings):
    p=build_input(package,package['event'],settings);key=str(uuid4())
    value={'schema_version':'1.0','message_id':key,'intelligence_id':key,'event':p['event_identity'],'asset':{'symbol':'BTCUSDT'},
        'relevance':'high','novelty':'new','surprise':{'status':'unavailable','value':None},
        'expectations':dict.fromkeys(('type','previous','consensus','actual','unit','source')),'information_quality':'high','event_specificity':'specific',
        'generated_at':'2026-09-19T23:00:00Z','basis':{'ruleset_version':'1.0','ruleset_hash':'a'*64,'matched_rule_ids':['fed.policy'],
        'canonical_hash':digest(p['event']),'input_hash':'b'*64,'novelty_scope':'canonical_revision_history_only','previous_event_revision':None,
        'evidence_hashes':[{'document_id':e['document']['document_id'],'message_id':e['document']['message_id'],'content_hash':e['document']['integrity']['content_hash']} for e in p['evidence']],
        'quality_basis':'deterministic_not_statistical_confidence','expectations_basis':'no_external_provider'}}
    return {'intelligence':value,'available_at':'2026-09-19T23:00:01Z','availability_basis':'confirmed_jetstream_publication'}

def test_historical_intelligence_pinned_without_rewriting_legacy(package,settings,envelope):
    p=build_input(package,package['event'],settings);before=copy.deepcopy(p)
    new=attach(p,envelope,envelope['intelligence']['intelligence_id'],settings)
    assert p==before and 'event_intelligence' not in p
    assert new['intelligence_availability']['hypothetical_derivation'] is True
    assert new['event_intelligence']==envelope['intelligence'] and digest(new)!=digest(p)
    assert all(q['offset_seconds']<=0 for q in new['market_context']['points'])

def test_live_rejects_late_confirmed_publication(package,settings,envelope):
    p=build_input(package,package['event'],settings);p['decision']['historical_simulation']=False
    with pytest.raises(Blocked,match='intelligence_available_after_decision'):attach(p,envelope,envelope['intelligence']['intelligence_id'],settings)
    p['decision']['decision_at']='2026-09-19T23:00:01Z'
    assert attach(p,envelope,envelope['intelligence']['intelligence_id'],settings)['intelligence_availability']['hypothetical_derivation'] is False

@pytest.mark.parametrize('mutate',[
 lambda e:e['intelligence']['event'].update(event_revision=99),
 lambda e:e['intelligence']['basis'].update(canonical_hash='c'*64),
 lambda e:e['intelligence']['basis']['evidence_hashes'].clear(),
 lambda e:e.update(available_at='2099-01-01T00:00:00Z'),
 lambda e:e.update(available_at='2000-01-01T00:00:00Z'),
 lambda e:e.update(availability_basis='unconfirmed'),
 lambda e:e['intelligence']['surprise'].update(status='available',value='1'),
])
def test_intelligence_guard_rejects_mismatches(package,settings,envelope,mutate):
    mutate(envelope)
    with pytest.raises(Blocked):attach(build_input(package,package['event'],settings),envelope,envelope['intelligence']['intelligence_id'],settings)

async def test_opt_in_worker_freezes_intelligence_and_preserves_output_contract(repo,settings,package,output,envelope):
    key=envelope['intelligence']['intelligence_id']
    config={**settings.configuration(),'prompt_version':PROMPT,'intelligence_id':key}
    analysis=repo.enqueue(package['event'],package['context_id'],'research_hypothetical',str(uuid4()),config)
    decisions=AsyncMock();decisions.fetch.return_value=package
    provider=AsyncMock();provider.analyze.return_value={'output':output,'audit':{'fake_provider':True}}
    intelligence=AsyncMock();intelligence.fetch.return_value=envelope
    w=Worker(repo,decisions,provider,settings,intelligence);assert await w.run_once()
    value=repo.view(analysis);assert value['analysis_status']=='completed'
    frozen=json.loads(repo.input(value['input_hash']).canonical_json)
    assert frozen['event_intelligence']['intelligence_id']==key
    assert value['analysis']['audit']['prompt_version']==PROMPT
    assert 'event_intelligence' not in value['analysis']
    assert 'event_intelligence' in json.loads(provider.analyze.call_args.args[0]['input'][1]['content'])

async def test_missing_intelligence_blocks_new_mode_without_provider(repo,settings,package,envelope):
    config={**settings.configuration(),'prompt_version':PROMPT,'intelligence_id':envelope['intelligence']['intelligence_id']}
    key=repo.enqueue(package['event'],package['context_id'],'research_hypothetical',str(uuid4()),config)
    decisions=AsyncMock();decisions.fetch.return_value=package;provider=AsyncMock();intelligence=AsyncMock();intelligence.fetch.side_effect=Blocked('event_intelligence_unavailable')
    await Worker(repo,decisions,provider,settings,intelligence).run_once()
    assert repo.view(key)['analysis_status']=='blocked';provider.analyze.assert_not_called()

def test_intelligence_identity_isolated(package,settings,envelope):
    legacy=settings.configuration();a={**legacy,'prompt_version':PROMPT,'intelligence_id':str(uuid4())};b={**a,'intelligence_id':str(uuid4())}
    assert len({identity(package['event'],c,'research_hypothetical','same') for c in (legacy,a,b)})==3

async def test_api_selects_new_prompt_only_when_opted_in(repo,settings,package,envelope):
    app=create_app(settings);app.state.repo=repo
    body={**package['event'],'context_id':package['context_id'],'basis':'research_hypothetical','run_key':str(uuid4()),'intelligence_id':envelope['intelligence']['intelligence_id']}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        r=await c.post('/analyses',json=body);assert r.status_code==202
        assert repo.view(r.json()['analysis_id'])['configuration']['prompt_version']==PROMPT

async def test_live_worker_requests_market_at_intelligence_availability(repo,settings,package,output,envelope):
    from datetime import timedelta
    from app.domain import parse,iso
    key=envelope['intelligence']['intelligence_id'];decision=parse(envelope['available_at'])
    package.update(decision_at=iso(decision),as_of=iso(decision),decision_mode='live',decision_basis='live_observed',historical_simulation=False,
        live_inputs_available_at=iso(decision),market_availability_basis='locally_collected_by_decision_at',content_assumption='exact_observed_inputs_available_by_decision_at')
    for point in package['points']:
        target=decision+timedelta(seconds=point['offset_seconds'])
        point.update(target_at=iso(target),price_at=iso(target),resolution='realtime_1s',candle=None,age_seconds=0,max_age_seconds=3)
    config={**settings.configuration(),'prompt_version':PROMPT,'intelligence_id':key}
    analysis=repo.enqueue(package['event'],package['context_id'],'live',str(uuid4()),config)
    decisions=AsyncMock();decisions.fetch.return_value=package
    provider=AsyncMock();provider.analyze.return_value={'output':output,'audit':{'fake_provider':True}}
    intelligence=AsyncMock();intelligence.fetch.return_value=envelope
    await Worker(repo,decisions,provider,settings,intelligence).run_once()
    decisions.fetch.assert_awaited_once_with(package['context_id'],'live',additional_input_available_at=envelope['available_at'])
    value=repo.view(analysis);assert value['analysis_status']=='completed'
    frozen=json.loads(repo.input(value['input_hash']).canonical_json)
    assert frozen['decision']['decision_at']==iso(decision)
    assert not frozen['intelligence_availability']['hypothetical_derivation']
    assert all(parse(p['price_at'])<=parse(p['target_at'])<=decision for p in frozen['market_context']['points'])
    provider.analyze.assert_awaited_once()

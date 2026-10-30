import copy,json
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest,httpx
from app.decision import DecisionResolver,DecisionInputs,DecisionUnavailable
from app.domain import iso,parse
from app.storage.models import MarketContext,ContextInput
from app.storage.repository import identity
from app.main import create_app
from app.worker import ContextWorker
from tests.test_context import T,exact,Market,market_data,accept,context

@pytest.fixture
def source(event):
    e=exact(event,T-timedelta(hours=3));e['time']['earliest_source_published_at']=iso(T)
    e['time']['first_detected_at']=e['time']['last_updated_at']=iso(T+timedelta(minutes=10))
    ref=e['evidence']['documents'][0]
    doc=json.loads(Path('tests/enriched.json').read_text())
    doc.update(document_id=ref['document_id'],message_id=ref['input_message_id']);doc['source']['id']=ref['source_id'];doc['lineage']['source_message_id']=ref['source_message_id']
    doc['timestamps'].update(published_at=iso(T),received_at=iso(T+timedelta(minutes=1)),enriched_at=iso(T+timedelta(minutes=8)))
    doc['fetch']['fetched_at']=iso(T+timedelta(minutes=7))
    row=SimpleNamespace(payload=e,received_at=(T+timedelta(days=1)).replace(tzinfo=None),jetstream_metadata={'published_at':iso(T+timedelta(minutes=11))},exact_payload=json.dumps(e).encode(),subject='event.detected.v1')
    return row,{'document':doc,'input_received_at':iso(T+timedelta(minutes=9)),'stream_sequence':1,'payload_sha256':'a'*64}

class Inputs:
    def __init__(self,source):self.row,self.document=source
    async def canonical_available_at(self,row):return parse(row.jetstream_metadata['published_at'])
    async def evidence(self,reference):return copy.deepcopy(self.document)
class Quotes:
    def __init__(self):self.calls=[]
    async def lookup(self,t,known_at=None):self.calls.append((t,known_at));return market_data(t,'realtime')

def resolver(source,settings):
    q=Quotes();return DecisionResolver(Inputs(source),q,settings,clock=lambda:T+timedelta(days=2)),q

async def test_live_uses_actual_inputs_not_event_or_publication(source,settings):
    service,q=resolver(source,settings);p=await service.build('context',source[0])
    assert p['event_time']==iso(T-timedelta(hours=3)) and p['decision_at']==iso(T+timedelta(minutes=11))
    assert p['decision_basis']=='live_observed' and not p['historical_simulation']
    assert parse(p['decision_at'])>=parse(p['evidence_available_at']) and p['resolver_observed_at']!=p['decision_at']
    assert [x['offset_seconds'] for x in p['points']]==[-900,-300,0]
    assert all(x['role']=='causal' and parse(x['price_at'])<=parse(x['target_at'])<=parse(p['decision_at']) for x in p['points'])
    assert all(known==parse(p['decision_at']) for _,known in q.calls)
    assert 'revision' not in p and 'pending_future_points' not in json.dumps(p)

async def test_live_waits_for_all_required_evidence(source,settings):
    source[1]['input_received_at']=iso(T+timedelta(minutes=20))
    service,_=resolver(source,settings);p=await service.build('context',source[0])
    assert p['decision_at']==iso(T+timedelta(minutes=20))

async def test_historical_explicit_simulation_and_late_content(source,settings):
    source[1]['document']['fetch']['fetched_at']=iso(T+timedelta(days=1))
    service,q=resolver(source,settings);p=await service.build('context',source[0],'research_hypothetical')
    assert p['decision_at']==iso(T) and p['decision_basis']=='source_published_at' and p['historical_simulation']
    assert p['decision_mode']=='research_hypothetical' and not p['historical_content_verified']
    assert parse(p['evidence_available_at'])>parse(p['decision_at'])
    assert p['known_information']['evidence'][0]['late_enrichment']
    assert not p['known_information']['evidence'][0]['historical_content_verified']
    assert all(known is None for _,known in q.calls)
    assert p['known_information']['evidence'][0]['document']['content']==source[1]['document']['content']

async def test_current_content_is_never_archivally_verified(source,settings):
    service,_=resolver(source,settings);p=await service.build('context',source[0])
    assert p['evidence_fetched_at']==iso(T+timedelta(minutes=7)) and not p['historical_content_verified']

@pytest.mark.parametrize('field',['document_id','message_id'])
async def test_document_version_mismatch_fails_closed(source,settings,field):
    source[1]['document'][field]='00000000-0000-0000-0000-000000000000'
    service,_=resolver(source,settings)
    with pytest.raises(DecisionUnavailable):await service.build('context',source[0])

async def test_missing_publication_has_no_hypothetical_fallback(source,settings):
    source[0].payload['time']['earliest_source_published_at']=None
    service,_=resolver(source,settings)
    with pytest.raises(DecisionUnavailable):await service.build('context',source[0],'research_hypothetical')
    assert (await service.build('context',source[0]))['decision_basis']=='live_observed'

async def test_imprecise_event_time_can_have_precise_live_decision(source,settings):
    source[0].payload['time'].update(event_time='2026-04-29',event_time_precision='date')
    service,_=resolver(source,settings)
    assert (await service.build('context',source[0]))['decision_at']==iso(T+timedelta(minutes=11))

async def test_market_future_observation_rejected(source,settings):
    service,q=resolver(source,settings)
    async def bad(t,known_at=None):
        d=market_data(t,'realtime');d['realtime']['observed_at']=iso(t+timedelta(seconds=1));return d
    q.lookup=bad
    with pytest.raises(ValueError):await service.build('context',source[0])

async def test_provenance_unavailable_does_not_use_publication(source,settings):
    service,_=resolver(source,settings);service.inputs.canonical_available_at=AsyncMock(side_effect=ConnectionError('NATS unavailable'))
    with pytest.raises(ConnectionError):await service.build('context',source[0])

async def test_original_nats_time_fallback_validates_exact_input(source,settings):
    row,_=source;row.jetstream_metadata={'stream_sequence':5}
    bus=AsyncMock();bus.js.get_msg.return_value=SimpleNamespace(data=row.exact_payload,subject=row.subject,time=T+timedelta(minutes=11))
    inputs=DecisionInputs(bus,settings)
    try:
        assert await inputs.canonical_available_at(row)==T+timedelta(minutes=11)
        bus.js.get_msg.return_value.data=b'{}'
        with pytest.raises(DecisionUnavailable):await inputs.canonical_available_at(row)
    finally:await inputs.close()

async def test_recorded_publish_time_does_not_require_nats(source,settings):
    inputs=DecisionInputs(AsyncMock(),settings)
    try:
        assert await inputs.canonical_available_at(source[0])==T+timedelta(minutes=11)
        inputs.bus.connect.assert_not_awaited()
    finally:await inputs.close()

async def test_decision_api_read_only_defaults_live(repo,sessions,settings,source):
    row,doc=source;accept(repo,row.payload)
    await ContextWorker(repo,Market(),settings,clock=lambda:T+timedelta(days=2)).run_once()
    key=identity(row.payload);before=context(sessions,key);app=create_app(settings);app.state.sessions=sessions
    service,q=resolver(source,settings);app.state.decisions=service
    # Stub availability adapter is independent of stored local reception time.
    service.inputs.canonical_available_at=AsyncMock(return_value=T+timedelta(minutes=11))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        response=await c.get('/contexts/'+key+'/decision');assert response.status_code==200
        assert response.json()['decision_basis']=='live_observed'
        research=await c.get('/contexts/'+key+'/decision',params={'basis':'research_hypothetical'})
        assert research.status_code==200 and research.json()['historical_simulation']
        assert (await c.get('/contexts/'+key+'/decision',params={'basis':'event_time'})).status_code==422
        shifted=await c.get('/contexts/'+key+'/decision',params={'additional_input_available_at':iso(T+timedelta(minutes=20))})
        assert shifted.status_code==200 and shifted.json()['decision_at']==iso(T+timedelta(minutes=20))
        for params in ({'additional_input_available_at':'2026-04-29T18:00:00'}, {'basis':'research_hypothetical','additional_input_available_at':iso(T)}):
            assert (await c.get('/contexts/'+key+'/decision',params=params)).status_code==422
    assert context(sessions,key)==before

async def test_multi_document_revision_uses_latest_required_input(source,settings):
    from uuid import uuid4
    row,first=source;second=copy.deepcopy(first);ref=copy.deepcopy(row.payload['evidence']['documents'][0])
    ref.update(document_id=str(uuid4()),input_message_id=str(uuid4()),source_message_id=str(uuid4()))
    second['document'].update(document_id=ref['document_id'],message_id=ref['input_message_id'])
    second['document']['lineage']['source_message_id']=ref['source_message_id']
    second['input_received_at']=iso(T+timedelta(minutes=30))
    row.payload['evidence']['documents'].append(ref);row.payload['evidence']['document_count']=2
    service,_=resolver(source,settings)
    async def evidence(reference):return first if reference['document_id']==first['document']['document_id'] else second
    service.inputs.evidence=evidence
    p=await service.build('context',row)
    assert p['decision_at']==iso(T+timedelta(minutes=30)) and len(p['known_information']['evidence'])==2

@pytest.mark.parametrize('minutes,expected',[(20,20),(5,11)])
async def test_additional_live_input_reanchors_without_rollback(source,settings,minutes,expected):
    service,q=resolver(source,settings);before=copy.deepcopy(source[0].payload)
    p=await service.build('context',source[0],additional_input_available_at=iso(T+timedelta(minutes=minutes)))
    decision=T+timedelta(minutes=expected)
    assert p['decision_at']==p['live_inputs_available_at']==iso(decision)
    assert q.calls==[(decision+timedelta(seconds=n),decision) for n in (-900,-300,0)]
    assert all(parse(x['price_at'])<=parse(x['target_at'])<=decision for x in p['points'])
    assert source[0].payload==before

@pytest.mark.parametrize('basis,stamp',[('research_hypothetical',T),('live',T+timedelta(days=3))])
async def test_additional_input_rejects_hypothetical_or_future(source,settings,basis,stamp):
    service,q=resolver(source,settings)
    with pytest.raises(DecisionUnavailable):await service.build('context',source[0],basis,iso(stamp))
    assert q.calls==[]

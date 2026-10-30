from datetime import timedelta
from types import SimpleNamespace
import pytest
from app.outcomes import outcome_view
from app.domain import iso,parse
from tests.test_context import T,market_data

@pytest.mark.parametrize('shift',[0,3600])
async def test_outcomes_use_decision_anchor_not_event_anchor(settings,shift):
    decision=T+timedelta(seconds=shift);calls=[]
    async def lookup(target):calls.append(target);return market_data(target,'candle')
    context={'context_id':'test','event':{'event_id':'event','event_revision':1},'market':{'provider':'binance_spot','symbol':'BTCUSDT'},'anchor':{'at':iso(T)}}
    value=await outcome_view(context,iso(decision),SimpleNamespace(lookup=lookup),settings,clock=lambda:decision+timedelta(hours=2))
    assert [p['offset_seconds'] for p in value['points']]==[60,300,900,3600]
    assert all(p['role']=='outcome' and p['available'] for p in value['points'])
    assert all(decision<parse(p['price_at'])<=parse(p['target_at']) for p in value['points'])
    assert calls==[decision+timedelta(seconds=n) for n in (60,300,900,3600)]

async def test_future_pending_no_market_lookup(settings):
    async def lookup(target):raise AssertionError('future lookup')
    value=await outcome_view({'context_id':'test','event':{},'market':{}},iso(T),SimpleNamespace(lookup=lookup),settings,clock=lambda:T)
    assert {p['status'] for p in value['points']}=={'pending'}
    assert all(p['price'] is None for p in value['points'])

async def test_stale_outcomes_never_substitute_causal_points(settings):
    async def lookup(target):
        d=market_data(target,'none');d['candle_1m']=market_data(T-timedelta(days=2),'candle')['candle_1m'];return d
    value=await outcome_view({'context_id':'test','event':{},'market':{}},iso(T),SimpleNamespace(lookup=lookup),settings,clock=lambda:T+timedelta(hours=2))
    assert all(p['status']=='unavailable' and p['reason']=='stale_market_data' and p['price'] is None for p in value['points'])

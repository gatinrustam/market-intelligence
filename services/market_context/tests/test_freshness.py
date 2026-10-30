from datetime import timedelta
import copy
import pytest
from pydantic import ValidationError
from app.config import Settings
from app.domain import resolve_point,iso
from app.freshness import FRESHNESS_POLICY,fresh_point,freshness_limits
from tests.test_context import T,market_data
from tests.test_decision_time import source,resolver

def candidate(resolution,age):
    data=market_data(T,'realtime' if resolution=='realtime_1s' else 'candle')
    price_at=T-timedelta(seconds=age)
    if resolution=='realtime_1s':data['realtime']['observed_at']=iso(price_at)
    else:data['candle_1m'].update(close_time=iso(price_at),open_time=iso(price_at-timedelta(seconds=59.999)))
    return resolve_point(0,T,data,T,10)

@pytest.mark.parametrize('resolution,age,available',[
    ('candle_1m',.001,True),('candle_1m',60,True),('candle_1m',60.001,False),
    ('candle_1m',120,False),('candle_1m',86400*150,False),
    ('realtime_1s',0,True),('realtime_1s',3,True),('realtime_1s',3.000001,False)])
def test_freshness_boundaries(settings,resolution,age,available):
    original=candidate(resolution,age);saved=copy.deepcopy(original)
    p=fresh_point(original,freshness_limits(settings))
    assert original==saved and p['available']==available and p['age_seconds']==age
    if not available:
        assert p['reason']=='stale_market_data' and p['status']=='unavailable'
        assert all(p[k] is None for k in ('price','price_at','candle','bid','ask','spread_bps','snapshot_message_id','return_pct_from_anchor','absolute_return_pct'))

def test_configurable_limits(settings):
    settings.candle_max_age_seconds=90;settings.realtime_max_age_seconds=1
    assert fresh_point(candidate('candle_1m',80),freshness_limits(settings))['available']
    assert not fresh_point(candidate('realtime_1s',2),freshness_limits(settings))['available']

@pytest.mark.parametrize('value',[0,-1,float('inf'),float('nan')])
def test_invalid_limits(value):
    with pytest.raises(ValidationError):Settings(candle_max_age_seconds=value)

@pytest.mark.parametrize('basis',['live','research_hypothetical'])
async def test_stale_t_blocks_decision_and_no_old_candle_fallback(source,settings,basis):
    service,q=resolver(source,settings)
    async def lookup(t,known_at=None):
        q.calls.append(t)
        d=market_data(t,'realtime')
        d['realtime']['observed_at']=iso(t-timedelta(seconds=4))
        d['candle_1m']=market_data(t-timedelta(days=150),'candle')['candle_1m']
        return d
    q.lookup=lookup
    p=await service.build('context',source[0],basis)
    assert p['lookup_policy']==FRESHNESS_POLICY
    assert p['freshness_policy']['max_age_seconds']=={'realtime_1s':3,'candle_1m':60}
    assert not p['complete'] and not p['decision_ready'] and p['market_data_status']=='market_data_unavailable'
    assert len(q.calls)==3 # no additional lookup/fallback after rejecting stale observation
    assert all(not x['available'] and x['price'] is None and x['candle'] is None for x in p['points'])
    assert all(x['return_pct_from_anchor'] is None for x in p['points'])

async def test_sparse_history_can_become_complete_after_backfill(source,settings):
    service,q=resolver(source,settings);backfilled=False
    async def lookup(t,known_at=None):
        d=market_data(t,'candle')
        if not backfilled:d['candle_1m']=market_data(t-timedelta(days=150),'candle')['candle_1m']
        return d
    q.lookup=lookup
    missing=await service.build('context',source[0],'research_hypothetical')
    assert not missing['decision_ready'] and all(p['reason']=='stale_market_data' for p in missing['points'])
    backfilled=True
    fresh=await service.build('context',source[0],'research_hypothetical')
    assert fresh['complete'] and fresh['decision_ready']
    assert all(p['available'] and p['age_seconds']==.001 for p in fresh['points'])
    assert all(p['price'] is None for p in missing['points'])

async def test_stale_history_removed_even_when_t_fresh(source,settings):
    service,q=resolver(source,settings)
    decision_at=T+timedelta(minutes=11)
    async def lookup(t,known_at=None):
        d=market_data(t,'candle')
        if t<decision_at:d['candle_1m']=market_data(t-timedelta(days=150),'candle')['candle_1m']
        return d
    q.lookup=lookup
    p=await service.build('context',source[0])
    assert p['decision_ready'] and not p['complete']
    assert all(x['price'] is None and x['return_pct_from_anchor'] is None for x in p['points'][:2])
    assert p['points'][-1]['available']

async def test_absent_t_is_not_decision_ready(source,settings):
    service,q=resolver(source,settings)
    async def lookup(t,known_at=None):return market_data(t,'none')
    q.lookup=lookup
    p=await service.build('context',source[0])
    assert not p['decision_ready'] and not p['complete'] and p['market_data_status']=='market_data_unavailable'

def test_april_candle_for_september_target_rejected(settings):
    from app.domain import parse
    september=parse('2026-09-17T12:55:00Z')
    data=market_data(september,'none')
    data['candle_1m']=market_data(parse('2026-04-29T18:00:00Z'),'candle')['candle_1m']
    point=resolve_point(0,september,data,september,10)
    result=fresh_point(point,freshness_limits(settings))
    assert result['reason']=='stale_market_data' and not result['available']
    assert result['price'] is None and result['candle'] is None

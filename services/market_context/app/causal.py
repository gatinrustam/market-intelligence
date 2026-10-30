"""Policy and a fail-closed allowlisted decision projection. No outcome data in Stage 4 input."""
import copy
from app.domain import OFFSETS,parse,returns
from datetime import timedelta

POLICY='causal_asof_v1'
LEGACY_POLICY='legacy_nearest_v1'
CAUSAL_OFFSETS=(-900,-300,0)
OUTCOME_OFFSETS=(60,300,900,3600)

def point_role(offset):
    if offset in CAUSAL_OFFSETS:return 'causal'
    if offset in OUTCOME_OFFSETS:return 'outcome'
    raise ValueError('unknown point offset')

def validate_points(points,anchor):
    if tuple(p['offset_seconds'] for p in points)!=OFFSETS:raise ValueError('invalid point offsets')
    for p in points:
        if not p['available']:continue
        if p['price_at'] is None or p['target_at'] is None:raise ValueError('missing price provenance')
        target,price_at=parse(p['target_at']),parse(p['price_at'])
        if price_at>target:raise ValueError('noncausal price observation')
        if p['resolution']=='candle_1m' and (p['candle'] is None or parse(p['candle']['close_time'])!=price_at):raise ValueError('invalid candle provenance')
        if point_role(p['offset_seconds'])=='causal' and (anchor['at'] is None or target>parse(anchor['at'])):raise ValueError('causal target after anchor')

def decision_view(payload,policy):
    if policy!=POLICY:raise ValueError('context requires causal recomputation')
    if payload['anchor']['at'] is None:raise ValueError('no precise decision anchor')
    # Deliberately select before inspecting: outcome data or its availability cannot
    # influence this projection, including derived metrics, status or revision IDs.
    selected=[copy.deepcopy(p) for p in payload['points'] if p['offset_seconds'] in CAUSAL_OFFSETS]
    if tuple(p['offset_seconds'] for p in selected)!=CAUSAL_OFFSETS:raise ValueError('missing or duplicate causal point')
    cutoff=parse(payload['anchor']['at'])
    for p in selected:
        if p['target_at'] is None or parse(p['target_at'])!=cutoff+timedelta(seconds=p['offset_seconds']):raise ValueError('invalid causal target')
        if p['available'] and (p['price_at'] is None or parse(p['price_at'])>parse(p['target_at'])):raise ValueError('future price in decision view')
        if p['candle'] is not None and parse(p['candle']['close_time'])>parse(p['target_at']):raise ValueError('future candle in decision view')
    # Recompute metrics solely from the three causal inputs.
    selected=returns(selected)
    allowed=('offset_seconds','target_at','status','available','resolution','reason','price','price_basis','price_at',
             'snapshot_message_id','snapshot_distance_ms','bid','ask','spread_bps','candle','return_pct_from_anchor','absolute_return_pct')
    points=[{**{k:p[k] for k in allowed},'role':'causal'} for p in selected]
    candle_fields=('open_time','close_time','open','high','low','close','base_volume','quote_volume','trade_count','taker_buy_base_volume','taker_buy_quote_volume')
    for p in points:
        if p['candle'] is not None:p['candle']={k:p['candle'][k] for k in candle_fields}
    return {'context_id':payload['context_id'],'event':{k:payload['event'][k] for k in ('event_id','event_revision')},'market':{k:payload['market'][k] for k in ('provider','symbol')},
        'anchor':{k:payload['anchor'][k] for k in ('at','type','precision','original_value','unavailable_reason')},'as_of':payload['anchor']['at'],'lookup_policy':POLICY,
        'points':points,'complete':all(p['available'] for p in points)}

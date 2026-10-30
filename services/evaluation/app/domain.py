import copy
import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from uuid import uuid5, NAMESPACE_URL

HORIZONS = (60, 300, 900, 3600)
BUCKETS = ('negligible', 'small', 'moderate', 'large')
POLICY = 'causal_asof_fresh_v1'


def now(): return datetime.now(timezone.utc)
def iso(value): return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
def parse(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None: raise ValueError('timezone required')
    return result.astimezone(timezone.utc)
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def identity(analysis_id): return str(uuid5(NAMESPACE_URL, 'evaluation.v1:'+analysis_id))
def context_id(event): return str(uuid5(NAMESPACE_URL, f"market.context.v1:{event['event_id']}:{event['event_revision']}:BTCUSDT"))
def price(value):
    if not isinstance(value, str): raise ValueError('decimal string required')
    result = Decimal(value)
    if not result.is_finite() or result <= 0: raise ValueError('positive finite price required')
    return result

def max_age(value):
    limit = Decimal(str(value))
    if not limit.is_finite() or limit <= 0: raise ValueError('invalid freshness limit')
    return limit

def direction(value, policy):
    if abs(value) < Decimal(policy['neutral_threshold_pct']): return 'neutral'
    return 'up' if value > 0 else 'down'

def impact(value, policy):
    for name in BUCKETS[:-1]:
        if abs(value) < Decimal(policy['impact_thresholds_pct'][name]): return name
    return 'large'

def movement(base, outcome):
    with localcontext() as ctx:
        ctx.prec = 80
        value = ((price(outcome)-price(base))/price(base)*100).quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_EVEN)
        return abs(value) if value == 0 else value

def prepare_input(analysis, package):
    if digest(package) != analysis['audit']['input_hash']: raise ValueError('immutable input hash mismatch')
    if package['event_identity'] != analysis['event']: raise ValueError('event revision mismatch')
    for key, value in analysis['decision'].items():
        if package['decision'][key] != value: raise ValueError('decision mismatch')
    event = package['event']
    if {'event_id':event['event']['id'], 'event_revision':event['event']['revision']} != analysis['event']:
        raise ValueError('canonical identity mismatch')
    market = package['market_context']
    if market['symbol'] != 'BTCUSDT' or market['lookup_policy'] != POLICY: raise ValueError('unsupported market input')
    anchors = [p for p in market['points'] if p['offset_seconds'] == 0]
    if len(anchors) != 1: raise ValueError('missing/duplicate decision anchor')
    anchor = anchors[0]
    target = parse(analysis['decision']['decision_at'])
    if not anchor['available'] or parse(anchor['target_at']) != target: raise ValueError('decision anchor unavailable')
    age = (target-parse(anchor['price_at'])).total_seconds()
    if market['freshness_policy']['version'] != POLICY: raise ValueError('wrong anchor freshness policy')
    limit = max_age(market['freshness_policy']['max_age_seconds'][anchor['resolution']])
    if not 0 <= Decimal(str(age)) <= limit: raise ValueError('stale/future anchor')
    price(anchor['price'])
    return {'context_id':context_id(analysis['event']), 'anchor':copy.deepcopy(anchor),
            'event_type':event['taxonomy']['event_type'],
            'sources':sorted(set(r['source_id'] for r in event['evidence']['documents']))}

def validate_outcomes(analysis, data):
    if data['context_id'] != context_id(analysis['event']): raise ValueError('wrong context')
    if any(data['event'][k] != v for k,v in analysis['event'].items()): raise ValueError('wrong outcome event')
    cutoff = parse(analysis['decision']['decision_at'])
    if parse(data['decision_at']) != cutoff or data['usage'] != 'evaluation_only': raise ValueError('wrong outcome anchor')
    if data['lookup_policy'] != POLICY or data['market']['symbol'] != 'BTCUSDT' or data['market']['provider'] != 'binance_spot':
        raise ValueError('wrong outcome market policy')
    if data['freshness_policy']['version'] != POLICY: raise ValueError('wrong freshness policy')
    if [p['offset_seconds'] for p in data['points']] != list(HORIZONS): raise ValueError('outcomes only, no causal points')
    for point in data['points']:
        target = cutoff+timedelta(seconds=point['offset_seconds'])
        if point['role'] != 'outcome' or parse(point['target_at']) != target or type(point['available']) is not bool: raise ValueError('invalid outcome target')
        if point['available']:
            observed = parse(point['price_at'])
            limit = max_age(data['freshness_policy']['max_age_seconds'][point['resolution']])
            if not cutoff < observed <= target <= now() or Decimal(str((target-observed).total_seconds())) > limit: raise ValueError('stale/future outcome')
            price(point['price'])
        elif point['status'] not in ('pending','unavailable'): raise ValueError('invalid unavailable outcome')
    return data['points']

def result(forecast, point, anchor, policy):
    entry = {'horizon_seconds':forecast['horizon_seconds'], 'forecast':{k:forecast[k] for k in ('direction','impact','confidence')},
             'status':point['status'] if not point['available'] else 'evaluated',
             'reason':point['reason'] if not point['available'] else None, 'actual':None,
             'evaluation':{'direction_result':'not_scored', 'impact_match':None, 'impact_distance':None}}
    if point['available']:
        value = movement(anchor['price'], point['price'])
        actual_direction, actual_impact = direction(value, policy), impact(value, policy)
        unclear = forecast['direction'] == 'unclear'
        entry['status'] = 'not_scored' if unclear else 'evaluated'
        entry['actual'] = {'anchor_price':anchor['price'], 'anchor_price_at':anchor['price_at'],
            'outcome_price':point['price'], 'outcome_price_at':point['price_at'], 'target_at':point['target_at'],
            'resolution':point['resolution'], 'return_pct':format(value,'f'), 'absolute_return_pct':format(abs(value),'f'),
            'direction':actual_direction, 'impact':actual_impact}
        entry['evaluation'] = {'direction_result':'not_scored' if unclear else 'hit' if forecast['direction']==actual_direction else 'miss',
            'impact_match':forecast['impact']==actual_impact, 'impact_distance':abs(BUCKETS.index(forecast['impact'])-BUCKETS.index(actual_impact))}
    return entry

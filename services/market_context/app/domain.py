from datetime import datetime,timedelta,timezone
from decimal import Decimal,localcontext,ROUND_HALF_EVEN
OFFSETS=(-900,-300,0,60,300,900,3600)
UTC=timezone.utc

def now():return datetime.now(UTC)
def iso(t):return t.astimezone(UTC).isoformat().replace('+00:00','Z')
def parse(s):
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('timezone required')
    return t.astimezone(UTC)
def decimal(value):
    if not isinstance(value,str):raise ValueError('expected decimal string')
    d=Decimal(value)
    if not d.is_finite() or d<0:raise ValueError('invalid price')
    return d

def anchor(event):
    time=event['time'];v=time['event_time'];kind='event_time';precision=time['event_time_precision']
    reason=None
    if v is None:
        v=time['earliest_source_published_at'];kind='source_published_at';precision='exact'
    if v is None:reason='missing_anchor_time'
    elif precision in ('date','date_range'):reason='imprecise_event_time'
    return {'at':iso(parse(v)) if reason is None else None,'type':kind,'precision':precision,'original_value':v,'unavailable_reason':reason}

def empty_point(offset,target,status,reason):
    return {'offset_seconds':offset,'target_at':iso(target) if target else None,'status':status,'available':False,
        'resolution':None,'reason':reason,'price':None,'price_basis':None,'price_at':None,'snapshot_message_id':None,
        'snapshot_distance_ms':None,'bid':None,'ask':None,'spread_bps':None,'candle':None,
        'return_pct_from_anchor':None,'absolute_return_pct':None}

def resolve_point(offset,target,data,at,grace):
    if data.get('provider')!='binance_spot' or data.get('symbol')!='BTCUSDT' or parse(data['requested_at'])!=target:
        raise ValueError('market response identity mismatch')
    realtime=data['realtime'];candle=data['candle_1m']
    point=empty_point(offset,target,'unavailable','not_collected')
    if realtime['available']:
        observed=parse(realtime['observed_at'])
        snapshot=realtime['snapshot']
        if observed>target or observed>at or snapshot['provider']!='binance_spot' or snapshot['symbol']!='BTCUSDT':raise ValueError('invalid realtime provenance')
        for k in ('last_trade_price','best_bid','best_ask','spread_bps'):decimal(realtime[k])
        if decimal(realtime['last_trade_price'])<=0 or decimal(realtime['best_bid'])>decimal(realtime['best_ask']):raise ValueError('invalid realtime price')
        point.update(status='available',available=True,reason=None,resolution='realtime_1s',price=realtime['last_trade_price'],
            price_basis='last_trade',price_at=realtime['observed_at'],snapshot_message_id=snapshot['message_id'],
            snapshot_distance_ms=realtime['distance_ms'],bid=realtime['best_bid'],ask=realtime['best_ask'],spread_bps=realtime['spread_bps'])
    elif candle['available']:
        if parse(candle['open_time'])>parse(candle['close_time']) or parse(candle['close_time'])>target or parse(candle['close_time'])>at:raise ValueError('invalid or unfinished candle')
        for k in ('open','high','low','close','base_volume','quote_volume','taker_buy_base_volume','taker_buy_quote_volume'):decimal(candle[k])
        if decimal(candle['close'])<=0:raise ValueError('zero candle price')
        point.update(status='available',available=True,reason=None,resolution='candle_1m',price=candle['close'],price_basis='candle_close',price_at=candle['close_time'],candle={k:v for k,v in candle.items() if k!='available'})
    elif at<target+timedelta(seconds=grace):
        point.update(status='pending',reason='awaiting_market_data')
    else:point['reason']=realtime.get('reason','not_collected')
    return point

def returns(points):
    base=next(p['price'] for p in points if p['offset_seconds']==0)
    for p in points:
        p['return_pct_from_anchor']=p['absolute_return_pct']=None
        if base is not None and p['price'] is not None:
            with localcontext() as ctx:
                ctx.prec=80
                value=((decimal(p['price'])-decimal(base))/decimal(base)*100).quantize(Decimal('0.000000000001'),rounding=ROUND_HALF_EVEN)
                if value==0:value=abs(value)
            p['return_pct_from_anchor']=format(value,'f');p['absolute_return_pct']=format(abs(value),'f')
    return points

def status(points):
    return {'complete':all(p['available'] for p in points),'pending_future_points':sum(p['reason']=='future_target' for p in points),
            'pending_data_points':sum(p['status']=='pending' and p['reason']!='future_target' for p in points),
            'available_points':sum(p['available'] for p in points),'unavailable_points':sum(p['status']=='unavailable' for p in points)}

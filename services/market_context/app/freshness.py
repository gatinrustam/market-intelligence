"""Versioned Stage 4 boundary; discard stale observations before deriving returns."""
from datetime import timedelta
from app.domain import parse,empty_point

FRESHNESS_POLICY='causal_asof_fresh_v1'

def freshness_limits(settings):
    return {'realtime_1s':settings.realtime_max_age_seconds,'candle_1m':settings.candle_max_age_seconds}

def fresh_point(point,limits):
    if not point['available']:
        return {**point,'age_seconds':None,'max_age_seconds':None}
    age=parse(point['target_at'])-parse(point['price_at'])
    if age<timedelta(0):raise ValueError('noncausal market observation')
    limit=limits[point['resolution']]
    metadata={'age_seconds':age.total_seconds(),'max_age_seconds':limit}
    if age>timedelta(seconds=limit):
        # Keep only age diagnostics. No price, candle OHLC, bid/ask, snapshot ID,
        # selected timestamp or derived return may escape via an unavailable point.
        point=empty_point(point['offset_seconds'],parse(point['target_at']),'unavailable','stale_market_data')
    return {**point,**metadata}

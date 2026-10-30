"""Evaluation-only read projection. Never include this in a Stage 4 decision input."""
import asyncio
from datetime import timedelta
from app.domain import now, parse, iso, resolve_point, empty_point
from app.causal import OUTCOME_OFFSETS
from app.freshness import fresh_point, freshness_limits, FRESHNESS_POLICY


async def outcome_view(context, decision_at, market, settings, clock=now):
    cutoff = parse(decision_at)
    semaphore = asyncio.Semaphore(4)

    async def point(offset):
        target = cutoff + timedelta(seconds=offset)
        if target > clock():
            result = empty_point(offset, target, 'pending', 'future_target')
            result.update(age_seconds=None, max_age_seconds=None)
        else:
            async with semaphore:
                data = await market.lookup(target)
            result = fresh_point(resolve_point(offset, target, data, clock(), settings.data_grace_seconds), freshness_limits(settings))
            # An old observation preceding the decision cannot measure its outcome,
            # even when a broad freshness limit would otherwise accept it.
            if result['available'] and parse(result['price_at']) <= cutoff:
                result = {**empty_point(offset, target, 'unavailable', 'no_post_decision_observation'),
                          'age_seconds':result['age_seconds'], 'max_age_seconds':result['max_age_seconds']}
        return {**result, 'role':'outcome'}

    return {'context_id':context['context_id'], 'event':context['event'],
            'market':context['market'], 'decision_at':iso(cutoff),
            'lookup_policy':FRESHNESS_POLICY, 'usage':'evaluation_only',
            'freshness_policy':{'version':FRESHNESS_POLICY,'max_age_seconds':freshness_limits(settings)},
            'points':await asyncio.gather(*(point(offset) for offset in OUTCOME_OFFSETS))}

import asyncio
import copy
import json
from datetime import timedelta
import httpx
from app.domain import now, parse, iso, prepare_input, validate_outcomes, result


class Upstreams:
    def __init__(self, settings):
        self.analysis = httpx.AsyncClient(base_url=settings.analysis_url,timeout=10)
        self.contexts = httpx.AsyncClient(base_url=settings.context_url,timeout=35)
    async def input(self, analysis):
        response = await self.analysis.get('/analyses/'+analysis['analysis_id']+'/input')
        response.raise_for_status()
        value = response.json()
        if value['input_hash'] != analysis['audit']['input_hash']: raise ValueError('input identity mismatch')
        return json.loads(value['canonical_json'])
    async def outcomes(self, prepared, analysis):
        response = await self.contexts.get('/contexts/'+prepared['context_id']+'/outcomes',params={'decision_at':analysis['decision']['decision_at']})
        response.raise_for_status()
        return response.json()
    async def close(self):
        await self.analysis.aclose(); await self.contexts.aclose()


class Worker:
    def __init__(self, repo, upstreams, settings, clock=now):
        self.repo, self.upstreams, self.settings, self.clock = repo, upstreams, settings, clock

    async def calculate(self, job, source, previous):
        analysis = source.payload
        prepared = job.prepared
        if prepared is None:
            package = source.fixture_input if source.origin=='fixture' else await self.upstreams.input(analysis)
            prepared = prepare_input(analysis,package)
        points = validate_outcomes(analysis,await self.upstreams.outcomes(prepared,analysis))
        old = {p['horizon_seconds']:p for p in previous['results']} if previous else {}
        results, next_times = [], []
        for forecast, point in zip(analysis['forecast'], points, strict=True):
            horizon = forecast['horizon_seconds']
            if horizon in old and old[horizon]['status'] in ('evaluated','not_scored'):
                entry = copy.deepcopy(old[horizon])
            else: entry = result(forecast,point,prepared['anchor'],source.policy)
            results.append(entry)
            if entry['status']=='pending':
                next_times.append(max(self.clock()+timedelta(seconds=self.settings.poll_seconds),parse(point['target_at'])))
            elif entry['status']=='unavailable':
                next_times.append(self.clock()+timedelta(seconds=self.settings.unavailable_retry_seconds))
        return prepared, results, min(next_times) if next_times else None

    async def run_once(self):
        claim = await asyncio.to_thread(self.repo.claim)
        if claim is None: return False
        job, source, previous = claim
        try:
            prepared, results, next_at = await asyncio.wait_for(self.calculate(job,source,previous),timeout=50)
            await asyncio.to_thread(self.repo.finish,job,source,prepared,results,next_at)
        except Exception as exc:
            await asyncio.to_thread(self.repo.failure,job,type(exc).__name__)
        return True

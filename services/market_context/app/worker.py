import asyncio,copy
from datetime import timedelta
from app.domain import anchor,OFFSETS,parse,empty_point,resolve_point,returns,now
from app.logging import log
from app.causal import POLICY,validate_points
class ContextWorker:
    def __init__(self,repository,market,settings,clock=now):self.repo=repository;self.market=market;self.settings=settings;self.clock=clock
    async def calculate(self,event,previous):
        a=anchor(event);at=self.clock();old={p['offset_seconds']:p for p in previous['points']} if previous and previous.get('_lookup_policy')==POLICY else {}
        semaphore=asyncio.Semaphore(4)
        async def point(offset):
            if offset in old and old[offset]['available']:return copy.deepcopy(old[offset])
            if a['at'] is None:return empty_point(offset,None,'unavailable',a['unavailable_reason'])
            target=parse(a['at'])+timedelta(seconds=offset)
            if target>at:return empty_point(offset,target,'pending','future_target')
            async with semaphore:data=await self.market.lookup(target)
            return resolve_point(offset,target,data,self.clock(),self.settings.data_grace_seconds)
        points=returns(await asyncio.gather(*(point(o) for o in OFFSETS)))
        validate_points(points,a)
        next_times=[]
        at=self.clock()
        if a['at'] is not None:
            for p in points:
                if p['available']:continue
                target=parse(p['target_at'])
                if p['reason']=='future_target':next_times.append(max(target,at+timedelta(seconds=1)))
                elif p['status']=='pending':next_times.append(at+timedelta(seconds=2))
                else:next_times.append(at+timedelta(seconds=self.settings.unavailable_retry_seconds))
        return a,points,min(next_times) if next_times else None
    async def run_once(self):
        claimed=await asyncio.to_thread(self.repo.claim)
        if claimed is None:return False
        job,event,previous=claimed
        try:
            a,points,next_at=await asyncio.wait_for(self.calculate(event,previous),timeout=30)
            changed=await asyncio.to_thread(self.repo.finish,job,a,points,next_at)
            log('context_resolved',context_id=job.id,changed=changed)
        except Exception as exc:
            await asyncio.to_thread(self.repo.failure,job,type(exc).__name__)
            log('context_retry',context_id=job.id,error_type=type(exc).__name__)
        return True

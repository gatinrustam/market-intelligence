import asyncio
import time
from app.extraction.quality import quality_gate
from app.storage.repository import LeaseLost
from app.logging import log


class EventWorker:
    def __init__(self,repository,extractor,core,bundle,settings):
        self.repository,self.extractor,self.core,self.bundle,self.settings=repository,extractor,core,bundle,settings
    async def run_once(self):
        claimed=await asyncio.to_thread(self.repository.claim)
        if claimed is None:
            return False
        job,document=claimed
        started=time.monotonic()
        context={'job_id':job.id,'document_id':job.document_id,'source_id':document['source']['id'],'attempt':job.attempt_count}
        quality=quality_gate(document,self.bundle.sources.quality)
        try:
            if job.attempt_count>self.settings.max_attempts:
                raise ValueError('processing_attempts_exhausted')
            candidates=await asyncio.to_thread(self.extractor.extract,document)
            result=await asyncio.to_thread(self.core.complete,job,document,candidates,quality,self.extractor.name,self.extractor.version)
            for item in result['events']:
                candidate=next(c for c in candidates if c.candidate_id==item['candidate_id'])
                log('event_committed',**context,**item,event_type=candidate.event_type,rule_id=candidate.matched_rule_ids,
                    correlation_method='exact_key' if item['outcome']!='event_created' else 'new_event')
            log('document_processed',**context,outcome=result['outcome'],duration_ms=round((time.monotonic()-started)*1000))
        except LeaseLost:
            log('job_lease_lost',**context)
        except Exception as exc:
            # DB rollback leaves canonical state untouched. Bounded retries also contain deterministic poison inputs.
            try:
                await asyncio.to_thread(self.repository.failure,job,document,self.bundle,quality,type(exc).__name__,self.extractor.name,self.extractor.version)
            except LeaseLost:
                log('job_lease_lost',**context)
            log('processing_failure',**context,error_type=type(exc).__name__,duration_ms=round((time.monotonic()-started)*1000))
        return True

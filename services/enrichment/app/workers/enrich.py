import asyncio
import time

from app.logging import log
from app.models.errors import ProcessingError
from app.normalization.document import build_document
from app.policies.sufficiency import Decision, EnrichmentPolicy
from app.storage.repository import LeaseLost


class EnrichmentWorker:
    def __init__(self, repository, policies, fetcher, extractor, settings):
        self.repository, self.policies, self.fetcher, self.extractor, self.settings = repository, policies, fetcher, extractor, settings

    async def run_once(self):
        claimed = await asyncio.to_thread(self.repository.claim)
        if claimed is None:
            return False
        job, event = claimed
        started = time.monotonic()
        context = {'job_id': job.id, 'source_message_id': job.source_message_id,
                   'source_id': event['source']['id'], 'attempt': job.attempt_count}
        log('job_claimed', **context)
        policy = self.policies.sources.get(event['source']['id'])
        decision = EnrichmentPolicy(policy).evaluate(event) if policy else Decision(True, 'policy_missing', False)
        snapshot, extracted, error = None, None, None
        try:
            try:
                if policy is None:
                    raise ProcessingError('source_policy_missing', rejected=True)
                if decision.required:
                    snapshot = await asyncio.to_thread(self.repository.snapshot, job)
                    if job.attempt_count > self.settings.max_attempts:
                        raise ProcessingError('attempts_exhausted')
                    if not event['url']:
                        raise ProcessingError('missing_url')
                    if snapshot is None:
                        snapshot = await self.fetcher.fetch(job, event['url'], policy)
                        log('snapshot_stored', **context, snapshot_id=snapshot.id,
                            content_length=snapshot.content_length, status='success')
                    else:
                        log('snapshot_reused', **context, snapshot_id=snapshot.id)
                    extracted = await self.extractor.extract(snapshot)
                    if extracted.reason:
                        error = ProcessingError(extracted.reason, rejected=extracted.status == 'rejected')
            except ProcessingError as exc:
                error = exc
                if exc.transient and job.attempt_count < self.settings.max_attempts:
                    await asyncio.to_thread(self.repository.retry, job, exc)
                    log('job_retry', **context, error_type=exc.reason, status='retry_wait')
                    return True
            result = build_document(event, decision, snapshot=snapshot, extracted=extracted,
                                    error=error, attempts=job.attempt_count)
            await asyncio.to_thread(self.repository.complete, job, result, error)
            log('document_committed', **context, document_id=result['document_id'],
                message_id=result['message_id'], snapshot_id=snapshot.id if snapshot else None,
                status=result['enrichment']['status'], content_length=result['content']['body_length'],
                error_type=error.reason if error else None,
                duration_ms=round((time.monotonic() - started) * 1000))
        except LeaseLost:
            log('job_lease_lost', **context)
        except Exception as exc:
            # DB/process failures retain the lease; a fresh process safely reclaims it.
            # After max attempts, no further HTTP request occurs and a terminal result is produced.
            log('job_processing_error', **context, error_type=type(exc).__name__)
            raise
        return True

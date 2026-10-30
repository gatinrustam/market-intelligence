import hashlib
import json
import random
from datetime import timedelta

from jsonschema.exceptions import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.dialects.mysql import insert

from app.storage.models import (EnrichmentInput, InvalidInput, EnrichmentJob, FetchSnapshot,
                                EnrichedDocument, OutboxEvent, utcnow, new_id)


class LeaseLost(Exception):
    pass


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


class Repository:
    def __init__(self, sessions, input_contract, output_contract, settings):
        self.sessions, self.input_contract, self.output_contract, self.settings = sessions, input_contract, output_contract, settings

    def quarantine(self, session, raw, sequence, reason):
        digest = hashlib.sha256(raw).hexdigest()
        statement = insert(InvalidInput).values(payload_hash=digest, exact_payload=raw,
                                               stream_sequence=sequence, reason=reason, created_at=utcnow())
        session.execute(statement.on_duplicate_key_update(payload_hash=InvalidInput.payload_hash))

    def accept(self, raw: bytes, sequence: int):
        try:
            if len(raw) > 1_000_000:
                raise ValueError('input too large')
            event = json.loads(raw, object_pairs_hook=unique_json)
            self.input_contract.validate(event)
        except (ValueError, UnicodeError, ValidationError, RecursionError):
            with self.sessions.begin() as session:
                self.quarantine(session, raw, sequence, 'invalid_input')
            return 'invalid'
        with self.sessions.begin() as session:
            exists = session.get(EnrichmentInput, event['message_id'])
            statement = insert(EnrichmentInput).values(
                source_message_id=event['message_id'], source_id=event['source']['id'], exact_payload=raw,
                payload=event, payload_hash=hashlib.sha256(raw).hexdigest(),
                stream_sequence=sequence, accepted_at=utcnow())
            session.execute(statement.on_duplicate_key_update(source_message_id=EnrichmentInput.source_message_id))
            stored = session.scalar(select(EnrichmentInput).where(
                EnrichmentInput.source_message_id == event['message_id']).with_for_update().execution_options(populate_existing=True))
            if stored.payload != event:
                self.quarantine(session, raw, sequence, 'identity_conflict')
                return 'identity_conflict'
            statement = insert(EnrichmentJob).values(id=new_id(), source_message_id=event['message_id'],
                status='pending', attempt_count=0, next_retry_at=utcnow(), created_at=utcnow())
            session.execute(statement.on_duplicate_key_update(id=EnrichmentJob.id))
            return 'duplicate' if exists else 'accepted'

    def claim(self):
        now = utcnow()
        with self.sessions.begin() as session:
            job = session.scalar(select(EnrichmentJob).where(
                EnrichmentJob.status.in_(['pending', 'processing', 'retry_wait']),
                EnrichmentJob.next_retry_at <= now,
                or_(EnrichmentJob.lease_until.is_(None), EnrichmentJob.lease_until <= now)
            ).order_by(EnrichmentJob.next_retry_at, EnrichmentJob.id).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return None
            job.status, job.lease_token = 'processing', new_id()
            job.lease_until = now + timedelta(seconds=self.settings.lease_seconds)
            job.attempt_count += 1
            session.flush()
            event = session.get(EnrichmentInput, job.source_message_id).payload
            return job, event

    def locked_job(self, session, job):
        current = session.scalar(select(EnrichmentJob).where(
            EnrichmentJob.id == job.id, EnrichmentJob.lease_token == job.lease_token,
            EnrichmentJob.status == 'processing', EnrichmentJob.lease_until > utcnow()).with_for_update())
        if current is None:
            raise LeaseLost()
        return current

    def snapshot(self, job):
        with self.sessions() as session:
            return session.scalar(select(FetchSnapshot).where(FetchSnapshot.job_id == job.id))

    def save_snapshot(self, job, fields):
        with self.sessions.begin() as session:
            self.locked_job(session, job)
            existing = session.scalar(select(FetchSnapshot).where(FetchSnapshot.job_id == job.id))
            if existing:
                return existing
            snapshot = FetchSnapshot(id=new_id(), job_id=job.id, **fields)
            session.add(snapshot)
            session.flush()
            return snapshot

    def retry(self, job, error):
        with self.sessions.begin() as session:
            row = self.locked_job(session, job)
            delay = min(300, self.settings.retry_base_seconds * 2 ** min(job.attempt_count - 1, 8)) + random.random()
            row.status, row.next_retry_at = 'retry_wait', utcnow() + timedelta(seconds=delay)
            row.last_error_type = row.last_error_message = error.reason
            row.lease_until = row.lease_token = None

    def complete(self, job, event, error=None):
        self.output_contract.validate(event)
        with self.sessions.begin() as session:
            current = self.locked_job(session, job)
            session.add(EnrichedDocument(id=event['document_id'], job_id=job.id,
                source_message_id=job.source_message_id, status=event['enrichment']['status'], payload=event))
            session.flush()
            session.add(OutboxEvent(message_id=event['message_id'], document_id=event['document_id'], payload=event))
            current.status = 'failed' if event['enrichment']['status'] in ('failed', 'rejected') else 'completed'
            current.completed_at = utcnow()
            current.lease_until = current.lease_token = None
            if error:
                current.last_error_type = current.last_error_message = error.reason
                current.failed_at = utcnow()

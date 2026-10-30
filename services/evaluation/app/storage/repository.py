import copy
import hashlib
import json
from datetime import timedelta
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select, or_, func
from sqlalchemy.exc import IntegrityError
from app.domain import canonical, digest, identity, iso, now
from app.storage.contract import Contract
from app.storage.models import EvaluationInput, EvaluationJob, Evaluation, EvaluationResult, EvaluationRevision, OutboxEvent, DeadInput, utcnow, new_id


class Repository:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings
        self.input_contract = Contract(settings.contracts_dir/'analysis/v1.schema.json')
        self.output_contract = Contract(settings.contracts_dir/'evaluation/v1.schema.json')

    def dead(self, raw, reason):
        key = hashlib.sha256(raw).hexdigest()
        try:
            with self.sessions.begin() as s:
                if s.get(DeadInput,key) is None:
                    s.add(DeadInput(id=key,payload=raw.decode(errors='replace'),reason=reason))
        except IntegrityError:
            with self.sessions() as s:
                if s.get(DeadInput,key) is None: raise
        return 'dead'

    def accept(self, raw, sequence, subject, metadata):
        try:
            incoming = json.loads(raw)
            fixture = subject == 'fixture.analysis.completed.v1'
            if fixture:
                if not self.settings.fixtures_enabled or set(incoming) != {'fixture_label','analysis','decision_input'}: raise ValueError('fixture disabled/invalid')
                label, analysis, package = incoming['fixture_label'], incoming['analysis'], incoming['decision_input']
                if not isinstance(label,str) or not 1 <= len(label) <= 100 or not analysis['audit']['model'].startswith('fixture/'): raise ValueError('fixture must be labelled')
            else:
                if subject != 'analysis.completed.v1': raise ValueError('unknown subject')
                label, analysis, package = None, incoming, None
                if analysis['audit']['model'].startswith('fixture/'): raise ValueError('fixture on production subject')
            self.input_contract.validate(analysis)
            if analysis['decision']['historical_simulation'] != (analysis['decision']['decision_basis']=='source_published_at'): raise ValueError('inconsistent decision mode')
            fingerprint = digest({'analysis':analysis,'origin':'fixture' if fixture else 'model','fixture_label':label,'decision_input':package})
        except Exception:
            return self.dead(raw,'invalid_analysis_input')
        try:
            with self.sessions.begin() as s:
                old = s.get(EvaluationInput,analysis['analysis_id'])
                if old is not None:
                    if old.payload_hash == fingerprint: return 'duplicate'
                else:
                    s.add(EvaluationInput(id=analysis['analysis_id'],payload=analysis,payload_hash=fingerprint,
                        exact_payload=raw.decode(),origin='fixture' if fixture else 'model',fixture_label=label,fixture_input=package,
                        provenance={**metadata,'subject':subject,'stream_sequence':sequence},policy=self.settings.policy()))
                    s.flush()
                    s.add(EvaluationJob(id=analysis['analysis_id']))
                    return 'accepted'
        except IntegrityError:
            with self.sessions() as s:
                old = s.get(EvaluationInput,analysis['analysis_id'])
                if old is None: raise
                if old.payload_hash == fingerprint: return 'duplicate'
        return self.dead(raw,'conflicting_analysis_identity')

    def claim(self):
        with self.sessions.begin() as s:
            job = s.scalar(select(EvaluationJob).where(EvaluationJob.status=='active',EvaluationJob.next_attempt_at<=utcnow(),
                or_(EvaluationJob.lease_until.is_(None),EvaluationJob.lease_until<=utcnow())).order_by(EvaluationJob.next_attempt_at).limit(1).with_for_update(skip_locked=True))
            if job is None: return None
            job.lease_token, job.lease_until = new_id(), utcnow()+timedelta(seconds=self.settings.lease_seconds)
            job.attempts += 1
            source = s.get(EvaluationInput,job.id)
            previous = s.get(Evaluation,identity(job.id))
            s.flush()
            return job, source, copy.deepcopy(previous.payload) if previous else None

    def locked(self, s, job):
        row = s.scalar(select(EvaluationJob).where(EvaluationJob.id==job.id).with_for_update())
        return row if row and row.lease_token==job.lease_token and row.status=='active' else None

    def finish(self, job, source, prepared, results, next_at):
        with self.sessions.begin() as s:
            locked = self.locked(s,job)
            if locked is None: return False
            if locked.prepared is not None and locked.prepared != prepared: raise ValueError('frozen anchor changed')
            locked.prepared = copy.deepcopy(prepared)
            key = identity(source.id)
            current = s.get(Evaluation,key)
            changed = current is None or current.payload['results'] != results
            if changed:
                revision = current.revision+1 if current else 1
                message_id = str(uuid5(NAMESPACE_URL,f'evaluation.v1:{key}:{revision}'))
                a = source.payload
                payload = {'schema_version':'1.0','message_id':message_id,'evaluation_id':key,'revision':revision,
                    'analysis':{'analysis_id':source.id,**a['event'],**{k:a['audit'][k] for k in ('model','prompt_version','input_hash')}},
                    'asset':{'symbol':'BTCUSDT'},'decision':copy.deepcopy(a['decision']),
                    'provenance':{'origin':source.origin,'fixture_label':source.fixture_label,'context_id':prepared['context_id'],
                        'event_type':prepared['event_type'],'sources':prepared['sources'],'outcome_policy':'causal_asof_fresh_v1'},
                    'policy':copy.deepcopy(source.policy),'policy_hash':digest(source.policy),'results':copy.deepcopy(results),
                    'status':{'complete':all(r['status'] in ('evaluated','not_scored') for r in results)},'evaluated_at':iso(now())}
                self.output_contract.validate(payload)
                if current is None:
                    current = Evaluation(id=key,analysis_id=source.id,event_id=a['event']['event_id'],origin=source.origin,revision=revision,payload=payload)
                    s.add(current); s.flush()
                else:
                    current.revision, current.payload, current.updated_at = revision,payload,utcnow()
                for result in results:
                    row = s.get(EvaluationResult,(key,result['horizon_seconds']))
                    if row is None:
                        s.add(EvaluationResult(evaluation_id=key,horizon_seconds=result['horizon_seconds'],status=result['status'],payload=result))
                    else: row.status, row.payload = result['status'],copy.deepcopy(result)
                s.add(EvaluationRevision(evaluation_id=key,revision=revision,payload=copy.deepcopy(payload)))
                subject = ('fixture.' if source.origin=='fixture' else '')+('evaluation.created.v1' if revision==1 else 'evaluation.updated.v1')
                s.add(OutboxEvent(evaluation_id=key,revision=revision,message_id=message_id,subject=subject,payload=copy.deepcopy(payload)))
            locked.lease_token = locked.lease_until = locked.error = None
            locked.status = 'complete' if next_at is None else 'active'
            if next_at is not None: locked.next_attempt_at = next_at.replace(tzinfo=None)
            return changed

    def failure(self, job, error):
        with self.sessions.begin() as s:
            row = self.locked(s,job)
            if row is None: return
            row.error = error
            row.lease_until = row.lease_token = None
            row.next_attempt_at = utcnow()+timedelta(seconds=min(300,2**min(row.attempts,8)))

    def view(self, key):
        with self.sessions() as s:
            row = s.get(Evaluation,key)
            return row.payload if row else None

    def stats(self):
        with self.sessions() as s:
            def counts(model,field): return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            return {'inputs':s.scalar(select(func.count()).select_from(EvaluationInput)),
                'evaluations':counts(Evaluation,Evaluation.origin), 'horizons':counts(EvaluationResult,EvaluationResult.status),
                'jobs':counts(EvaluationJob,EvaluationJob.status), 'outbox':counts(OutboxEvent,OutboxEvent.status),
                'revisions':s.scalar(select(func.count()).select_from(EvaluationRevision)),
                'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput))}

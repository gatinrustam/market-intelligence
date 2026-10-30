import copy,hashlib,json
from datetime import timedelta
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import input_identity,identity,digest,build_result
from app.storage.contract import Contract
from app.storage.models import Ruleset,IntelligenceInput,IntelligenceRun,IntelligenceResult,OutboxEvent,DeadInput,utcnow,new_id

class Repository:
    def __init__(self,sessions,settings,configuration):
        self.sessions,self.settings,self.configuration=sessions,settings,configuration
        self.input_contract=Contract(settings.contracts_dir/'event/canonical/v1.schema.json')
        self.output_contract=Contract(settings.contracts_dir/'event/intelligence/v1.schema.json')
    def register(self):
        version=self.configuration['version'];fingerprint=digest(self.configuration)
        try:
            with self.sessions.begin() as s:
                row=s.get(Ruleset,version)
                if row is None:s.add(Ruleset(version=version,configuration=self.configuration,configuration_hash=fingerprint))
                elif row.configuration_hash!=fingerprint:raise ValueError('ruleset version already has different content')
        except IntegrityError:
            with self.sessions() as s:
                row=s.get(Ruleset,version)
                if row is None or row.configuration_hash!=fingerprint:raise ValueError('ruleset version conflict')
    def dead(self,raw,reason):
        key=hashlib.sha256(raw).hexdigest()
        try:
            with self.sessions.begin() as s:
                if s.get(DeadInput,key) is None:s.add(DeadInput(id=key,payload=raw.decode(errors='replace'),reason=reason))
        except IntegrityError:
            with self.sessions() as s:
                if s.get(DeadInput,key) is None:raise
        return 'dead'
    def accept(self,raw,sequence,subject,metadata):
        try:
            event=json.loads(raw);self.input_contract.validate(event)
            if subject not in ('event.detected.v1','event.updated.v1'):raise ValueError('wrong subject')
            if (subject=='event.detected.v1')!=(event['event']['change_type']=='created'):raise ValueError('change type mismatch')
        except Exception:return self.dead(raw,'invalid_canonical_input')
        self.register()
        source=input_identity(event['event']);key=identity(event['event'],self.configuration['version']);fingerprint=digest(event)
        try:
            with self.sessions.begin() as s:
                old=s.get(IntelligenceInput,source)
                if old is not None and old.payload_hash!=fingerprint:conflict=True
                else:
                    conflict=False
                    if old is None:
                        s.add(IntelligenceInput(id=source,event_id=event['event']['id'],event_revision=event['event']['revision'],payload=event,payload_hash=fingerprint,exact_payload=raw.decode(),provenance={**metadata,'subject':subject,'stream_sequence':sequence}));s.flush()
                    if s.get(IntelligenceRun,key) is not None:return 'duplicate'
                    s.add(IntelligenceRun(id=key,input_id=source,ruleset_version=self.configuration['version'],configuration=copy.deepcopy(self.configuration)))
            if conflict:return self.dead(raw,'conflicting_canonical_revision')
        except IntegrityError:
            with self.sessions() as s:
                old=s.get(IntelligenceInput,source)
                if old is None:raise
                if old.payload_hash!=fingerprint:return self.dead(raw,'conflicting_canonical_revision')
                if s.get(IntelligenceRun,key) is None:raise
            return 'duplicate'
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            run=s.scalar(select(IntelligenceRun).where(IntelligenceRun.status=='pending',IntelligenceRun.next_attempt_at<=utcnow(),or_(IntelligenceRun.lease_until.is_(None),IntelligenceRun.lease_until<=utcnow())).order_by(IntelligenceRun.next_attempt_at,IntelligenceRun.id).limit(1).with_for_update(skip_locked=True))
            if run is None:return None
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds);run.attempts+=1;s.flush()
            return run,s.get(IntelligenceInput,run.input_id).payload
    def locked(self,s,run):
        row=s.scalar(select(IntelligenceRun).where(IntelligenceRun.id==run.id).with_for_update())
        return row if row and row.status=='pending' and row.lease_token==run.lease_token else None
    def finish(self,run,snapshot):
        payload=build_result(run,snapshot);self.output_contract.validate(payload)
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row is None:return False
            row.snapshot=copy.deepcopy(snapshot);row.status='complete';row.error=None;row.lease_until=row.lease_token=None
            s.add(IntelligenceResult(id=run.id,event_id=payload['event']['event_id'],event_revision=payload['event']['event_revision'],ruleset_version=run.ruleset_version,payload=payload));s.flush()
            s.add(OutboxEvent(intelligence_id=run.id,message_id=payload['message_id'],payload=copy.deepcopy(payload)))
        return True
    def failure(self,run,error,permanent=False):
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row:
                row.error=error;row.status='failed' if permanent else 'pending';row.lease_until=row.lease_token=None
                row.next_attempt_at=utcnow()+timedelta(seconds=min(300,2**min(row.attempts,8)))
    def view(self,key):
        with self.sessions() as s:
            row=s.get(IntelligenceResult,key)
            return row.payload if row else None
    def stats(self):
        with self.sessions() as s:
            def counts(model,field):return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            distributions={k:{} for k in ('relevance','event_specificity','information_quality','novelty','surprise_status')}
            for p in s.scalars(select(IntelligenceResult.payload).where(IntelligenceResult.ruleset_version==self.configuration['version'])):
                for k,bucket in distributions.items():
                    value=p['surprise']['status'] if k=='surprise_status' else p[k];bucket[value]=bucket.get(value,0)+1
            return {'ruleset_version':self.configuration['version'],'inputs':s.scalar(select(func.count()).select_from(IntelligenceInput)),
                'results_by_ruleset':counts(IntelligenceResult,IntelligenceResult.ruleset_version),'runs':counts(IntelligenceRun,IntelligenceRun.status),
                'outbox':counts(OutboxEvent,OutboxEvent.status),'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput)), 'distributions':distributions}

import copy,hashlib,json
from datetime import timedelta
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import identity,digest,version_key,canonical
from app.pipeline import validate_spans
from app.storage.contract import Contract
from app.storage.models import *

class Repository:
    def __init__(self,sessions,settings,configuration):
        self.sessions,self.settings,self.configuration=sessions,settings,configuration
        self.input_contract=Contract(settings.contracts_dir/'document/enriched/v1.schema.json')
        self.output_contract=Contract(settings.contracts_dir/'document/intelligence/v1.schema.json')
    def register(self):
        version=version_key(self.configuration);h=digest(self.configuration)
        try:
            with self.sessions.begin() as s:
                row=s.get(Configuration,version)
                if row is None:s.add(Configuration(version=version,payload=self.configuration,content_hash=h))
                elif row.content_hash!=h:raise ValueError('version content conflict')
        except IntegrityError:
            with self.sessions() as s:
                if s.get(Configuration,version).content_hash!=h:raise ValueError('version content conflict')
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
            doc=json.loads(raw);self.input_contract.validate(doc)
            if subject!='document.enriched.v1':raise ValueError('subject')
        except Exception:return self.dead(raw,'invalid_enriched_input')
        self.register();source=doc['document_id'];key=identity(doc,self.configuration);h=digest(doc)
        try:
            with self.sessions.begin() as s:
                old=s.get(IntelligenceInput,source)
                if old is not None and old.payload_hash!=h:conflict=True
                else:
                    conflict=False
                    if old is None:
                        s.add(IntelligenceInput(id=source,payload=doc,payload_hash=h,exact_payload=raw.decode(),provenance={**metadata,'subject':subject,'stream_sequence':sequence}));s.flush()
                    if s.get(IntelligenceJob,key) is not None:return 'duplicate'
                    s.add(IntelligenceJob(id=key,input_id=source,version=version_key(self.configuration),configuration=copy.deepcopy(self.configuration)))
            if conflict:return self.dead(raw,'conflicting_document_identity')
        except IntegrityError:
            with self.sessions() as s:
                old=s.get(IntelligenceInput,source)
                if old is None:raise
                if old.payload_hash!=h:return self.dead(raw,'conflicting_document_identity')
                if s.get(IntelligenceJob,key) is None:raise
            return 'duplicate'
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            job=s.scalar(select(IntelligenceJob).where(IntelligenceJob.status=='pending',IntelligenceJob.next_attempt_at<=utcnow(),or_(IntelligenceJob.lease_until.is_(None),IntelligenceJob.lease_until<=utcnow())).order_by(IntelligenceJob.next_attempt_at,IntelligenceJob.id).limit(1).with_for_update(skip_locked=True))
            if job is None:return None
            job.lease_token=new_id();job.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds);job.attempts+=1;s.flush()
            return job,s.get(IntelligenceInput,job.input_id).payload
    def locked(self,s,job):
        row=s.scalar(select(IntelligenceJob).where(IntelligenceJob.id==job.id).with_for_update())
        return row if row and row.status=='pending' and row.lease_token==job.lease_token else None
    def finish(self,job,payload):
        self.output_contract.validate(payload)
        if payload['intelligence_id']!=job.id or payload['extraction']['configuration_hash']!=digest(job.configuration):raise ValueError('output identity')
        with self.sessions.begin() as s:
            row=self.locked(s,job)
            if row is None:return False
            doc=s.get(IntelligenceInput,job.input_id).payload;validate_spans(payload,doc['content']['body'])
            if payload['document']['document_id']!=doc['document_id']:raise ValueError('document mismatch')
            # Stay below broker max payload before committing an undeliverable result.
            if len(json.dumps(payload,ensure_ascii=False).encode())>950_000:raise ValueError('output_too_large')
            row.status=payload['processing']['status'];row.error=None;row.lease_until=row.lease_token=None
            s.add(IntelligenceRun(id=job.id,status=row.status,payload=payload));s.flush()
            for field,model in [('entities',DocumentEntity),('measurements',DocumentMeasurement),('dates',DocumentDate),('relations',DocumentRelation),('facts',DocumentFact),('topics',DocumentTopic)]:
                s.add_all(model(run_id=job.id,ordinal=i,payload=value) for i,value in enumerate(payload[field]))
            s.add(OutboxEvent(intelligence_id=job.id,message_id=job.id,payload=copy.deepcopy(payload)))
        return True
    def failure(self,job,error):
        with self.sessions.begin() as s:
            row=self.locked(s,job)
            if row:
                row.error=error;row.status='failed';row.lease_until=row.lease_token=None
                s.add(IntelligenceRun(id=job.id,status='failed',payload=None))
    def view(self,key):
        with self.sessions() as s:
            row=s.get(IntelligenceRun,key);return row.payload if row else None
    def stats(self):
        with self.sessions() as s:
            def counts(model,field):return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            return {'version':version_key(self.configuration),'inputs':s.scalar(select(func.count()).select_from(IntelligenceInput)),
                'jobs':counts(IntelligenceJob,IntelligenceJob.status),'outbox':counts(OutboxEvent,OutboxEvent.status),'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput))}

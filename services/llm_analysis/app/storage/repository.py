import copy,json,hashlib,random
from datetime import timedelta
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import identity,prompt,canonical,digest
from app.storage.models import AnalysisInput,AnalysisJob,AnalysisRun,AnalysisResult,OutboxEvent,DeadInput,utcnow,new_id
from app.storage.contract import Contract
class Repository:
    def __init__(self,sessions,settings):self.sessions=sessions;self.settings=settings
    def enqueue(self,event,context_id,basis='live',run_key='live',configuration=None,input_id=None):
        config=copy.deepcopy(configuration or self.settings.configuration());_,_,prompt_hash=prompt(config['prompt_version'])
        key=identity(event,config,basis,run_key)
        try:
            with self.sessions.begin() as s:
                old=s.get(AnalysisJob,key)
                if old:
                    if input_id and old.input_id!=input_id:raise ValueError('research run identity input mismatch')
                    return old.id
                if input_id and s.get(AnalysisInput,input_id) is None:raise ValueError('unknown immutable input')
                s.add(AnalysisJob(id=key,event_id=event['event_id'],event_revision=event['event_revision'],context_id=context_id,basis=basis,run_key=run_key,configuration=config,prompt_hash=prompt_hash,input_id=input_id))
        except IntegrityError:
            with self.sessions() as s:
                if s.get(AnalysisJob,key) is None:raise
        return key
    def accept(self,raw,sequence,subject,metadata):
        try:
            event=json.loads(raw);Contract(self.settings.contracts_dir/'event/canonical/v1.schema.json').validate(event)
            if subject not in ('event.detected.v1','event.updated.v1'):raise ValueError('invalid subject')
        except Exception:
            key=hashlib.sha256(raw).hexdigest()
            with self.sessions.begin() as s:
                if s.get(DeadInput,key) is None:s.add(DeadInput(id=key,payload=raw.decode(errors='replace'),reason='invalid_canonical_input'))
            return 'dead'
        e=event['event'];context_id=str(uuid5(NAMESPACE_URL,f"market.context.v1:{e['id']}:{e['revision']}:BTCUSDT"))
        self.enqueue({'event_id':e['id'],'event_revision':e['revision']},context_id)
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            job=s.scalar(select(AnalysisJob).where(AnalysisJob.status=='pending',AnalysisJob.next_attempt_at<=utcnow(),or_(AnalysisJob.lease_until.is_(None),AnalysisJob.lease_until<=utcnow())).order_by(AnalysisJob.next_attempt_at).limit(1).with_for_update(skip_locked=True))
            if job is None:return None
            for run in s.scalars(select(AnalysisRun).where(AnalysisRun.analysis_id==job.id,AnalysisRun.status=='started')):
                run.status='abandoned';run.error='worker_lease_expired_unknown_provider_outcome';run.finished_at=utcnow()
            if job.attempts>=self.settings.max_attempts:
                job.status='failed';job.error='attempt_budget_exhausted';job.lease_token=None;job.lease_until=None
                return None
            job.attempts+=1;job.lease_token=new_id();job.lease_until=utcnow()+timedelta(seconds=self.settings.request_timeout_seconds+60)
            s.flush();return job
    def _locked(self,s,job):
        row=s.scalar(select(AnalysisJob).where(AnalysisJob.id==job.id).with_for_update())
        return row if row.lease_token==job.lease_token and row.status=='pending' else None
    def freeze(self,job,package):
        value=canonical(package);key=digest(package)
        with self.sessions.begin() as s:
            row=self._locked(s,job)
            if row is None:raise ValueError('lost job lease')
            if row.input_id and row.input_id!=key:raise ValueError('immutable input mismatch')
            existing=s.get(AnalysisInput,key)
            if existing is None:
                # Unique content hash; a concurrent research preparation may insert identical bytes.
                try:
                    with s.begin_nested():s.add(AnalysisInput(id=key,canonical_json=value));s.flush()
                except IntegrityError:
                    if s.get(AnalysisInput,key).canonical_json!=value:raise ValueError('input hash collision')
            elif existing.canonical_json!=value:raise ValueError('input hash collision')
            row.input_id=key
        job.input_id=key
        return self.input(key)
    def input(self,key):
        with self.sessions() as s:
            row=s.get(AnalysisInput,key)
            if row is None or digest(json.loads(row.canonical_json))!=key:raise ValueError('input integrity failure')
            return row
    def start_run(self,job,request):
        with self.sessions.begin() as s:
            if self._locked(s,job) is None:raise ValueError('lost job lease')
            run=AnalysisRun(analysis_id=job.id,attempt=job.attempts,request=request);s.add(run);s.flush();return run.id
    def finish(self,job,run_id=None,payload=None,audit=None,error=None,retry=False,invalid=False,blocked=False):
        with self.sessions.begin() as s:
            row=self._locked(s,job)
            if row is None:return False
            if run_id:
                run=s.get(AnalysisRun,run_id);run.response_audit=audit or {};run.error=error;run.finished_at=utcnow();run.status='completed' if payload else 'failed'
            row.lease_until=None;row.lease_token=None;row.error=error
            if payload:
                s.add(AnalysisResult(id=row.id,payload=payload));s.add(OutboxEvent(analysis_id=row.id,message_id=payload['message_id'],payload=payload));row.status='completed'
            else:
                row.invalid_attempts+=int(invalid)
                retry=retry and row.attempts<self.settings.max_attempts and (not invalid or row.invalid_attempts<self.settings.max_invalid_attempts)
                row.status='blocked' if blocked else 'pending' if retry else 'failed'
                row.next_attempt_at=utcnow()+timedelta(seconds=min(300,2**row.attempts)+random.uniform(0,1))
            return True
    def view(self,key):
        with self.sessions() as s:
            job=s.get(AnalysisJob,key)
            if job is None:return None
            result=s.get(AnalysisResult,key);runs=s.scalars(select(AnalysisRun).where(AnalysisRun.analysis_id==key).order_by(AnalysisRun.attempt)).all()
            return {'analysis_id':key,'analysis_status':job.status,'event_id':job.event_id,'event_revision':job.event_revision,'context_id':job.context_id,'basis':job.basis,'run_key':job.run_key,'input_hash':job.input_id,'configuration':job.configuration,'prompt_hash':job.prompt_hash,'error':job.error,'attempts':job.attempts,'analysis':result.payload if result else None,'runs':[{'run_id':r.id,'attempt':r.attempt,'status':r.status,'request':r.request,'response_audit':r.response_audit,'error':r.error} for r in runs]}
    def stats(self):
        with self.sessions() as s:return {'jobs':dict(s.execute(select(AnalysisJob.status,func.count()).group_by(AnalysisJob.status)).all()),'outbox':dict(s.execute(select(OutboxEvent.status,func.count()).group_by(OutboxEvent.status)).all()),'inputs':s.scalar(select(func.count()).select_from(AnalysisInput))}

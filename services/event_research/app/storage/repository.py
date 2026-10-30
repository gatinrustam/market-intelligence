import copy,hashlib,json
from datetime import timedelta
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import identity,digest,build_result,comparison,validate_links
from app.storage.contract import Contract
from app.storage.models import Ruleset,ResearchInput,ResearchRun,ResearchResult,OutboxEvent,DeadInput,CandidateRecord,ComparisonRecord,utcnow,new_id

class Repository:
    def __init__(self,sessions,settings,configuration):
        self.sessions,self.settings,self.configuration=sessions,settings,configuration
        self.input_contract=Contract(settings.contracts_dir/'document/intelligence/v1.schema.json')
        self.output_contract=Contract(settings.contracts_dir/'event/research/v2.schema.json')
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
            event=json.loads(raw);self.input_contract.validate(event);validate_links(event)
            if subject != 'document.intelligence.v1':raise ValueError('wrong subject')
        except Exception:return self.dead(raw,'invalid_document_intelligence')
        self.register()
        source=event['intelligence_id'];key=identity(event,self.configuration);fingerprint=digest(event)
        try:
            with self.sessions.begin() as s:
                old=s.get(ResearchInput,source)
                if old is not None and old.payload_hash!=fingerprint:conflict=True
                else:
                    conflict=False
                    if old is None:
                        s.add(ResearchInput(id=source,document_id=event['document']['document_id'],payload=event,payload_hash=fingerprint,exact_payload=raw.decode(),provenance={**metadata,'subject':subject,'stream_sequence':sequence}));s.flush()
                    if s.get(ResearchRun,key) is not None:return 'duplicate'
                    s.add(ResearchRun(id=key,input_id=source,ruleset_version=self.configuration['version'],configuration=copy.deepcopy(self.configuration)))
            if conflict:return self.dead(raw,'conflicting_intelligence_input')
        except IntegrityError:
            with self.sessions() as s:
                old=s.get(ResearchInput,source)
                if old is None:raise
                if old.payload_hash!=fingerprint:return self.dead(raw,'conflicting_intelligence_input')
                if s.get(ResearchRun,key) is None:raise
            return 'duplicate'
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            run=s.scalar(select(ResearchRun).where(ResearchRun.status=='pending',ResearchRun.next_attempt_at<=utcnow(),or_(ResearchRun.lease_until.is_(None),ResearchRun.lease_until<=utcnow())).order_by(ResearchRun.next_attempt_at,ResearchRun.id).limit(1).with_for_update(skip_locked=True))
            if run is None:return None
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds);run.attempts+=1;s.flush()
            return run,s.get(ResearchInput,run.input_id).payload
    def locked(self,s,run):
        row=s.scalar(select(ResearchRun).where(ResearchRun.id==run.id).with_for_update())
        return row if row and row.status=='pending' and row.lease_token==run.lease_token else None
    def finish(self,run,snapshot):
        payload=build_result(snapshot['intelligence'],snapshot,run.configuration);self.output_contract.validate(payload)
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row is None:return False
            row.snapshot=copy.deepcopy(snapshot);row.status='complete';row.error=None;row.lease_until=row.lease_token=None
            s.add(ResearchResult(id=run.id,document_id=payload['document']['document_id'],ruleset_version=run.ruleset_version,payload=payload));s.flush()
            for candidate in payload['candidates']:s.add(CandidateRecord(id=candidate['candidate_id'],research_id=run.id,event_type=candidate['event_type'],payload=candidate))
            s.add(ComparisonRecord(research_id=run.id,payload=comparison(payload,snapshot)))
            s.add(OutboxEvent(research_id=run.id,message_id=payload['message_id'],payload=copy.deepcopy(payload)))
        return True
    def failure(self,run,error,permanent=False):
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row:
                row.error=error;row.status='failed' if permanent else 'pending';row.lease_until=row.lease_token=None
                row.next_attempt_at=utcnow()+timedelta(seconds=min(300,2**min(row.attempts,8)))
    def view(self,key):
        with self.sessions() as s:
            row=s.get(ResearchResult,key)
            return row.payload if row else None

    def detail(self,key):
        with self.sessions() as s:
            result=s.get(ResearchResult,key)
            if not result:return None
            run=s.get(ResearchRun,key)
            return {'result':result.payload,'comparison':s.get(ComparisonRecord,key).payload,'snapshot':run.snapshot,'configuration':run.configuration}
    def for_document(self,key):
        with self.sessions() as s:
            return [{'result':r.payload,'comparison':s.get(ComparisonRecord,r.id).payload} for r in s.scalars(select(ResearchResult).where(ResearchResult.document_id==key).order_by(ResearchResult.created_at,ResearchResult.id))]
    def catalogue(self,offset,limit):
        with self.sessions() as s:
            q=select(ResearchResult).order_by(ResearchResult.created_at,ResearchResult.id)
            return {'items':[{'result':r.payload,'comparison':s.get(ComparisonRecord,r.id).payload} for r in s.scalars(q.offset(offset).limit(limit))],
                'total':s.scalar(select(func.count()).select_from(ResearchResult))}
    def stats(self):
        with self.sessions() as s:
            def counts(model,field):return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            metrics={k:0 for k in ('documents_total','fact_based','fallback_used','conflict','multiple_candidates','no_event','same_classification','changed_classification')}
            for row in s.scalars(select(ComparisonRecord).join(ResearchResult,ResearchResult.id==ComparisonRecord.research_id).where(ResearchResult.ruleset_version==self.configuration['version'])):
                metrics['documents_total']+=1
                for key,value in row.payload['flags'].items():metrics[key]+=int(value)
            return {'ruleset_version':self.configuration['version'],'inputs':s.scalar(select(func.count()).select_from(ResearchInput)),'runs':counts(ResearchRun,ResearchRun.status),'results_by_ruleset':counts(ResearchResult,ResearchResult.ruleset_version),'outbox':counts(OutboxEvent,OutboxEvent.status),'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput)),'metrics':metrics}

import copy,hashlib,json
from datetime import timedelta
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import identity,digest
from app.storage.contract import Contract
from app.storage.models import Ruleset,SemanticInput,SemanticRun,SemanticResult,OutboxEvent,DeadInput,ReviewItem,HumanLabel,utcnow,new_id

class Repository:
    def __init__(self,sessions,settings,configuration):
        self.sessions,self.settings,self.configuration=sessions,settings,configuration
        self.input_contract=Contract(settings.contracts_dir/'document/intelligence/v1.schema.json')
        self.output_contract=Contract(settings.contracts_dir/'article/semantic/v1.schema.json')
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
            if subject != 'document.intelligence.v1':raise ValueError('wrong subject')
        except Exception:return self.dead(raw,'invalid_document_intelligence')
        self.register()
        source=event['intelligence_id'];key=identity(event,self.configuration);fingerprint=digest(event)
        try:
            with self.sessions.begin() as s:
                old=s.get(SemanticInput,source)
                if old is not None and old.payload_hash!=fingerprint:conflict=True
                else:
                    conflict=False
                    if old is None:
                        s.add(SemanticInput(id=source,document_id=event['document']['document_id'],payload=event,payload_hash=fingerprint,exact_payload=raw.decode(),provenance={**metadata,'subject':subject,'stream_sequence':sequence}));s.flush()
                    if s.get(SemanticRun,key) is not None:return 'duplicate'
                    s.add(SemanticRun(id=key,input_id=source,ruleset_version=self.configuration['version'],configuration=copy.deepcopy(self.configuration)))
            if conflict:return self.dead(raw,'conflicting_intelligence_input')
        except IntegrityError:
            with self.sessions() as s:
                old=s.get(SemanticInput,source)
                if old is None:raise
                if old.payload_hash!=fingerprint:return self.dead(raw,'conflicting_intelligence_input')
                if s.get(SemanticRun,key) is None:raise
            return 'duplicate'
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            run=s.scalar(select(SemanticRun).where(SemanticRun.status=='pending',SemanticRun.ruleset_version==self.configuration['version'],SemanticRun.next_attempt_at<=utcnow(),or_(SemanticRun.lease_until.is_(None),SemanticRun.lease_until<=utcnow())).order_by(SemanticRun.next_attempt_at,SemanticRun.id).limit(1).with_for_update(skip_locked=True))
            if run is None:return None
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds);run.attempts+=1;s.flush()
            return run,s.get(SemanticInput,run.input_id).payload
    def locked(self,s,run):
        row=s.scalar(select(SemanticRun).where(SemanticRun.id==run.id).with_for_update())
        return row if row and row.status=='pending' and row.lease_token==run.lease_token else None
    def finish(self,run,snapshot,payload):
        self.output_contract.validate(payload)
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row is None:return False
            row.snapshot=copy.deepcopy(snapshot);row.status='complete';row.error=None;row.lease_until=row.lease_token=None
            s.add(SemanticResult(id=run.id,document_id=payload['document']['document_id'],ruleset_version=run.ruleset_version,payload=payload));s.flush()
            s.add(ReviewItem(semantic_id=run.id,document_id=payload['document']['document_id'],route=payload['routing']['semantic_suggested_route']))
            s.add(OutboxEvent(semantic_id=run.id,message_id=payload['message_id'],payload=copy.deepcopy(payload)))
        return True
    def failure(self,run,error,permanent=False):
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row:
                row.error=error;row.status='failed' if permanent else 'pending';row.lease_until=row.lease_token=None
                row.next_attempt_at=utcnow()+timedelta(seconds=min(300,2**min(row.attempts,8)))
    def ensure_baseline(self,di,snapshot,observed):
        from app.domain import build_result
        c=self.configuration.get('baseline_configuration')
        if not c:return None
        key=identity(di,c)
        old=self.view(key)
        if old:return old
        baseline_repo=Repository(self.sessions,self.settings,c);baseline_repo.register()
        baseline_repo.accept(json.dumps(di,ensure_ascii=False).encode(),None,'document.intelligence.v1',{'mode':'shared_local_inference_baseline'})
        frozen=copy.deepcopy(snapshot);obs=copy.deepcopy(observed)
        obs['matches']=obs.pop('baseline_matches',[]);obs.pop('reranking_seconds',None)
        frozen['observed']=obs;frozen.pop('baseline',None)
        payload=build_result(di,frozen,c,obs)
        with self.sessions.begin() as session:
            run=session.scalar(select(SemanticRun).where(SemanticRun.id==key).with_for_update())
            if session.get(SemanticResult,key):return session.get(SemanticResult,key).payload
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds)
        baseline_repo.finish(run,frozen,payload)
        return baseline_repo.view(key)

    def view(self,key):
        with self.sessions() as s:
            row=s.get(SemanticResult,key)
            return row.payload if row else None

    def detail(self,key):
        with self.sessions() as s:
            result=s.get(SemanticResult,key)
            if not result:return None
            run=s.get(SemanticRun,key);item=s.get(ReviewItem,key)
            return {'machine':result.payload,'snapshot':run.snapshot,'configuration':run.configuration,
                'review':{'status':item.status,'revision':item.revision,'reviewer':item.reviewer,'created_at':item.created_at.isoformat()+'Z','reviewed_at':item.reviewed_at.isoformat()+'Z' if item.reviewed_at else None},
                'labels':[{'revision':r.revision,'created_at':r.created_at.isoformat()+'Z',**r.payload} for r in s.scalars(select(HumanLabel).where(HumanLabel.semantic_id==key).order_by(HumanLabel.revision))]}
    def label(self,key,body):
        payload=body.model_dump(mode='json')
        for field in ('concepts_correct','false_positives','gold_concepts'):
            if field not in body.model_fields_set:payload.pop(field,None)
        fingerprint=digest({'semantic_id':key,'label':payload})
        with self.sessions.begin() as s:
            item=s.scalar(select(ReviewItem).where(ReviewItem.semantic_id==key).with_for_update())
            if item is None:raise LookupError('Unknown article')
            result=s.get(SemanticResult,key).payload
            if not set(map(str,body.correct_claim_ids)) <= {c['claim_id'] for c in result['claims']}:
                raise ValueError('Unknown claim ID')
            if not set(body.gold_assets) <= {'BTC','ETH','crypto_market','USD','EUR','US_equities','specific_company','rates','gold','RUB','RU_equities','fx_market'}:
                raise ValueError('Unknown asset label')
            allowed={x['id'] for x in self.configuration['ontology']['concepts']}
            if not set(body.gold_concepts)<=allowed:raise ValueError('Unknown concept label')
            if len(body.false_positives)>50 or any(len(x)>300 for x in body.false_positives):raise ValueError('Invalid false-positive labels')
            old=s.get(HumanLabel,str(body.request_id))
            if old:
                if old.request_hash!=fingerprint:raise ValueError('Request ID reused with different content')
                return {'revision':old.revision,'request_id':old.id}
            if item.revision!=body.expected_revision:raise ValueError('Review changed; reload before saving')
            item.revision+=1;item.status=body.status;item.reviewer=body.reviewer;item.reviewed_at=utcnow() if body.status!='new' else None
            s.add(HumanLabel(id=str(body.request_id),semantic_id=key,revision=item.revision,request_hash=fingerprint,payload=payload))
            return {'revision':item.revision,'request_id':str(body.request_id)}
    def for_document(self,key):
        with self.sessions() as s:
            keys=list(s.scalars(select(SemanticResult.id).where(SemanticResult.document_id==key).order_by(SemanticResult.created_at.desc(),SemanticResult.id.desc())))
        return [self.detail(key) for key in keys]
    def catalogue(self,offset,limit):
        with self.sessions() as s:
            q=select(SemanticResult).order_by(SemanticResult.created_at,SemanticResult.id)
            return {'items':[r.payload for r in s.scalars(q.offset(offset).limit(limit))], 'total':s.scalar(select(func.count()).select_from(SemanticResult))}
    def stats(self):
        with self.sessions() as s:
            def counts(model,field):return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            rows=list(s.scalars(select(SemanticResult.payload).where(SemanticResult.ruleset_version==self.configuration['version'])))
            n=len(rows)
            return {'pipeline_version':self.configuration['version'],'inputs':s.scalar(select(func.count()).select_from(SemanticInput)),
                'results_by_version':counts(SemanticResult,SemanticResult.ruleset_version),'runs':dict(s.execute(select(SemanticRun.status,func.count()).where(SemanticRun.ruleset_version==self.configuration['version']).group_by(SemanticRun.status)).all()),
                'all_version_runs':counts(SemanticRun,SemanticRun.status),
                'outbox':counts(OutboxEvent,OutboxEvent.status),'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput)),
                'human_labels':s.scalar(select(func.count()).select_from(HumanLabel)),
                'documents_processed':n,'concepts_per_document':sum(len(r['semantic_concepts']) for r in rows)/n if n else 0,
                'claims_per_document':sum(len(r['claims']) for r in rows)/n if n else 0,
                'assets_per_document':sum(len(r['affected_assets']) for r in rows)/n if n else 0,
                'routing_disagreements':sum(r['routing']['disagreement'] is True for r in rows),
                'documents_with_di_facts':sum(bool(r['facts']) for r in rows),
                'semantic_context_candidates_without_di_facts':sum(bool(r['semantic_concepts']) and not r['facts'] for r in rows),
                'conflicts_with_di':sum(bool(r['conflicts']) for r in rows)}

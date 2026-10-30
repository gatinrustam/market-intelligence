import copy,hashlib,json
from datetime import timedelta
from sqlalchemy import select,or_,func
from sqlalchemy.exc import IntegrityError
from app.domain import identity,digest,build_result
from app.storage.contract import Contract
from app.storage.models import Ruleset,RoutingInput,RoutingRun,RoutingResult,OutboxEvent,DeadInput,ReviewItem,HumanLabel,utcnow,new_id

class Repository:
    def __init__(self,sessions,settings,configuration):
        self.sessions,self.settings,self.configuration=sessions,settings,configuration
        self.input_contract=Contract(settings.contracts_dir/'document/intelligence/v1.schema.json')
        self.output_contract=Contract(settings.contracts_dir/'article/routing/v1.schema.json')
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
                old=s.get(RoutingInput,source)
                if old is not None and old.payload_hash!=fingerprint:conflict=True
                else:
                    conflict=False
                    if old is None:
                        s.add(RoutingInput(id=source,document_id=event['document']['document_id'],payload=event,payload_hash=fingerprint,exact_payload=raw.decode(),provenance={**metadata,'subject':subject,'stream_sequence':sequence}));s.flush()
                    if s.get(RoutingRun,key) is not None:return 'duplicate'
                    s.add(RoutingRun(id=key,input_id=source,ruleset_version=self.configuration['version'],configuration=copy.deepcopy(self.configuration)))
            if conflict:return self.dead(raw,'conflicting_intelligence_input')
        except IntegrityError:
            with self.sessions() as s:
                old=s.get(RoutingInput,source)
                if old is None:raise
                if old.payload_hash!=fingerprint:return self.dead(raw,'conflicting_intelligence_input')
                if s.get(RoutingRun,key) is None:raise
            return 'duplicate'
        return 'accepted'
    def claim(self):
        with self.sessions.begin() as s:
            run=s.scalar(select(RoutingRun).where(RoutingRun.status=='pending',RoutingRun.next_attempt_at<=utcnow(),or_(RoutingRun.lease_until.is_(None),RoutingRun.lease_until<=utcnow())).order_by(RoutingRun.next_attempt_at,RoutingRun.id).limit(1).with_for_update(skip_locked=True))
            if run is None:return None
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=self.settings.lease_seconds);run.attempts+=1;s.flush()
            return run,s.get(RoutingInput,run.input_id).payload
    def locked(self,s,run):
        row=s.scalar(select(RoutingRun).where(RoutingRun.id==run.id).with_for_update())
        return row if row and row.status=='pending' and row.lease_token==run.lease_token else None
    def finish(self,run,snapshot):
        payload=build_result(snapshot['intelligence'],snapshot,run.configuration);self.output_contract.validate(payload)
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row is None:return False
            row.snapshot=copy.deepcopy(snapshot);row.status='complete';row.error=None;row.lease_until=row.lease_token=None
            s.add(RoutingResult(id=run.id,document_id=payload['document']['document_id'],ruleset_version=run.ruleset_version,payload=payload));s.flush()
            s.add(ReviewItem(routing_id=run.id,document_id=payload['document']['document_id'],route=payload['classification']['route']))
            s.add(OutboxEvent(routing_id=run.id,message_id=payload['message_id'],payload=copy.deepcopy(payload)))
        return True
    def failure(self,run,error,permanent=False):
        with self.sessions.begin() as s:
            row=self.locked(s,run)
            if row:
                row.error=error;row.status='failed' if permanent else 'pending';row.lease_until=row.lease_token=None
                row.next_attempt_at=utcnow()+timedelta(seconds=min(300,2**min(row.attempts,8)))
    def view(self,key):
        with self.sessions() as s:
            row=s.get(RoutingResult,key)
            return row.payload if row else None

    def detail(self,key):
        with self.sessions() as s:
            result=s.get(RoutingResult,key)
            if not result:return None
            run=s.get(RoutingRun,key);item=s.get(ReviewItem,key)
            return {'machine':result.payload,'snapshot':run.snapshot,'configuration':run.configuration,
                'review':{'status':item.status,'revision':item.revision,'reviewer':item.reviewer,'created_at':item.created_at.isoformat()+'Z','reviewed_at':item.reviewed_at.isoformat()+'Z' if item.reviewed_at else None},
                'labels':[{'revision':r.revision,'created_at':r.created_at.isoformat()+'Z',**r.payload} for r in s.scalars(select(HumanLabel).where(HumanLabel.routing_id==key).order_by(HumanLabel.revision))]}
    def label(self,key,body):
        payload=body.model_dump(mode='json');fingerprint=digest({'routing_id':key,'label':payload})
        with self.sessions.begin() as s:
            item=s.scalar(select(ReviewItem).where(ReviewItem.routing_id==key).with_for_update())
            if item is None:raise LookupError('Unknown article')
            old=s.get(HumanLabel,str(body.request_id))
            if old:
                if old.request_hash!=fingerprint:raise ValueError('Request ID reused with different content')
                return {'revision':old.revision,'request_id':old.id}
            if item.revision!=body.expected_revision:raise ValueError('Review changed; reload before saving')
            item.revision+=1;item.status=body.status;item.reviewer=body.reviewer;item.reviewed_at=utcnow() if body.status!='new' else None
            s.add(HumanLabel(id=str(body.request_id),routing_id=key,revision=item.revision,request_hash=fingerprint,payload=payload))
            return {'revision':item.revision,'request_id':str(body.request_id)}
    def articles(self,offset,limit):
        with self.sessions() as s:
            # Page immutable result IDs before reading JSON. Large article bodies and
            # complete DI snapshots never cross this catalogue query boundary.
            latest={}
            for key,document_id in s.execute(select(RoutingResult.id,RoutingResult.document_id).order_by(RoutingResult.created_at.desc(),RoutingResult.id)):
                if document_id not in latest:latest[document_id]=key
            keys=list(latest.values())[offset:offset+limit]
            if not keys:return {'items':[],'total':len(latest)}
            snap=RoutingRun.snapshot
            query=select(RoutingResult.id,RoutingResult.document_id,RoutingResult.payload,
                snap['document']['content']['title'].as_string(),snap['document']['timestamps']['published_at'].as_string(),
                snap['document']['source'],snap['document']['content']['language'].as_string(),
                snap['document']['classification']['categories'],snap['intelligence']['topics'],snap['events'],
                RoutingRun.configuration['source_metadata'],ReviewItem.status).join(RoutingRun,RoutingRun.id==RoutingResult.id).join(ReviewItem,ReviewItem.routing_id==RoutingResult.id).where(RoutingResult.id.in_(keys))
            rows={}
            for key,document_id,p,title,published,source,language,categories,topics,events,metadata,status in s.execute(query):
                external=source.get('external_id') or ''
                rows[key]={'id':key,'document_id':document_id,'title':title,'published':published,'source':source['id'],'language':language,
                    'topics':sorted({t['topic'] for t in topics or []}|{t for e in events or [] for t in e['taxonomy']['topics']}),
                    'route':p['classification']['route'],**p['features'],'review_status':status,
                    'source_metadata':(metadata or {}).get(source['id'],{}),'categories':categories or [],
                    'incident_id':external.split('/')[1] if external.startswith('incident/') else None}
            return {'items':[rows[key] for key in keys if key in rows],'total':len(latest)}
    def repeated(self,di,document):
        with self.sessions() as s:
            for run in s.scalars(select(RoutingRun).where(RoutingRun.status=='complete',RoutingRun.input_id!=di['intelligence_id'])):
                old=run.snapshot['document']
                if old['source']['id']==document['source']['id'] and old['lineage']['source_message_id']==document['lineage']['source_message_id']:return True
        return False
    def stats(self):
        with self.sessions() as s:
            def counts(model,field):return dict(s.execute(select(field,func.count()).select_from(model).group_by(field)).all())
            routes={k:0 for k in ('critical','important','review','low','archive')}
            for p in s.scalars(select(RoutingResult.payload).where(RoutingResult.ruleset_version==self.configuration['version'])):routes[p['classification']['route']]+=1
            return {'ruleset_version':self.configuration['version'],'inputs':s.scalar(select(func.count()).select_from(RoutingInput)),
                'results_by_ruleset':counts(RoutingResult,RoutingResult.ruleset_version),'runs':counts(RoutingRun,RoutingRun.status),
                'outbox':counts(OutboxEvent,OutboxEvent.status),'dead_inputs':s.scalar(select(func.count()).select_from(DeadInput)), 'routes':routes,'human_labels':s.scalar(select(func.count()).select_from(HumanLabel))}

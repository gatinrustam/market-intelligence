import copy,hashlib,json,random
from datetime import timedelta
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,or_,update,func
from sqlalchemy.dialects.mysql import insert
from jsonschema.exceptions import ValidationError
from app.storage.models import ContextInput,DeadInput,MarketContext,MarketContextPoint,ContextJob,ContextRevision,OutboxEvent,new_id,utcnow
from app.domain import status,iso,UTC
from app.causal import POLICY,validate_points

def unique_json(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate key')
        result[k]=v
    return result

def reject_constant(value):raise ValueError('nonfinite JSON')
def identity(event):return str(uuid5(NAMESPACE_URL,f"market.context.v1:{event['event']['id']}:{event['event']['revision']}:BTCUSDT"))
class LeaseLost(Exception):pass
class Repository:
    def __init__(self,sessions,input_contract,output_contract,settings):
        self.sessions=sessions;self.input_contract=input_contract;self.output_contract=output_contract;self.settings=settings
    def quarantine(self,s,raw,subject,reason):
        statement=insert(DeadInput).values(payload_hash=hashlib.sha256(raw).hexdigest(),exact_payload=raw,subject=subject,reason=reason)
        s.execute(statement.on_duplicate_key_update(payload_hash=DeadInput.payload_hash))
    def accept(self,raw,sequence,subject,metadata=None):
        try:
            if len(raw)>1000000:raise ValueError('size limit')
            event=json.loads(raw,object_pairs_hook=unique_json,parse_constant=reject_constant)
            self.input_contract.validate(event)
            if subject!={'created':'event.detected.v1','updated':'event.updated.v1'}[event['event']['change_type']]:raise ValueError('subject mismatch')
            key=identity(event)
        except (ValueError,ValidationError,UnicodeError,RecursionError) as exc:
            with self.sessions.begin() as s:self.quarantine(s,raw,subject,type(exc).__name__)
            return 'invalid'
        with self.sessions.begin() as s:
            existing=s.get(ContextInput,key)
            statement=insert(ContextInput).values(id=key,event_id=event['event']['id'],event_revision=event['event']['revision'],symbol='BTCUSDT',
                input_message_id=event['message_id'],exact_payload=raw,payload=event,subject=subject,jetstream_metadata=metadata or {'stream_sequence':sequence})
            s.execute(statement.on_duplicate_key_update(id=ContextInput.id))
            stored=s.scalar(select(ContextInput).where(ContextInput.id==key).with_for_update().execution_options(populate_existing=True))
            left,right=dict(stored.payload),dict(event);left.pop('message_id');right.pop('message_id')
            if left!=right:
                self.quarantine(s,raw,subject,'event_revision_identity_conflict');return 'identity_conflict'
            statement=insert(ContextJob).values(id=key,status='pending',attempts=0,next_attempt_at=utcnow())
            s.execute(statement.on_duplicate_key_update(id=ContextJob.id))
            return 'duplicate' if existing else 'accepted'
    def claim(self):
        at=utcnow()
        with self.sessions.begin() as s:
            job=s.scalar(select(ContextJob).where(ContextJob.status.in_(['pending','processing']),ContextJob.next_attempt_at<=at,
                or_(ContextJob.lease_until.is_(None),ContextJob.lease_until<=at)).order_by(ContextJob.next_attempt_at,ContextJob.id).limit(1).with_for_update(skip_locked=True))
            if job is None:return None
            job.status='processing';job.lease_token=new_id();job.lease_until=at+timedelta(seconds=self.settings.lease_seconds);job.attempts+=1
            context=s.get(MarketContext,job.id);s.flush()
            previous=copy.deepcopy(context.payload) if context else None
            if previous is not None:previous['_lookup_policy']=context.lookup_policy
            return job,copy.deepcopy(s.get(ContextInput,job.id).payload),previous
    def finish(self,job,anchor,points,next_at):
        with self.sessions.begin() as s:
            leased=s.scalar(select(ContextJob).where(ContextJob.id==job.id,ContextJob.lease_token==job.lease_token,ContextJob.lease_until>utcnow()).with_for_update())
            if leased is None:raise LeaseLost()
            context=s.get(MarketContext,job.id);input_row=s.get(ContextInput,job.id)
            changed=context is None or context.lookup_policy!=POLICY or context.payload['points']!=points or context.payload['anchor']!=anchor
            if changed:
                revision=1 if context is None else context.revision+1
                payload={'schema_version':'1.0','message_id':new_id(),'context_id':job.id,'revision':revision,
                    'event':{'event_id':input_row.event_id,'event_revision':input_row.event_revision},'market':{'provider':'binance_spot','symbol':'BTCUSDT'},
                    'anchor':anchor,'points':points,'status':status(points),'generated_at':iso(utcnow().replace(tzinfo=UTC))}
                self.output_contract.validate(payload)
                validate_points(points,anchor)
                if context is None:
                    context=MarketContext(lookup_policy=POLICY,id=job.id,event_id=input_row.event_id,event_revision=input_row.event_revision,revision=revision,payload=copy.deepcopy(payload));s.add(context);s.flush()
                else:context.lookup_policy=POLICY;context.revision=revision;context.payload=copy.deepcopy(payload);context.updated_at=utcnow()
                for p in points:
                    row=s.get(MarketContextPoint,(job.id,p['offset_seconds']))
                    if row:row.payload=copy.deepcopy(p)
                    else:s.add(MarketContextPoint(context_id=job.id,offset_seconds=p['offset_seconds'],payload=copy.deepcopy(p)))
                s.add(ContextRevision(lookup_policy=POLICY,context_id=job.id,revision=revision,message_id=payload['message_id'],payload=copy.deepcopy(payload)))
                s.add(OutboxEvent(context_id=job.id,revision=revision,message_id=payload['message_id'],subject='market.context.created.v1' if revision==1 else 'market.context.updated.v1',payload=copy.deepcopy(payload)))
            leased.status='pending' if next_at else 'completed';leased.next_attempt_at=next_at.astimezone(UTC).replace(tzinfo=None) if next_at else utcnow()
            leased.lease_until=leased.lease_token=None;leased.last_error=None;leased.attempts=0
            return changed
    def failure(self,job,error):
        with self.sessions.begin() as s:
            s.execute(update(ContextJob).where(ContextJob.id==job.id,ContextJob.lease_token==job.lease_token).values(
                status='pending',lease_token=None,lease_until=None,last_error=error,next_attempt_at=utcnow()+timedelta(seconds=min(300,2**min(job.attempts,8))+random.random())))
    def stats(self):
        with self.sessions() as s:
            def count(cls,*where):return s.scalar(select(func.count()).select_from(cls).where(*where))
            return {'inputs_total':count(ContextInput),'contexts_total':count(MarketContext),'points_total':count(MarketContextPoint),'revisions_total':count(ContextRevision),
                'jobs':dict(s.execute(select(ContextJob.status,func.count()).group_by(ContextJob.status)).all()),
                'jobs_with_error':count(ContextJob,ContextJob.last_error.is_not(None)),
                'outbox_pending':count(OutboxEvent,OutboxEvent.status=='pending'),'outbox_dead':count(OutboxEvent,OutboxEvent.status=='dead'),'dead_inputs':count(DeadInput)}

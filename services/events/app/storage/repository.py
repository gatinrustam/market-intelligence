import hashlib
import copy
import json
import random
from datetime import timedelta
from jsonschema.exceptions import ValidationError
from sqlalchemy import or_,select
from sqlalchemy.dialects.mysql import insert
from app.storage.models import EventInput,DeadInput,EventJob,ExtractionRun,utcnow,new_id


class LeaseLost(Exception):
    pass


def reject_nonfinite(value):
    raise ValueError("nonfinite_json_number")


def unique_json(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key]=value
    return result


class Repository:
    def __init__(self,sessions,input_contract,settings):
        self.sessions,self.input_contract,self.settings=sessions,input_contract,settings
    def quarantine(self,session,raw,subject,metadata,reason):
        statement=insert(DeadInput).values(payload_hash=hashlib.sha256(raw).hexdigest(),exact_payload=raw,
            validation_error=reason,subject=subject,jetstream_metadata=metadata,received_at=utcnow())
        session.execute(statement.on_duplicate_key_update(payload_hash=DeadInput.payload_hash))
    def accept(self,raw,sequence,subject='document.enriched.v1',metadata=None):
        metadata=metadata or {'stream_sequence':sequence}
        try:
            if len(raw)>1_000_000:
                raise ValueError('input_size_limit')
            document=json.loads(raw,object_pairs_hook=unique_json,parse_constant=reject_nonfinite)
            json.dumps(document,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.input_contract.validate(document)
        except (ValueError,UnicodeError,ValidationError,RecursionError) as exc:
            # Never store exception text containing body/credentials in normal errors/logs.
            reason=('schema:'+str(exc.validator)+':'+'.'.join(map(str,exc.absolute_schema_path)))[:512] if isinstance(exc,ValidationError) else type(exc).__name__
            with self.sessions.begin() as session:
                self.quarantine(session,raw,subject,metadata,reason)
            return 'invalid'
        with self.sessions.begin() as session:
            exists=session.get(EventInput,document['document_id'])
            statement=insert(EventInput).values(document_id=document['document_id'],input_message_id=document['message_id'],
                source_id=document['source']['id'],exact_payload=raw,payload=document,
                payload_hash=hashlib.sha256(raw).hexdigest(),stream_sequence=sequence,received_at=utcnow())
            session.execute(statement.on_duplicate_key_update(document_id=EventInput.document_id))
            stored=session.scalar(select(EventInput).where(EventInput.document_id==document['document_id']).with_for_update().execution_options(populate_existing=True))
            # Replayed equivalent document may have another transport message ID.
            left,right=dict(stored.payload),dict(document)
            left.pop('message_id');right.pop('message_id')
            if left!=right:
                self.quarantine(session,raw,subject,metadata,'document_identity_conflict')
                return 'identity_conflict'
            statement=insert(EventJob).values(id=new_id(),document_id=document['document_id'],status='pending',
                attempt_count=0,next_retry_at=utcnow(),created_at=utcnow())
            session.execute(statement.on_duplicate_key_update(id=EventJob.id))
            return 'duplicate' if exists else 'accepted'
    def claim(self):
        now=utcnow()
        with self.sessions.begin() as session:
            job=session.scalar(select(EventJob).where(EventJob.status.in_(['pending','processing','retry_wait']),
                EventJob.next_retry_at<=now,or_(EventJob.lease_until.is_(None),EventJob.lease_until<=now))
                .order_by(EventJob.next_retry_at,EventJob.id).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return None
            job.status,job.lease_token,job.lease_until='processing',new_id(),now+timedelta(seconds=self.settings.lease_seconds)
            job.attempt_count+=1
            session.flush()
            return job,session.get(EventInput,job.document_id).payload
    def locked_job(self,session,job):
        row=session.scalar(select(EventJob).where(EventJob.id==job.id,EventJob.lease_token==job.lease_token,
            EventJob.status=='processing',EventJob.lease_until>utcnow()).with_for_update())
        if row is None:
            raise LeaseLost()
        return row
    def record_run(self,session,job,document,bundle,quality,result,extractor_name,extractor_version):
        run=ExtractionRun(id=new_id(),job_id=job.id if job else None,document_id=document['document_id'],
            extractor_name=extractor_name,extractor_version=extractor_version,ruleset_version=bundle.rules.version,
            taxonomy_version=bundle.taxonomy.version,entity_registry_version=bundle.registry.version,
            config_hash=bundle.fingerprint(),configuration=bundle.model_dump(),input_quality=quality.model_dump(),result_json=copy.deepcopy(result))
        session.add(run);session.flush()
        return run
    def failure(self,job,document,bundle,quality,error_type,extractor_name,extractor_version):
        with self.sessions.begin() as session:
            row=self.locked_job(session,job)
            row.last_error_type=error_type
            row.lease_until=row.lease_token=None
            if job.attempt_count>=self.settings.max_attempts:
                row.status,row.outcome='failed','failed'
                row.failed_at=row.completed_at=utcnow()
                self.record_run(session,job,document,bundle,quality,{'outcome':'failed','error_type':error_type,'candidates':[]},extractor_name,extractor_version)
            else:
                row.status='retry_wait'
                delay=min(300,self.settings.retry_base_seconds*2**(job.attempt_count-1))+random.random()
                row.next_retry_at=utcnow()+timedelta(seconds=delay)

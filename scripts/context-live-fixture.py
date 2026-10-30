"""Insert ONE explicitly labelled synthetic current event into resolver-owned input storage.
No publication to the Stage 2 EVENTS stream and no mutation of Stage 2 records.
Run: docker compose exec -T market-context python - < scripts/context-live-fixture.py
"""
import copy,json,urllib.request
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from app.config import Settings
from app.storage.database import make_database
from app.storage.contract import CanonicalContract,ContextContract
from app.storage.repository import Repository,identity
from app.storage.models import ContextInput

settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value())
repo=Repository(sessions,CanonicalContract(settings.input_schema_path),ContextContract(settings.output_schema_path),settings)
uid=lambda role:str(uuid5(NAMESPACE_URL,'market-context-stage35-live-smoke:'+role))
with sessions() as s:
    existing=s.scalar(select(ContextInput).where(ContextInput.event_id==uid('event')))
    if existing:
        print(json.dumps({'status':'existing','event_id':existing.event_id,'context_id':existing.id,'anchor':existing.payload['time']['event_time']}))
    else:
        source=s.scalar(select(ContextInput).limit(1));assert source
        event=copy.deepcopy(source.payload)
        stats=json.load(urllib.request.urlopen(settings.market_data_url+'/stats'))
        target=stats['last_snapshot_at'];assert target and stats['provider_connected']
        event['message_id']=uid('message');event['event']={'id':uid('event'),'revision':1,'change_type':'created'}
        event['taxonomy'].update(event_type='unknown',topics=[],classification_basis='fallback')
        event['content']['canonical_title']='SYNTHETIC STAGE 3.5 LIVE SMOKE FIXTURE — not a real market announcement'
        event['actors']=[];event['jurisdictions']=[]
        event['time'].update(event_time=target,event_time_precision='exact',event_time_source='body',earliest_source_published_at=target,latest_source_published_at=target,first_detected_at=target,last_updated_at=target)
        event['lifecycle']={'status':'detected'}
        doc=copy.deepcopy(event['evidence']['documents'][0]);doc.update(document_id=uid('document'),input_message_id=uid('document_input'),source_message_id=uid('source_message'),source_id='market_context_smoke_fixture',relation='primary',document_status='ready',content_chars=0,quality='low',extraction_run_id=uid('extraction'))
        event['evidence']={'quality':'low','document_count':1,'independent_source_count':1,'documents':[doc]}
        event['extraction'].update(extractor='synthetic_smoke_fixture',matched_rule_ids=[],configuration_hash='0'*64)
        event['correlation']={'method':'new_event','exact_event_key':None}
        result=repo.accept(json.dumps(event).encode(),0,'event.detected.v1',{'synthetic_fixture':True,'source':'scripts/context-live-fixture.py'})
        assert result=='accepted'
        print(json.dumps({'status':result,'event_id':event['event']['id'],'context_id':identity(event),'anchor':target}))
engine.dispose()

"""Read-only real-data verification. Run inside events container via stdin."""
import asyncio,json,hashlib,urllib.request
from collections import Counter
from datetime import datetime,timezone
from sqlalchemy import select
from app.config import Settings
from app.storage.contract import CanonicalContract
from app.storage.database import make_database
from app.storage.models import EventInput,Event,EventDocument,EventRevision,EventJob,ExtractionRun,OutboxEvent,CorrelationSuggestion
from app.publishers.nats import JetStreamBus


async def main():
 settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value())
 contract=CanonicalContract(settings.output_schema_path);bus=JetStreamBus(settings.nats_url.get_secret_value())
 try:
  await bus.connect()
  with sessions() as s:
   inputs=list(s.scalars(select(EventInput)));events=list(s.scalars(select(Event)))
   revisions=list(s.scalars(select(EventRevision)));outbox=list(s.scalars(select(OutboxEvent)))
   relations=list(s.scalars(select(EventDocument)));jobs=list(s.scalars(select(EventJob)))
   runs=list(s.scalars(select(ExtractionRun)))
   suggestions=list(s.scalars(select(CorrelationSuggestion)))
  assert len(inputs)==len(jobs)==len(runs)==55
  assert all(j.status=='completed' for j in jobs) and all(o.status=='published' for o in outbox)
  for inp in inputs:
   stored=await bus.js.get_msg('DOCUMENT_ENRICHED',seq=inp.stream_sequence)
   assert stored.data==inp.exact_payload
   assert hashlib.sha256(inp.exact_payload).hexdigest()==inp.payload_hash
  info=await bus.js.stream_info('EVENTS');published={}
  for seq in range(info.state.first_seq,info.state.last_seq+1):
   msg=await bus.js.get_msg('EVENTS',seq=seq)
   payload=json.loads(msg.data);contract.validate(payload)
   expected='event.detected.v1' if payload['event']['change_type']=='created' else 'event.updated.v1'
   assert msg.subject==expected
   published[payload['message_id']]=payload
  for revision in revisions:
   contract.validate(revision.payload)
   assert published[revision.message_id]==revision.payload
  by_id={e.id:e for e in events};by_document={r.document_id:r.event_id for r in relations}
  for run in runs:
   assert run.result_json['events']
   assert all(item['event_id']==by_document[run.document_id] for item in run.result_json['events'])
   assert hashlib.sha256(json.dumps(run.configuration,sort_keys=True,separators=(',',':')).encode()).hexdigest()==run.config_hash
  records=[]
  for inp in inputs:
   event=by_id[by_document[inp.document_id]];p=event.payload
   records.append({'document_id':inp.document_id,'source_id':inp.source_id,'title':inp.payload['content']['title'],
    'url':inp.payload['source']['url'],'published_at':inp.payload['timestamps']['published_at'],
    'event_id':event.id,'event_type':event.event_type,'event_time':p['time']['event_time'],
    'exact_event_key':event.exact_event_key,'quality':p['evidence']['quality'],'classification_basis':p['taxonomy']['classification_basis'],
    'rule_ids':p['extraction']['matched_rule_ids']})
  def choose(predicate):
   found=[r for r in records if predicate(r)]
   assert len(found)==1,found
   return found[0]
  april=choose(lambda r:'monetary20260429a.htm' in (r['url'] or ''))
  june=choose(lambda r:'monetary20260617a.htm' in (r['url'] or ''))
  projections=choose(lambda r:'monetary20260617b.htm' in (r['url'] or ''))
  assert len({r['event_id'] for r in [april,june,projections]})==3
  sec=[r for r in records if r['source_id']=='sec_press_releases']
  assert len({r['event_id'] for r in sec})==len(sec)==25
  lagarde=choose(lambda r:r['title']=='Christine Lagarde: Interview with Ouest-France')
  pdf=choose(lambda r:r['title']=='Philip R. Lane: Diversity at the European Central Bank')
  sec_sample=choose(lambda r:r['title']=='SEC Announces Roundtable on Preparations for 24-Hour Trading')
  examples={label:by_id[r['event_id']].payload for label,r in [('Fed FOMC statement',april),('ECB Lagarde interview',lagarde),('ECB PDF speech',pdf),('SEC partial RSS event',sec_sample)]}
  quality=Counter(e.payload['evidence']['quality'] for e in events)
  stats=json.loads(urllib.request.urlopen('http://127.0.0.1:8002/stats',timeout=5).read())
  print(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'stats':stats,
   'events_by_type':dict(sorted(Counter(e.event_type for e in events).items())),
   'evidence_quality':{q:quality[q] for q in ['high','medium','low']},
   'fallback_events':sum(e.payload['taxonomy']['classification_basis']=='fallback' for e in events),
   'actual_exact_correlations':sum(r.revision>1 for r in revisions),
   'verified_exact_inputs':len(inputs),'verified_published_revisions':len(revisions),
   'false_merge_inspection':{'fed':[april,june,projections],'sec_documents':len(sec),'sec_distinct_events':len({r['event_id'] for r in sec})},
   'examples':examples,'documents':sorted(records,key=lambda r:(r['source_id'],r['url'] or ''))},ensure_ascii=False,indent=2))
 finally:
  await bus.close();engine.dispose()

asyncio.run(main())

"""Read-only audit of completed DI-5 runs, exact NATS payloads and frozen replay.
Run inside article-semantic after the research corpus completes.
"""
import asyncio,json
from sqlalchemy import select
from app.config import Settings
from app.domain import load_configuration,build_result,digest
from app.storage.database import make_database
from app.storage.models import SemanticResult,SemanticRun,SemanticInput,OutboxEvent
from app.storage.contract import Contract
from app.publishers.nats import JetStreamBus
async def main():
 settings=Settings();configuration=load_configuration(settings)
 engine,sessions=make_database(settings.database_url.get_secret_value());bus=JetStreamBus(settings.nats_url.get_secret_value())
 await bus.connect();report=[];archived=[];wire={}
 info=await bus.js.stream_info('ARTICLE_SEMANTIC')
 for sequence in range(info.state.first_seq,info.state.last_seq+1):
  message=await bus.js.get_msg('ARTICLE_SEMANTIC',seq=sequence);payload=json.loads(message.data)
  wire[payload['message_id']]=payload
 contract=Contract(settings.contracts_dir/'article/semantic/v1.schema.json')
 with sessions() as session:
  rows=list(session.scalars(select(SemanticResult)))
  for row in rows:
   run=session.get(SemanticRun,row.id);stored=row.payload;di=session.get(SemanticInput,run.input_id).payload
   snapshot=run.snapshot;body=snapshot['document']['content']['body'];observed=snapshot['observed'];chunks=observed['chunks']
   assert ''.join(c['text'] for c in chunks)==body
   assert all(a['end_char']==b['start_char'] for a,b in zip(chunks,chunks[1:]))
   assert all(c['token_count']<=run.configuration['max_chunk_tokens'] for c in chunks)
   assert stored['facts']==di['facts']
   for claim in stored['claims']:
    span=claim['evidence'];assert body[span['start_char']:span['end_char']]==span['text']
   assert all(a['basis'] and a['evidence'] for a in stored['affected_assets'])
   replay=build_result(di,snapshot,run.configuration,observed);replay['generated_at']=stored['generated_at']
   assert replay==stored
   assert wire[stored['message_id']]==stored
   contract.validate(stored)
   assert stored['routing']['production_switch'] is False
   if row.ruleset_version==configuration['version']:assert observed['embedding_available'] and observed['gliner_available']
   target=report if row.ruleset_version==configuration['version'] else archived
   target.append({'semantic_id':row.id,'title':stored['document']['title'],'result':stored,'frozen_replay_equal':True,
     'nats_exact_payload_equal':True,'full_stored_body_coverage':True,'exact_claim_spans':True,'result_hash':digest(stored)})
 assert len(report)==55 and len({r['result']['document']['document_id'] for r in report})==55
 print(json.dumps({'documents':len(report),'stream_messages':info.state.messages,'archived_results_verified':len(archived),'archived_result_hashes':{r['semantic_id']:r['result_hash'] for r in archived},'results':report},ensure_ascii=False))
 await bus.close();engine.dispose()
asyncio.run(main())

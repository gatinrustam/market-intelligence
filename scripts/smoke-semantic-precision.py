"""Read-only DI-5.1 corpus, provenance, immutable history, wire and replay audit."""
import asyncio,json,statistics
from collections import Counter
from pathlib import Path
from sqlalchemy import select
from app.config import Settings
from app.domain import load_configuration,build_result,digest
from app.storage.database import make_database
from app.storage.models import SemanticResult,SemanticRun,SemanticInput
from app.storage.contract import Contract
from app.publishers.nats import JetStreamBus
async def main():
 settings=Settings();configuration=load_configuration(settings);engine,sessions=make_database(settings.database_url.get_secret_value());bus=JetStreamBus(settings.nats_url.get_secret_value());await bus.connect()
 old=json.loads(Path('/audit/article-semantic-verification.json').read_text());old_hashes={**old['archived_result_hashes'],**{r['semantic_id']:r['result_hash'] for r in old['results']}}
 wire={};info=await bus.js.stream_info('ARTICLE_SEMANTIC')
 for sequence in range(info.state.first_seq,info.state.last_seq+1):
  message=await bus.js.get_msg('ARTICLE_SEMANTIC',seq=sequence);payload=json.loads(message.data);wire[payload['message_id']]=payload
 contract=Contract(settings.contracts_dir/'article/semantic/v1.schema.json');report=[];perf={'en':[],'ru':[]}
 with sessions() as session:
  for key,expected in old_hashes.items():assert digest(session.get(SemanticResult,key).payload)==expected
  query=select(SemanticResult).where(SemanticResult.ruleset_version==configuration['version'])
  # Once captured, keep the research corpus fixed as normal live ingestion grows.
  pinned=Path('/audit/semantic-precision-verification.json')
  if pinned.exists():
   document_ids=[item['document_id'] for item in json.loads(pinned.read_text())['results']]
   query=query.where(SemanticResult.document_id.in_(document_ids))
  rows=list(session.scalars(query))
  assert len(rows)==95
  for row in rows:
   run=session.get(SemanticRun,row.id);stored=row.payload;di=session.get(SemanticInput,run.input_id).payload;snapshot=run.snapshot;body=snapshot['document']['content']['body'];observed=snapshot['observed'];chunks=observed['chunks']
   assert ''.join(ch['text'] for ch in chunks)==body
   assert observed['embedding_available'] and observed['gliner_available']
   assert all(ch['token_count']<=run.configuration['max_chunk_tokens'] for ch in chunks)
   assert stored['facts']==di['facts'] and stored['reranking']['status']=='complete'
   for claim in stored['claims']:
    span=claim['evidence'];assert body[span['start_char']:span['end_char']]==span['text']
   for asset in stored['affected_assets']:
    assert asset['basis'] and asset['evidence']
    for span in asset['evidence']:assert body[span['start_char']:span['end_char']]==span['text']
   baseline=snapshot['baseline'];assert session.get(SemanticResult,baseline['semantic_id']).payload==baseline
   assert stored['comparison']['baseline_hash']==digest(baseline)
   replay=build_result(di,snapshot,run.configuration,observed);replay['generated_at']=stored['generated_at'];assert replay==stored, row.id
   assert wire[stored['message_id']]==stored
   assert wire[baseline['message_id']]==baseline
   contract.validate(stored);assert stored['routing']['production_switch'] is False
   language=stored['document']['language'];perf[language].append({**stored['performance'],'reranking_seconds':stored['reranking']['latency_seconds']})
   report.append({'semantic_id':row.id,'document_id':row.document_id,'source_id':stored['document']['source_id'],'language':language,'title':stored['document']['title'],'baseline_id':baseline['semantic_id'],'result_hash':digest(stored),'exact_wire_and_frozen_replay':True,'exact_source_evidence':True})
 performance={}
 for lang,values in perf.items():
  elapsed=[v['latency_seconds'] for v in values];total=sum(elapsed);chunks=sum(v['chunks'] for v in values)
  performance[lang]={'documents':len(values),'mean_latency_seconds':statistics.mean(elapsed),'median_latency_seconds':statistics.median(elapsed),'max_latency_seconds':max(elapsed),'total_inference_seconds':total,'chunks':chunks,'aggregate_chunks_per_second':chunks/total,'peak_rss_bytes':max(v['peak_rss_bytes'] for v in values),'mean_reranking_seconds':statistics.mean(v['reranking_seconds'] for v in values)}
 sources=Counter(r['source_id'] for r in report);assert sources['cbr_events_ru']+sources['cbr_press_ru']==20 and sources['moex_news_ru']==20
 print(json.dumps({'version':configuration['version'],'documents':len(report),'source_counts':dict(sources),'old_result_hashes_unchanged':len(old_hashes),'stream_messages':info.state.messages,'model_revisions':configuration['models'],'performance':performance,'results':report},ensure_ascii=False,indent=2))
 await bus.close();engine.dispose()
asyncio.run(main())

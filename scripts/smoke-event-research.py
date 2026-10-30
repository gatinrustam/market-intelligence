"""Read-only proof of persisted research results, reproducibility and exact NATS publication."""
import asyncio,json
from datetime import datetime,timezone
import httpx,nats
from app.config import Settings
from app.domain import build_result,comparison,digest
from app.storage.contract import Contract
async def main():
 s=Settings();contract=Contract(s.contracts_dir/'event/research/v2.schema.json')
 async with httpx.AsyncClient(base_url='http://localhost:8011',timeout=30) as c:
  async def get(path):
   r=await c.get(path);r.raise_for_status();return r.json()
  listing=await get('/research?limit=100');assert listing['total']==55
  nc=await nats.connect(s.nats_url.get_secret_value());js=nc.jetstream();stream=await js.stream_info('EVENT_RESEARCH_V2');published={}
  for seq in range(stream.state.first_seq,stream.state.last_seq+1):
   m=await js.get_msg('EVENT_RESEARCH_V2',seq=seq);p=json.loads(m.data);published[p['research_id']]=p
  rows=[];fact_refs=actor_refs=measurement_refs=0
  def no_body(v):
   if isinstance(v,dict):return 'body' not in v and all(no_body(x) for x in v.values())
   if isinstance(v,list):return all(no_body(x) for x in v)
   return True
  for row in listing['items']:
   key=row['result']['research_id'];saved=await get('/research/'+key);p=saved['result'];snapshot=saved['snapshot'];contract.validate(p)
   assert p==published[key]
   expected=build_result(snapshot['intelligence'],snapshot,saved['configuration'],clock=lambda:datetime.fromisoformat(p['generated_at'].replace('Z','+00:00')))
   assert p==expected;assert saved['comparison']==comparison(p,snapshot);assert no_body(saved)
   di=snapshot['intelligence'];facts={f['fact_id']:f for f in di['facts']};entities={e['mention_id']:e for e in di['entities']}
   for candidate in p['candidates']:
    for ref in candidate['fact_references']:
     fact=facts[ref['fact_id']]
     assert all(ref[k]==fact[k] for k in ('fact_type','relation_id','evidence','extraction'));fact_refs+=1
    for actor in candidate['actors']:
     entity=entities[actor['mention_id']];assert actor['entity_id']==entity['entity_id'];assert (actor['resolution']=='canonical')==entity['registry'];actor_refs+=1
    for attached in candidate['measurements']:
     assert all(attached['measurement'] in facts[fid]['values'] for fid in attached['fact_ids']);measurement_refs+=1
    if candidate['event_time'] is not None:
     assert candidate['event_time'] in [d['date']['normalized'] for d in candidate['dates']]
   rows.append({'title':snapshot['metadata']['title'],'source':snapshot['metadata']['source']['id'],'published_at':snapshot['metadata']['published_at'],'result_hash':digest(p),'snapshot_hash':digest(snapshot),'comparison_hash':digest(saved['comparison']),'result':p,'comparison':saved['comparison']})
  await nc.close()
  print(json.dumps({'verified_at':datetime.now(timezone.utc).isoformat(),'stats':await get('/stats'),'nats_exact_match':len(rows),'reproduced_from_frozen_input':len(rows),'snapshots_without_full_body':len(rows),'fact_references_verified':fact_refs,'actor_references_verified':actor_refs,'measurement_references_verified':measurement_refs,'documents':rows},ensure_ascii=False,indent=2))
asyncio.run(main())

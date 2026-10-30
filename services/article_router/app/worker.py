import asyncio,json,hashlib
import httpx
from app.domain import digest
from app.storage.contract import Contract
class MetadataClient:
    def __init__(self,settings):
        self.settings=settings;self.client=httpx.AsyncClient(timeout=8,follow_redirects=False)
        self.document_contract=Contract(settings.contracts_dir/'document/enriched/v1.schema.json')
        self.event_contract=Contract(settings.contracts_dir/'event/canonical/v1.schema.json')
        self.ei_contract=Contract(settings.contracts_dir/'event/intelligence/v1.schema.json')
    async def get(self,url,**params):
        r=await self.client.get(url,params=params);r.raise_for_status();return r.json()
    async def snapshot(self,di):
        frozen=await self.get(self.settings.intelligence_url+'/intelligence/'+di['intelligence_id']+'/input')
        d=json.loads(frozen['exact_payload']);self.document_contract.validate(d)
        ref=di['document']
        if (d['document_id']!=ref['document_id'] or d['message_id']!=ref['input_message_id'] or d['lineage']['source_message_id']!=ref['source_message_id'] or hashlib.sha256(d['content']['body'].encode()).hexdigest()!=ref['body_hash'] or digest(d)!=frozen['payload_hash'] or digest(frozen['configuration'])!=di['extraction']['configuration_hash']):raise ValueError('DI evidence mismatch')
        snapshot={'document':d,'intelligence':di,'events':[],'event_intelligence':[],'metadata_warnings':[],'repeated_source_item':False}
        try:
            offset=0
            while True:
                batch=await self.get(self.settings.events_url+'/events',offset=offset,limit=100)
                rows=batch['items']
                for event in rows:
                    self.event_contract.validate(event)
                    if any(r['document_id']==d['document_id'] and r['input_message_id']==d['message_id'] for r in event['evidence']['documents']):snapshot['events'].append(event)
                offset+=len(rows)
                if not rows or offset>=batch['total']:break
                if offset>=10000:raise ValueError('Metadata catalogue cap')
        except Exception as exc:
            snapshot['events']=[];snapshot['metadata_warnings'].append('canonical_metadata_unavailable:'+type(exc).__name__)
        for event in snapshot['events']:
            try:
                rows=await self.get(self.settings.event_intelligence_url+'/events/'+event['event']['id']+'/intelligence',event_revision=event['event']['revision'])
                valid=[]
                for ei in rows:
                    self.ei_contract.validate(ei)
                    if ei['basis']['canonical_hash']!=digest(event):continue
                    if not any(h['document_id']==d['document_id'] and h['message_id']==d['message_id'] and h['content_hash']==d['integrity']['content_hash'] for h in ei['basis']['evidence_hashes']):continue
                    valid.append(ei)
                if valid:snapshot['event_intelligence'].append(max(valid,key=lambda x:x['generated_at']))
                else:snapshot['metadata_warnings'].append('compatible_event_intelligence_unavailable')
            except Exception as exc:snapshot['metadata_warnings'].append('event_intelligence_unavailable:'+type(exc).__name__)
        return snapshot
    async def close(self):await self.client.aclose()
class Worker:
    def __init__(self,repo,metadata):self.repo,self.metadata=repo,metadata
    async def run_once(self):
        claim=await asyncio.to_thread(self.repo.claim)
        if claim is None:return False
        run,di=claim
        try:
            snapshot=await asyncio.wait_for(self.metadata.snapshot(di),60)
            snapshot['repeated_source_item']=await asyncio.to_thread(self.repo.repeated,di,snapshot['document'])
            await asyncio.to_thread(self.repo.finish,run,snapshot)
        except Exception as exc:await asyncio.to_thread(self.repo.failure,run,type(exc).__name__,isinstance(exc,ValueError))
        return True

import asyncio
import httpx
from app.domain import digest
from app.storage.contract import Contract
class MetadataClient:
    def __init__(self,settings):
        self.settings=settings;self.client=httpx.AsyncClient(timeout=8,follow_redirects=False)
        self.event_contract=Contract(settings.contracts_dir/'event/canonical/v1.schema.json')
    async def get(self,url,**params):
        r=await self.client.get(url,params=params);r.raise_for_status();return r.json()
    async def snapshot(self,di):
        meta=await self.get(self.settings.intelligence_url+'/intelligence/'+di['intelligence_id']+'/metadata')
        if meta['intelligence_id']!=di['intelligence_id'] or meta['intelligence_hash']!=digest(di) or meta['extraction']!=di['extraction'] or any(meta[k]!=v for k,v in di['document'].items()):raise ValueError('DI provenance mismatch')
        if 'body' in meta or 'content' in meta:raise ValueError('Metadata endpoint returned body')
        # Baseline comparison must be complete; unlike optional reviews, v1 API failure retries the run.
        events=[];offset=0
        while True:
            batch=await self.get(self.settings.events_url+'/events',offset=offset,limit=100)
            for e in batch['items']:
                self.event_contract.validate(e)
                if any(r['document_id']==meta['document_id'] and r['input_message_id']==meta['input_message_id'] for r in e['evidence']['documents']):events.append(e)
            offset+=len(batch['items'])
            if not batch['items'] or offset>=batch['total']:break
            if offset>=10000:raise ValueError('v1 catalogue cap exceeded')
        extraction=await self.get(self.settings.events_url+'/documents/'+meta['document_id']+'/extraction')
        if extraction['job']['status']!='completed':raise RuntimeError('v1 extraction not complete')
        basis=[]
        for run in extraction['runs']:
            for candidate in run['result_json']['candidates']:
                if candidate['document_id']!=meta['document_id']:raise ValueError('v1 document mismatch')
                basis.append({'event_type':candidate['event_type'],'classification_basis':candidate['classification_basis'],'rule_ids':candidate['matched_rule_ids']})
        snapshot={'intelligence':di,'metadata':meta,'v1_events':events,'v1_extraction':extraction,'v1_basis':basis,'human_reviews':[],'warnings':[]}
        try:
            reviews=await self.get(self.settings.article_router_url+'/documents/'+meta['document_id']+'/reviews')
            snapshot['human_reviews']=[r for r in reviews if r['intelligence_id']==di['intelligence_id']]
        except Exception as exc:snapshot['warnings'].append('human_review_unavailable:'+type(exc).__name__)
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
            await asyncio.to_thread(self.repo.finish,run,snapshot)
        except Exception as exc:await asyncio.to_thread(self.repo.failure,run,type(exc).__name__,isinstance(exc,ValueError))
        return True

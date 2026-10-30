import asyncio,hashlib,time
import httpx
from app.domain import build_result
class InputClient:
    def __init__(self,settings):self.settings=settings;self.client=httpx.AsyncClient(timeout=30,follow_redirects=False)
    async def get(self,url):
        r=await self.client.get(url);r.raise_for_status();return r.json()
    async def snapshot(self,di):
        document=await self.get(self.settings.enrichment_url+'/documents/'+di['document']['document_id'])
        if document['message_id']!=di['document']['input_message_id'] or document['lineage']['source_message_id']!=di['document']['source_message_id'] or hashlib.sha256(document['content']['body'].encode()).hexdigest()!=di['document']['body_hash']:
            raise ValueError('Enriched/DI provenance mismatch')
        old=None;warnings=[]
        try:
            offset=0
            while old is None:
                items=await self.get(self.settings.router_url+f'/articles?limit=100&offset={offset}')
                for item in items['items']:
                    if item['document_id']==di['document']['document_id']:
                        detail=await self.get(self.settings.router_url+'/articles/'+item['id'])
                        if detail['machine']['document']['intelligence_id']==di['intelligence_id']:
                            old={'routing_id':item['id'],'route':detail['machine']['classification']['route']};break
                offset+=len(items['items'])
                if not items['items'] or offset>=items['total']:break
            if old is None:warnings.append('No matching immutable DI-2 route available')
        except Exception as exc:warnings.append('old_route_unavailable:'+type(exc).__name__)
        return {'document':document,'intelligence':di,'old_route':old,'warnings':warnings}
    async def close(self):await self.client.aclose()
class Worker:
    def __init__(self,repo,client,models):self.repo,self.client,self.models=repo,client,models
    async def run_once(self):
        claim=await asyncio.to_thread(self.repo.claim)
        if claim is None:return False
        run,di=claim
        try:
            snapshot=await self.client.snapshot(di)
            observed=await asyncio.to_thread(self.models.analyze,di,snapshot['document']['content']['body'])
            snapshot['observed']=observed
            baseline=await asyncio.to_thread(self.repo.ensure_baseline,di,snapshot,observed)
            if baseline:snapshot['baseline']=baseline
            rerank_start=time.monotonic()
            payload=build_result(di,snapshot,run.configuration,observed)
            if self.repo.configuration.get('reranking'):
                observed['reranking_seconds']=time.monotonic()-rerank_start
                payload['reranking']['latency_seconds']=observed['reranking_seconds']
            await asyncio.to_thread(self.repo.finish,run,snapshot,payload)
        except Exception as exc:await asyncio.to_thread(self.repo.failure,run,type(exc).__name__,isinstance(exc,ValueError))
        return True

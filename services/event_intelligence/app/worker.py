import asyncio
import httpx
from app.storage.contract import Contract

class EventsClient:
    def __init__(self,settings):
        self.client=httpx.AsyncClient(base_url=settings.events_url,timeout=10)
        self.event_contract=Contract(settings.contracts_dir/'event/canonical/v1.schema.json')
        self.document_contract=Contract(settings.contracts_dir/'document/enriched/v1.schema.json')
    async def documents(self,event):
        docs=[]
        for ref in event['evidence']['documents']:
            response=await self.client.get('/documents/'+ref['document_id']+'/input');response.raise_for_status();doc=response.json()['document']
            self.document_contract.validate(doc)
            if doc['document_id']!=ref['document_id'] or doc['message_id']!=ref['input_message_id'] or doc['lineage']['source_message_id']!=ref['source_message_id'] or doc['source']['id']!=ref['source_id'] or doc['enrichment']['status']!=ref['document_status']:raise ValueError('immutable evidence mismatch')
            docs.append(doc)
        if len(docs)!=event['evidence']['document_count'] or len({d['document_id'] for d in docs})!=len(docs) or len({d['source']['id'] for d in docs})!=event['evidence']['independent_source_count']:raise ValueError('evidence count mismatch')
        return docs
    async def snapshot(self,event):
        docs=await self.documents(event);previous=None
        if event['event']['revision']>1:
            r=await self.client.get('/events/'+event['event']['id']+'/revisions',params={'offset':event['event']['revision']-2,'limit':1});r.raise_for_status();rows=r.json()
            if rows:
                old=rows[0];self.event_contract.validate(old)
                if old['event']['id']!=event['event']['id'] or old['event']['revision']!=event['event']['revision']-1:raise ValueError('previous revision mismatch')
                previous={'event':old,'documents':await self.documents(old)}
        return {'event':event,'documents':docs,'previous':previous}
    async def close(self):await self.client.aclose()
class Worker:
    def __init__(self,repo,events):self.repo,self.events=repo,events
    async def run_once(self):
        claim=await asyncio.to_thread(self.repo.claim)
        if claim is None:return False
        run,event=claim
        try:
            snapshot=await asyncio.wait_for(self.events.snapshot(event),timeout=60)
            await asyncio.to_thread(self.repo.finish,run,snapshot)
        except Exception as exc:await asyncio.to_thread(self.repo.failure,run,type(exc).__name__,isinstance(exc,ValueError))
        return True

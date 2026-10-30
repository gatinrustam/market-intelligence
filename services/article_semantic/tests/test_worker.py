import json
import pytest
import httpx
from app.worker import InputClient,Worker
from conftest import observation

@pytest.mark.asyncio
async def test_document_provenance_mismatch_rejected(settings,examples):
    client=InputClient(settings);doc=examples['Fed']['document'];doc['content']['body']='tampered'
    client.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=doc)))
    with pytest.raises(ValueError):await client.snapshot(examples['Fed']['intelligence'])
    await client.close()

@pytest.mark.asyncio
async def test_gliner_failure_does_not_block_semantic_result(repo,examples,configuration):
    snapshot=examples['Fed'];repo.accept(json.dumps(snapshot['intelligence']).encode(),1,'document.intelligence.v1',{})
    class Client:
        async def snapshot(self,di):return snapshot
    class Models:
        def analyze(self,di,body):return observation(snapshot,gliner=False)
    assert await Worker(repo,Client(),Models()).run_once()
    result=repo.catalogue(0,100)['items'][0]
    assert result['status']=='partial' and result['semantic_concepts'] and result['facts']

@pytest.mark.asyncio
async def test_route_lookup_paginates_without_changing_old_route(settings,examples):
    client=InputClient(settings);snap=examples['Fed'];did=snap['intelligence']['document']['document_id'];requests=[]
    async def get(url):
        requests.append(url)
        if '/documents/' in url:return snap['document']
        if 'offset=0' in url:return {'total':2,'items':[{'id':'other','document_id':'other'}]}
        if 'offset=1' in url:return {'total':2,'items':[{'id':'route','document_id':did}]}
        return {'machine':{'document':{'intelligence_id':snap['intelligence']['intelligence_id']},'classification':{'route':'important'}}}
    client.get=get
    result=await client.snapshot(snap['intelligence'])
    assert result['old_route']=={'routing_id':'route','route':'important'}
    assert any('offset=1' in url for url in requests)
    await client.close()

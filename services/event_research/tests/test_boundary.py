import json,copy
import httpx,pytest
from app.worker import MetadataClient
from app.domain import digest
from app.main import create_app
from tests.test_storage import complete
@pytest.mark.asyncio
async def test_metadata_only_boundary_and_exact_provenance(settings,examples):
    s=examples['Fed'];requests=[]
    def handle(request):
        requests.append(str(request.url));path=request.url.path
        if path.endswith('/metadata'):return httpx.Response(200,json=s['metadata'])
        if path=='/events':return httpx.Response(200,json={'items':s['v1_events'],'total':len(s['v1_events'])})
        if path.endswith('/extraction'):return httpx.Response(200,json=s['v1_extraction'])
        if path.endswith('/reviews'):return httpx.Response(503)
        raise AssertionError('Unexpected full-document read: '+path)
    client=MetadataClient(settings);await client.client.aclose();client.client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    snapshot=await client.snapshot(s['intelligence']);assert snapshot['v1_basis']==s['v1_basis'];assert snapshot['warnings'];assert not any('/input' in path for path in requests)
    assert 'body' not in snapshot['metadata']
    s['metadata']['body_hash']='0'*64
    with pytest.raises(ValueError):await client.snapshot(s['intelligence'])
    await client.close()
@pytest.mark.asyncio
async def test_http_read_only_results(repo,examples,sessions,settings):
    key=complete(repo,examples['Fed']);app=create_app(settings);app.state.repo=repo
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/research/'+key)).json()==repo.detail(key)
        rows=(await c.get('/documents/'+examples['Fed']['metadata']['document_id']+'/comparison')).json();assert rows[0]['result']==repo.view(key)
        assert (await c.post('/research/'+key,json={})).status_code==405
        assert (await c.get('/research')).json()['total']==1

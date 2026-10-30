import copy,json
from uuid import uuid4
import httpx,pytest
from fastapi.testclient import TestClient
from app.worker import MetadataClient,Worker
from app.domain import digest
from app.main import create_app
from app.storage.models import RoutingRun
from app.storage.database import make_database
from tests.test_router import complete

@pytest.mark.asyncio
async def test_required_evidence_checked_optional_metadata_outage(settings,examples):
    snap=examples['Fed'];di=snap['intelligence'];configuration={'fixture':True};di['extraction']['configuration_hash']=digest(configuration)
    def handler(req):
        if req.url.host=='document-intelligence':return httpx.Response(200,json={'exact_payload':json.dumps(snap['document']),'payload_hash':digest(snap['document']),'configuration':configuration})
        return httpx.Response(503)
    client=MetadataClient(settings);await client.client.aclose();client.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result=await client.snapshot(di);assert result['document']==snap['document'];assert result['events']==[];assert result['metadata_warnings']
    di['document']['body_hash']='0'*64
    with pytest.raises(ValueError):await client.snapshot(di)
    await client.close()
@pytest.mark.asyncio
async def test_required_input_outage_retries_without_result(repo,examples,sessions):
    repo.accept(json.dumps(examples['Fed']['intelligence']).encode(),1,'document.intelligence.v1',{})
    class Down:
        async def snapshot(self,di):raise ConnectionError()
    await Worker(repo,Down()).run_once()
    assert repo.stats()['runs']=={'pending':1};assert repo.stats()['outbox']=={}

def test_review_endpoint_auth_and_read_only_machine(settings,repo,examples):
    key=complete(repo,examples['Fed']);app=create_app(settings)
    with TestClient(app) as client:
        before=client.get('/routing/'+key).json()
        payload={'request_id':str(uuid4()),'expected_revision':0,'status':'reviewed','reviewer':'research@test','send_to_llm':True}
        assert client.post('/reviews/'+key+'/labels',json=payload).status_code==401
        assert client.post('/reviews/'+key+'/labels',json=payload,headers={'Authorization':'Bearer test-secret'}).status_code==200
        assert client.get('/routing/'+key).json()==before
        assert client.put('/routing/'+key,json={}).status_code==405
        assert client.get('/articles').json()['total']==1
        assert len(client.get('/articles/'+key).json()['labels'])==1
        reviews=client.get('/documents/'+before['document']['document_id']+'/reviews').json()
        assert len(reviews)==1 and len(reviews[0]['labels'])==1
        assert reviews[0]['reviewed_v1_types']==['central_bank.policy_statement']
        assert 'snapshot' not in reviews[0] and 'body' not in reviews[0]
        assert client.post('/reviews/'+key+'/labels',json={**payload,'evil':True},headers={'Authorization':'Bearer test-secret'}).status_code==422

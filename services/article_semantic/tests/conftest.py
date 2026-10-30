import json,os
from pathlib import Path
import pytest
from app.config import Settings
from app.domain import load_configuration,chunk_document
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository
@pytest.fixture
def settings():return Settings(workers_enabled=False,review_token='test-semantic-token')
@pytest.fixture
def configuration(settings):return load_configuration(settings,"policy.di5.json")
@pytest.fixture
def examples():return json.loads(Path('tests/examples.json').read_text())
@pytest.fixture
def sessions():
    url=os.environ['TEST_DATABASE_URL'];assert '/article_semantic_test?' in url
    engine,sessions=make_database(url);Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    yield sessions
    Base.metadata.drop_all(engine);engine.dispose()
@pytest.fixture
def repo(sessions,settings,configuration):
    repo=Repository(sessions,settings,configuration);repo.register();return repo

def observation(snapshot,concept='interest_rates',similarity=.8,bge=True,gliner=True):
    di=snapshot['intelligence'];body=snapshot['document']['content']['body']
    chunks=chunk_document(di['document']['document_id'],body,di['sentences'],192,lambda s:len(s))
    return {'chunks':chunks,'matches':[{'concept_id':concept,'similarity':similarity,'chunk_id':c['chunk_id']} for c in chunks] if bge else [],
        'entities':[],'embeddings':[],'warnings':[],'embedding_available':bge,'gliner_available':gliner,'runtime_versions':{'test':'fixture'},
        'performance':{'latency_seconds':1.,'embedding_seconds':.5,'gliner_seconds':.5,'chunks_per_second':len(chunks),'documents_per_second':1.,'rss_bytes':1,'peak_rss_bytes':1,'chunks':len(chunks)}}

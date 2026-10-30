import copy,json,os,hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from app.config import Settings
from app.domain import load_configuration
from app.pipeline import Pipeline
from app.storage.models import Base
from app.storage.database import make_database
from app.storage.repository import Repository
@pytest.fixture(scope='session')
def settings():return Settings(workers_enabled=False)
@pytest.fixture(scope='session')
def configuration(settings):return load_configuration(settings)
@pytest.fixture(scope='session')
def pipeline(configuration):return Pipeline(configuration)
@pytest.fixture
def document():
    def make(body):
        doc=json.loads(Path('tests/document.json').read_text());doc['document_id']=str(uuid4());doc['message_id']=str(uuid4());doc['content']['body']=body;doc['content']['body_length']=len(body)
        doc['integrity']['content_hash']=hashlib.sha256(body.encode()).hexdigest();return doc
    return make
@pytest.fixture
def sessions():
    url=os.environ['TEST_DATABASE_URL'];assert '/document_intelligence_test?' in url
    engine,sessions=make_database(url);Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    yield sessions
    Base.metadata.drop_all(engine);engine.dispose()
@pytest.fixture
def repo(sessions,settings,configuration):
    repo=Repository(sessions,settings,configuration);repo.register();return repo

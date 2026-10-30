import copy
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from app.config import Settings
from app.taxonomy.configuration import load_bundle
from app.storage.contract import Contract,CanonicalContract
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository
from app.correlation.core import EventCore
from app.extraction.rules import RuleBasedEventExtractor
from app.workers.process import EventWorker

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture
def settings():
    return Settings(input_schema_path=ROOT/'contracts/document/enriched/v1.schema.json',
        output_schema_path=ROOT/'contracts/event/canonical/v1.schema.json',config_dir=ROOT/'config/events',workers_enabled=False)


@pytest.fixture
def bundle(settings):
    return load_bundle(settings.config_dir)


@pytest.fixture
def extractor(bundle):
    return RuleBasedEventExtractor(bundle)


@pytest.fixture
def input_contract(settings):
    return Contract(settings.input_schema_path)


@pytest.fixture
def output_contract(settings):
    return CanonicalContract(settings.output_schema_path)


@pytest.fixture
def document():
    p=json.loads((Path(__file__).parent/'fixtures/fed.json').read_text())
    p['message_id']=str(uuid4());p['document_id']=str(uuid4());p['lineage']['source_message_id']=str(uuid4())
    return p


@pytest.fixture
def database(monkeypatch):
    url=os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL required')
    assert make_url(url).database=='events_test'
    monkeypatch.setenv('EVENTS_DATABASE_URL',url)
    command.upgrade(Config('alembic.ini'),'head')
    engine,sessions=make_database(url)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
    yield engine,sessions
    engine.dispose()


@pytest.fixture
def repository(database,input_contract,settings):
    return Repository(database[1],input_contract,settings)


@pytest.fixture
def core(repository,output_contract,bundle):
    return EventCore(repository,output_contract,bundle)


@pytest.fixture
def worker(repository,extractor,core,bundle,settings):
    return EventWorker(repository,extractor,core,bundle,settings)

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from app.config import Settings, SourcePolicy, Policies
from app.normalization.contract import Contract
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def settings(monkeypatch):
    return Settings(input_schema_path=ROOT/'contracts/news/raw/v1.schema.json',
                    output_schema_path=ROOT/'contracts/document/enriched/v1.schema.json',
                    policy_path=ROOT/'config/enrichment/policies.yaml', workers_enabled=False)


@pytest.fixture
def input_contract(settings):
    return Contract(settings.input_schema_path)


@pytest.fixture
def output_contract(settings):
    return Contract(settings.output_schema_path)


@pytest.fixture
def policy():
    return SourcePolicy(allowed_hosts=['example.org'])


@pytest.fixture
def policies(policy):
    return Policies(sources={'test_authority': policy})


@pytest.fixture
def event():
    return {'schema_version': '1.0', 'message_id': str(uuid4()),
            'source': {'id': 'test_authority', 'type': 'rss', 'external_id': 'item-1'},
            'timestamps': {'published_at': '2026-01-01T12:00:00+00:00', 'received_at': '2026-09-19T12:00:00+00:00'},
            'content': {'title': 'Original source title', 'body': '', 'language': 'en'},
            'classification': {'categories': ['macro', 'monetary_policy']},
            'url': 'https://example.org/article', 'integrity': {'content_hash': 'a'*64},
            'raw': {'payload_id': str(uuid4())}}


@pytest.fixture
def html_bytes():
    return (Path(__file__).parent/'fixtures/article.html').read_bytes()


@pytest.fixture
def pdf_bytes():
    return (Path(__file__).parent/'fixtures/statement.pdf').read_bytes()


@pytest.fixture
def extraction_context(settings):
    return {'url': 'https://example.org/article', 'content_type': 'text/html',
            'max_pdf_pages': settings.max_pdf_pages, 'minimum_extracted_characters': 100,
            'max_output_characters': settings.max_output_characters}


@pytest.fixture
def database(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL required for real MariaDB integration tests')
    if make_url(url).database != 'enrichment_test':
        raise RuntimeError('Only isolated enrichment_test DB is permitted')
    monkeypatch.setenv('ENRICHMENT_DATABASE_URL', url)
    command.upgrade(Config('alembic.ini'), 'head')
    engine, sessions = make_database(url)
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
    yield engine, sessions
    engine.dispose()


@pytest.fixture
def repository(database, input_contract, output_contract, settings):
    return Repository(database[1], input_contract, output_contract, settings)

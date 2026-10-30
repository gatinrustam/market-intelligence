import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from app.adapters.base import FetchResult
from app.config import SourceConfig
from app.normalization.contract import Contract
from app.storage.database import make_database
from app.storage.models import Base


@pytest.fixture
def source():
    return SourceConfig.model_validate({'id': 'test_authority', 'name': 'Test Authority',
        'connector': {'type': 'rss', 'url': 'https://example.org/rss'}, 'language': 'en',
        'classification': {'categories': ['macro']}})


@pytest.fixture
def feed():
    return FetchResult((Path(__file__).parent / 'fixtures/feed.xml').read_bytes(),
                       datetime(2026, 9, 19, tzinfo=timezone.utc), 'application/rss+xml')


@pytest.fixture
def contract():
    return Contract(Path(__file__).resolve().parents[3] / 'contracts/news/raw/v1.schema.json')


@pytest.fixture
def database(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL required for real MariaDB integration tests')
    if '/ingestion_test' not in url:
        raise RuntimeError('Tests require dedicated ingestion_test database')
    monkeypatch.setenv('INGESTION_DATABASE_URL', url)
    command.upgrade(Config('alembic.ini'), 'head')
    engine, sessions = make_database(url)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
    yield engine, sessions
    engine.dispose()

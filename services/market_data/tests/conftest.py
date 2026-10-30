import os
from pathlib import Path
import pytest
from app.contract import Contract
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository

@pytest.fixture
def contract(): return Contract(Path('/workspace/contracts/market/snapshot/v1.schema.json'))
@pytest.fixture
def sessions():
    url=os.environ['TEST_DATABASE_URL']
    assert '/market_data_test?' in url
    engine,sessions=make_database(url)
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield sessions
    Base.metadata.drop_all(engine); engine.dispose()
@pytest.fixture
def repo(sessions,contract): return Repository(sessions,contract)

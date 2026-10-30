import copy,json,os
from pathlib import Path
import pytest
from app.config import Settings
from app.storage.contract import CanonicalContract,ContextContract
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository

@pytest.fixture
def settings():return Settings()
@pytest.fixture
def event():return json.loads(Path('tests/canonical.json').read_text())
@pytest.fixture
def contract(settings):return ContextContract(settings.output_schema_path)
@pytest.fixture
def sessions():
    url=os.environ['TEST_DATABASE_URL'];assert '/market_context_test?' in url
    engine,sessions=make_database(url);Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    yield sessions
    Base.metadata.drop_all(engine);engine.dispose()
@pytest.fixture
def repo(sessions,settings,contract):return Repository(sessions,CanonicalContract(settings.input_schema_path),contract,settings)

import copy,json,os
from pathlib import Path
from uuid import uuid4
import pytest
from app.config import Settings
from app.domain import digest
from app.storage.database import make_database
from app.storage.models import Base
from app.storage.repository import Repository

@pytest.fixture
def settings(): return Settings(fixtures_enabled=True)
@pytest.fixture
def package():
    p=json.loads(Path('tests/decision.json').read_text())
    points=copy.deepcopy(p['points'])
    points[-1]['price']='100'
    return {'event_identity':p['event'],'event':p['known_information']['canonical_event'],
            'decision':{k:p[k] for k in ('decision_at','decision_basis','historical_simulation')},
            'market_context':{'symbol':'BTCUSDT','lookup_policy':p['lookup_policy'],'freshness_policy':p['freshness_policy'],'points':points}}
@pytest.fixture
def analysis(package):
    key=str(uuid4())
    return {'schema_version':'1.0','message_id':key,'analysis_id':key,'event':package['event_identity'],
        'decision':package['decision'],'asset':{'symbol':'BTCUSDT','relevance':'medium'},
        'interpretation':{'summary':'LABELLED FIXTURE, not a model output','market_mechanism':'Deterministic evaluation test'},
        'forecast':[{'horizon_seconds':n,'direction':'up','impact':'small','confidence':'medium'} for n in (60,300,900,3600)],
        'uncertainties':['Fixture only'],'unavailable_data':{k:'unavailable' for k in ('market_surprise','consensus_expectation','probability_of_fed_action')},
        'confidence_basis':'model_reported_not_calibrated','audit':{'provider':'openai','model':'fixture/test','prompt_version':'fixture_v1','input_hash':digest(package),'reasoning_effort':'medium'}}
@pytest.fixture
def sessions():
    url=os.environ['TEST_DATABASE_URL'];assert '/evaluation_test?' in url
    engine,sessions=make_database(url);Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    yield sessions
    Base.metadata.drop_all(engine);engine.dispose()
@pytest.fixture
def repo(sessions,settings): return Repository(sessions,settings)

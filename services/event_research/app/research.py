"""Replay this service's immutable inputs under the currently configured ruleset."""
import json
from sqlalchemy import select
from app.config import Settings
from app.domain import load_configuration
from app.storage.database import make_database
from app.storage.repository import Repository
from app.storage.models import ResearchInput

def main():
    settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value())
    repo=Repository(sessions,settings,load_configuration(settings));repo.register();counts={}
    with sessions() as s:inputs=list(s.scalars(select(ResearchInput)))
    for row in inputs:
        result=repo.accept(row.exact_payload.encode(),row.provenance['stream_sequence'],row.provenance['subject'],row.provenance)
        counts[result]=counts.get(result,0)+1
    engine.dispose();print(json.dumps(counts))
if __name__=='__main__':main()

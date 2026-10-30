"""Real isolated NATS outage/restart; fake provider only, never production streams."""
import asyncio,json,os,sys
from pathlib import Path
from sqlalchemy import select,func
from app.config import Settings
from app.storage.database import make_database
from app.storage.models import Base,OutboxEvent,AnalysisResult,utcnow
from app.storage.repository import Repository
from app.storage.contract import Contract
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from tests.test_analysis import worker,enqueue

async def main():
    url=os.environ['TEST_DATABASE_URL'];nats_url=os.environ['TEST_NATS_URL']
    assert '/llm_analysis_test?' in url and 'nats-test' in nats_url
    engine,sessions=make_database(url);settings=Settings();repo=Repository(sessions,settings)
    bus=JetStreamBus(nats_url);contract=Contract(settings.contracts_dir/'analysis/v1.schema.json');publisher=OutboxPublisher(sessions,bus,contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            package=json.loads(Path('tests/decision.json').read_text())
            output={'relevance':'low','interpretation':{'summary':'Synthetic provider test only.','market_mechanism':'Unavailable.'},'forecast':[{'horizon_seconds':h,'direction':'unclear','impact':'negligible','confidence':'low'} for h in (60,300,900,3600)],'uncertainties':['Test fixture.'],'unavailable_data':{k:'unavailable' for k in ('market_surprise','consensus_expectation','probability_of_fed_action')}}
            key=enqueue(repo,package);w,_,_=worker(repo,package,settings,output);await w.run_once()
            assert repo.view(key)['analysis_status']=='completed'
            assert await publisher.run_once()
            with sessions() as s:
                assert s.scalar(select(OutboxEvent)).status=='pending'
                assert s.scalar(select(func.count()).select_from(AnalysisResult))==1
            print(json.dumps({'broker':'offline','analysis_saved':1,'outbox_pending':1,'fake_provider':True}))
        else:
            await bus.connect();await bus.js.purge_stream('ANALYSES')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)):row.next_attempt_at=utcnow()
            assert await publisher.run_once();assert not await publisher.run_once()
            raw=await bus.js.get_msg('ANALYSES',seq=(await bus.js.stream_info('ANALYSES')).state.first_seq);value=json.loads(raw.data);contract.validate(value)
            with sessions() as s:assert s.get(AnalysisResult,value['analysis_id']).payload==value
            await bus.publish(value['message_id'],value,'analysis.completed.v1')
            assert (await bus.js.stream_info('ANALYSES')).state.messages==1
            print(json.dumps({'broker':'recovered','fresh_process':True,'published':1,'duplicate_suppressed':True}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())

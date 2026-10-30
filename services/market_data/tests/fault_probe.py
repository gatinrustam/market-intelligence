"""Isolated broker/process outage probe. Never operates on production DB or NATS."""
import asyncio,json,os,sys
from datetime import timedelta
from sqlalchemy import select,func
from app.config import Settings
from app.contract import Contract
from app.domain import now
from app.storage.database import make_database
from app.storage.models import Base,Snapshot,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from tests.test_market import state

async def main():
    url=os.environ['TEST_DATABASE_URL'];nats_url=os.environ['TEST_NATS_URL']
    assert '/market_data_test?' in url and 'nats-test' in nats_url
    engine,sessions=make_database(url);contract=Contract(Settings().contract_path)
    bus=JetStreamBus(nats_url);repo=Repository(sessions,contract);worker=OutboxPublisher(sessions,bus,contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            t=now();repo.save_snapshot(state(t).snapshot(t))
            publishing=asyncio.create_task(worker.run_once())
            # Sampling and durable writes continue while a real NATS connection fails.
            for _ in range(3):
                await asyncio.sleep(1.05);t=now();repo.save_snapshot(state(t).snapshot(t))
            await publishing
            with sessions() as s:
                assert s.scalar(select(func.count()).select_from(Snapshot))==4
                assert s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status=='pending'))==4
            print(json.dumps({'broker':'offline','snapshots_saved':4,'outbox_pending':4}))
        else:
            await bus.connect();await bus.js.purge_stream('MARKET_SNAPSHOTS')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)): row.next_attempt_at=utcnow()
            while await worker.run_once():pass
            with sessions() as s:
                rows=s.scalars(select(OutboxEvent)).all()
                assert len(rows)==4 and all(r.status=='published' for r in rows)
                payloads={r.message_id:r.payload for r in rows}
            info=await bus.js.stream_info('MARKET_SNAPSHOTS');assert info.state.messages==4
            for seq in range(info.state.first_seq,info.state.last_seq+1):
                raw=await bus.js.get_msg('MARKET_SNAPSHOTS',seq=seq);payload=json.loads(raw.data)
                assert payload==payloads[payload['message_id']];contract.validate(payload)
            print(json.dumps({'broker':'recovered','fresh_worker_process':True,'published_exact_payloads':4,'outbox_pending':0}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())

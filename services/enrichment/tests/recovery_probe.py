"""Real broker outage probe. Only enrichment_test / nats-test may be used."""
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import Settings, Policies, SourcePolicy
from app.extraction.runner import ExtractionRunner
from app.normalization.contract import Contract
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.database import make_database
from app.storage.models import EnrichedDocument, OutboxEvent, utcnow
from app.storage.repository import Repository
from app.workers.enrich import EnrichmentWorker


async def main():
    url, nats_url = os.environ['TEST_DATABASE_URL'], os.environ['TEST_NATS_URL']
    assert make_url(url).database == 'enrichment_test' and 'nats-test:' in nats_url
    engine, sessions = make_database(url)
    settings = Settings(workers_enabled=False)
    input_contract, output_contract = Contract(settings.input_schema_path), Contract(settings.output_schema_path)
    repository = Repository(sessions, input_contract, output_contract, settings)
    bus = JetStreamBus(nats_url)
    publisher = OutboxPublisher(sessions, bus, output_contract)
    try:
        if sys.argv[1] == 'offline':
            event = {'schema_version':'1.0','message_id':str(uuid4()),
                'source':{'id':'fault_probe','type':'rss','external_id':None},
                'timestamps':{'published_at':None,'received_at':'2026-09-19T00:00:00Z'},
                'content':{'title':'Real NATS outage probe','body':'Sufficient original source content. '*30,'language':'en'},
                'classification':{'categories':[]},'url':'https://example.org/article',
                'integrity':{'content_hash':'a'*64},'raw':{'payload_id':str(uuid4())}}
            repository.accept(json.dumps(event).encode(), 0)
            policies = Policies(sources={'fault_probe':SourcePolicy(allowed_hosts=['example.org'])})
            worker = EnrichmentWorker(repository,policies,AsyncMock(),ExtractionRunner(settings),settings)
            while await worker.run_once():
                pass
            while await publisher.run_once():
                pass
            with sessions() as session:
                rows = [r for r in session.scalars(select(OutboxEvent)) if r.payload['source']['id']=='fault_probe']
                assert rows and all(r.status=='pending' and r.attempts>=1 for r in rows)
                for r in rows:
                    assert session.get(EnrichedDocument,r.document_id)
                print('PASS: real stopped NATS; committed document and pending output:', [r.message_id for r in rows])
        else:
            with sessions.begin() as session:
                for row in session.scalars(select(OutboxEvent).where(OutboxEvent.status=='pending')):
                    row.next_attempt_at=utcnow()-timedelta(seconds=1)
            while await publisher.run_once():
                pass
            with sessions() as session:
                rows=[r for r in session.scalars(select(OutboxEvent)) if r.payload['source']['id']=='fault_probe']
                assert rows and all(r.status=='published' and r.attempts>=2 for r in rows)
            await bus.connect()
            info=await bus.js.stream_info('DOCUMENT_ENRICHED')
            found={}
            for seq in range(info.state.first_seq,info.state.last_seq+1):
                msg=await bus.js.get_msg('DOCUMENT_ENRICHED',seq=seq)
                payload=json.loads(msg.data)
                output_contract.validate(payload)
                found[payload['message_id']]=payload
            assert all(found[r.message_id]==r.payload for r in rows)
            print('PASS: new publisher process recovered exact same message IDs into real JetStream')
    finally:
        await bus.close()
        engine.dispose()

asyncio.run(main())

"""Read-only deployed smoke: docker compose exec -T enrichment python - < scripts/enrichment-smoke.py"""
import asyncio
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
import urllib.request

from sqlalchemy import select

from app.config import Settings
from app.normalization.contract import Contract
from app.publishers.nats import JetStreamBus
from app.storage.database import make_database
from app.storage.models import EnrichmentInput, EnrichedDocument, FetchSnapshot, OutboxEvent


async def main():
    settings=Settings()
    engine,sessions=make_database(settings.database_url.get_secret_value())
    contract=Contract(settings.output_schema_path)
    bus=JetStreamBus(settings.nats_url.get_secret_value())
    await bus.connect()
    try:
        with sessions() as session:
            pairs=list(session.execute(select(EnrichedDocument,EnrichmentInput).join(EnrichmentInput,
                EnrichedDocument.source_message_id==EnrichmentInput.source_message_id)))
            snapshots=list(session.scalars(select(FetchSnapshot)))
            outbox=list(session.scalars(select(OutboxEvent)))
        assert pairs and len(pairs)==len(outbox)
        output_info=await bus.js.stream_info('DOCUMENT_ENRICHED')
        published={}
        for seq in range(output_info.state.first_seq,output_info.state.last_seq+1):
            raw=await bus.js.get_msg('DOCUMENT_ENRICHED',seq=seq)
            event=json.loads(raw.data)
            contract.validate(event)
            published[event['message_id']]=event
        records=[]
        for doc,inp in pairs:
            p=doc.payload
            contract.validate(p)
            original=await bus.js.get_msg('NEWS_RAW',seq=inp.stream_sequence)
            assert original.data==inp.exact_payload
            assert published[p['message_id']]==p
            assert p['classification']==inp.payload['classification']
            assert p['content']['title']==inp.payload['content']['title']
            assert p['content']['body_length']==len(p['content']['body'])
            records.append({'source':p['source']['id'],'title':p['content']['title'],
                'rss_chars':len(inp.payload['content']['body']),'enriched_chars':p['content']['body_length'],
                'fetch_status':p['fetch']['status'],'http_status':p['fetch']['http_status'],
                'content_type':p['fetch']['content_type'],'extractor':p['extraction']['method'],
                'document_status':p['enrichment']['status'],'reason':p['enrichment']['reason'],
                'failure_reason':p['enrichment']['failure_reason'],'url':p['source']['url'],
                'document_id':doc.id,'source_message_id':inp.source_message_id,
                'message_id':p['message_id'],'snapshot_id':p['fetch']['snapshot_id']})
        for snapshot in snapshots:
            assert hashlib.sha256(snapshot.raw_body).hexdigest()==snapshot.response_hash
            assert len(snapshot.raw_body)==snapshot.content_length
        chosen=[]
        for source,title in [('fed_monetary_policy','Federal Reserve issues FOMC statement'),
            ('sec_press_releases','SEC Announces Roundtable on Preparations for 24-Hour Trading'),
            ('ecb_press','Christine Lagarde: Interview with Ouest-France'),
            ('ecb_press','Philip R. Lane: Diversity at the European Central Bank')]:
            candidates=[r for r in records if r['source']==source and r['title']==title]
            assert candidates, (source,title)
            chosen.append(sorted(candidates,key=lambda r:r['url'])[0])
        endpoints={p:json.loads(urllib.request.urlopen('http://127.0.0.1:8001/'+p,timeout=10).read()) for p in ('health','ready','stats')}
        print(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),
            'verified_exact_nats_inputs':len(pairs),'verified_nats_outputs':len(pairs),
            'verified_snapshot_hashes':len(snapshots),'by_source_status':dict(Counter(r['source']+'/'+r['document_status'] for r in records)),
            'endpoints':endpoints,'examples':chosen},ensure_ascii=False,indent=2))
    finally:
        await bus.close()
        engine.dispose()

asyncio.run(main())

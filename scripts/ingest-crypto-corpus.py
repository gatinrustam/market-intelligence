"""Bounded historical bootstrap of original official responses via normal outbox.

Run in the ingestion runtime with /feeds containing captured official HTTP bodies.
A second invocation exercises persistent deduplication. No paid API calls.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from app.config import Settings, load_sources
from app.adapters.base import FetchResult
from app.adapters.parsers import parse_entries, incident_identity
from app.storage.database import make_database
from app.normalization.contract import Contract
from app.workers.ingest import Ingestor
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher

SELECTION = [
    ('kraken_status_incidents', 'kraken', 10),
    ('kraken_status_maintenance', 'kraken_maintenance', 5),
    ('coinbase_blog', 'coinbase', 10),
    ('tether_news', 'tether_feed', 5),
    ('tether_news', 'tether_history', 5),
    ('circle_pressroom', 'circle', 6),
    ('circle_pressroom', 'circle_history', 4),
    ('sec_strategy_8k', 'strategy', 10),
]

async def main():
    settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value())
    contract=Contract(settings.schema_path);ingestor=Ingestor(sessions,contract)
    sources={s.id:s for s in load_sources(settings.sources_dir)}
    bus=JetStreamBus(settings.nats_url.get_secret_value());publisher=OutboxPublisher(sessions,bus,contract)
    report=[]
    for source_id,name,limit in SELECTION:
        path=Path('/feeds',name);body=path.read_bytes();source=sources[source_id]
        entries=parse_entries(source,body)
        if source.connector.type=='statuspage':
            identities=list(dict.fromkeys(incident_identity(e['id']) for e in entries))[:limit]
            indices=[i for i,e in enumerate(entries) if incident_identity(e['id']) in identities]
        elif source_id=='coinbase_blog':
            preferred=[i for i,e in enumerate(entries) if 'derivative' in e['title'].lower()]
            indices=list(dict.fromkeys(preferred+list(range(len(entries)))))[:limit]
        else:indices=list(range(min(limit,len(entries))))
        received=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)
        counts=ingestor.process(source,FetchResult(body,received,'application/json' if source.connector.type in ('statuspage','sec_filing') else 'application/rss+xml' if source.connector.type=='rss' else 'text/html'),selected_indices=indices)
        replay=ingestor.process(source,FetchResult(body,received,'application/octet-stream'),selected_indices=indices)
        assert replay['created']==0 and replay['failed']==0
        report.append({'source_id':source_id,'capture':name,'historical_sample':True,'source_url':str(source.connector.url)+('?29c9664d_page=2' if name=='circle_history' else '?paged=2' if name=='tether_history' else ''),'sha256':hashlib.sha256(body).hexdigest(),'received_at':received.isoformat(),'indices':indices,'counts':counts,'replay':replay})
    while await publisher.run_once():pass
    print('CRYPTO_CORPUS_REPORT='+json.dumps(report,ensure_ascii=False))
    await bus.close();engine.dispose()

asyncio.run(main())

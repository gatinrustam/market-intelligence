"""Bounded research bootstrap using the normal Ingestor and transactional outbox.
Keeps complete, unmodified official feeds in raw storage; explicit item indices
select a diverse corpus without replaying a thousand-item MOEX backlog.
"""
import asyncio,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
from app.config import Settings,load_sources
from app.adapters.base import FetchResult
from app.storage.database import make_database
from app.normalization.contract import Contract
from app.workers.ingest import Ingestor
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
SELECTION={'cbr_events_ru':('cbr_events',[0,1,2,3,4,6,7,9,14,15,28,30,33,39]),'cbr_press_ru':('cbr_press',[0,1,2,3,4,7]),'moex_news_ru':('moex',[0,4,6,7,9,10,11,15,19,22,25,30,32,39,41,43,44,46,54,70])}
async def main():
 s=Settings();e,ss=make_database(s.database_url.get_secret_value());contract=Contract(s.schema_path);ingestor=Ingestor(ss,contract);sources={x.id:x for x in load_sources(s.sources_dir)};bus=JetStreamBus(s.nats_url.get_secret_value());publisher=OutboxPublisher(ss,bus,contract)
 report=[]
 for key,(file,indices) in SELECTION.items():
  body=Path('/feeds/'+file+'.xml').read_bytes();counts=ingestor.process(sources[key],FetchResult(body,datetime.now(timezone.utc),'application/rss+xml'),selected_indices=indices)
  report.append({'source_id':key,'url':str(sources[key].connector.url),'feed_sha256':hashlib.sha256(body).hexdigest(),'selected_indices':indices,'counts':counts})
 while await publisher.run_once():pass
 print(json.dumps({'sources':report},ensure_ascii=False))
 await bus.close();e.dispose()
asyncio.run(main())

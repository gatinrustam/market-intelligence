"""Read-only production smoke evidence; run via docker compose exec -T market-data python -."""
import asyncio,json,urllib.request,urllib.parse
from datetime import datetime,timezone
from sqlalchemy import select,func
from app.config import Settings
from app.contract import Contract
from app.storage.database import make_database
from app.storage.models import Snapshot,MarketCandle,OutboxEvent,BackfillJob
from app.storage.repository import candle_payload,aware
from app.publishers.nats import JetStreamBus

def get(path):return json.load(urllib.request.urlopen('http://127.0.0.1:8003'+path,timeout=10))
async def main():
    settings=Settings();contract=Contract(settings.contract_path)
    engine,sessions=make_database(settings.database_url.get_secret_value());bus=JetStreamBus(settings.nats_url)
    try:
        stats=get('/stats');ready=get('/ready')
        assert ready['ready'] and stats['provider_connected'] and stats['trade_updates']>0 and stats['book_updates']>0
        with sessions() as s:
            counts=dict(s.execute(select(MarketCandle.source,func.count()).group_by(MarketCandle.source)).all())
            assert counts.get('websocket',0)>0
            bars=s.scalars(select(MarketCandle).where(MarketCandle.source=='websocket').order_by(MarketCandle.open_time.desc()).limit(2)).all()
            live=s.scalar(select(Snapshot).where(Snapshot.observed_at>=bars[0].open_time,Snapshot.observed_at<=bars[0].close_time).order_by(Snapshot.observed_at.desc()).limit(1))
            assert live
            lookup_path='/market/snapshot?symbol=BTCUSDT&at='+urllib.parse.quote(live.payload['timestamps']['observed_at'])
            historical=get('/market/snapshot?symbol=BTCUSDT&at=2026-04-29T18:00:00Z')
            assert historical['realtime']=={'available':False,'reason':'not_collected'} and historical['candle_1m']['available']
            hist_count=s.scalar(select(func.count()).select_from(MarketCandle).where(MarketCandle.open_time>=datetime(2026,4,29,17,58),MarketCandle.open_time<datetime(2026,4,29,18,3)))
            assert hist_count==5
            jobs=s.scalars(select(BackfillJob).where(BackfillJob.start_at==datetime(2026,4,29,17,58),BackfillJob.end_at==datetime(2026,4,29,18,3))).all()
            assert len(jobs)==1 and jobs[0].status=='completed' and jobs[0].pages==1 and jobs[0].candles_seen==5
            backfill={'range_from':'2026-04-29T17:58:00Z','range_to_exclusive':'2026-04-29T18:03:00Z','candles':hist_count,'job_id':jobs[0].id,'pages':jobs[0].pages,'status':jobs[0].status}
            bars_payload=[candle_payload(b) for b in bars]
        await bus.connect();info=await bus.js.stream_info('MARKET_SNAPSHOTS');assert info.state.messages>=3
        samples=[]
        for seq in range(info.state.last_seq-2,info.state.last_seq+1):
            raw=await bus.js.get_msg('MARKET_SNAPSHOTS',seq=seq);p=json.loads(raw.data);contract.validate(p)
            with sessions() as s:
                row=s.get(Snapshot,p['message_id']);out=s.scalar(select(OutboxEvent).where(OutboxEvent.message_id==p['message_id']))
                assert row and row.payload==p and out.payload==p
            samples.append({'stream_sequence':seq,'subject':raw.subject,'payload':p})
        lookup=get(lookup_path);assert lookup['realtime']['available'] and lookup['candle_1m']['available']
        print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'ready':ready,'stats':stats,
            'candle_counts_by_origin':counts,'nats_stream_messages':info.state.messages,'real_nats_snapshots':samples,
            'live_candle_examples':bars_payload,'live_lookup_request':lookup_path,'live_lookup_response':lookup,
            'historical_backfill':backfill,'historical_lookup_response':historical},indent=2))
    finally:await bus.close();engine.dispose()
asyncio.run(main())

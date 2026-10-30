"""Read-only smoke verification against persisted canonical inputs, NATS and public APIs."""
import asyncio,json,urllib.request,urllib.parse
from datetime import datetime,timezone
from sqlalchemy import select
from app.config import Settings
from app.storage.database import make_database
from app.storage.contract import CanonicalContract,ContextContract
from app.storage.models import ContextInput,MarketContext,ContextRevision
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus

def get(url):return json.load(urllib.request.urlopen(url,timeout=10))
async def main():
    settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value());contract=ContextContract(settings.output_schema_path)
    repo=Repository(sessions,CanonicalContract(settings.input_schema_path),contract,settings);bus=JetStreamBus(settings.nats_url.get_secret_value())
    selected={'historical_fed':'d9b482b8-af7e-4fc9-970a-52b30196142e','recent_ecb':'bf6fd01f-7923-4c63-a8ca-5d8a20601d74','unavailable_sec':'006e85e2-6047-46f8-8d24-59fc133bd458','synthetic_live_fixture':'d74a530b-0545-5979-be27-9753fce69ccc'}
    try:
        await bus.connect();examples={};inputs_verified=0
        with sessions() as s:
            for row in s.scalars(select(ContextInput)):
                if row.jetstream_metadata.get('synthetic_fixture'):continue
                raw=await bus.js.get_msg('EVENTS',seq=row.jetstream_metadata['stream_sequence'])
                assert raw.data==row.exact_payload and json.loads(raw.data)==row.payload
                inputs_verified+=1
            assert inputs_verified==55
            for label,event_id in selected.items():
                row=s.scalar(select(MarketContext).where(MarketContext.event_id==event_id));assert row
                p=get('http://127.0.0.1:8004/contexts/'+row.id);contract.validate(p)
                revisions=get('http://127.0.0.1:8004/contexts/'+row.id+'/revisions')
                examples[label]={'source_title':s.get(ContextInput,row.id).payload['content']['canonical_title'],'context':p,'revisions':revisions}
                if label in ('historical_fed','recent_ecb'):
                    assert p['status']['complete'] and all(q['resolution']=='candle_1m' and q['bid'] is None and q['ask'] is None and q['spread_bps'] is None for q in p['points'])
                if label=='unavailable_sec':
                    # Legacy smoke had no target-minute data. Causal mode may expose
                    # an older stored closed candle; its actual age remains explicit.
                    from app.domain import parse
                    assert all(not q['available'] or parse(q['price_at'])<=parse(q['target_at']) for q in p['points'])
                if label=='synthetic_live_fixture':
                    assert revisions[0]['points'][3]['status']=='pending'
                    assert p['points'][3]['resolution']=='realtime_1s' and len(revisions)>=2
                    assert p['points'][2]['resolution']=='realtime_1s'
                    # Other offsets may honestly fall into real snapshot gaps and use candles.
                for q in p['points']:
                    if q['resolution']=='realtime_1s':
                        data=get(settings.market_data_url+'/market/snapshot?symbol=BTCUSDT&at='+urllib.parse.quote(q['price_at'])+'&mode=causal')
                        assert data['realtime']['snapshot']['message_id']==q['snapshot_message_id']
                    elif q['resolution']=='candle_1m':
                        data=get(settings.market_data_url+'/market/snapshot?symbol=BTCUSDT&at='+urllib.parse.quote(q['target_at'])+'&mode=causal')
                        assert not data['realtime']['available'] and data['candle_1m']['close']==q['price']
            stream=await bus.js.stream_info('MARKET_CONTEXTS');counts={};output_verified=0
            for seq in range(stream.state.first_seq,stream.state.last_seq+1):
                raw=await bus.js.get_msg('MARKET_CONTEXTS',seq=seq);p=json.loads(raw.data);contract.validate(p)
                stored=s.get(ContextRevision,(p['context_id'],p['revision']))
                assert stored and stored.payload==p
                assert raw.subject==('market.context.created.v1' if p['revision']==1 else 'market.context.updated.v1')
                output_verified+=1;counts[raw.subject]=counts.get(raw.subject,0)+1
        readiness={name:get(f'http://{name}:{port}/ready') for name,port in [('ingestion',8000),('enrichment',8001),('events',8002),('market-data',8003),('market-context',8004)]}
        print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'stats':repo.stats(),'verified_exact_real_canonical_inputs':inputs_verified,'verified_nats_context_messages':output_verified,'output_subject_counts':counts,'all_five_services_ready':True,'readiness':readiness,'examples':examples},ensure_ascii=False,indent=2))
    finally:await bus.close();engine.dispose()
asyncio.run(main())

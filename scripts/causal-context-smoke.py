"""Read-only Stage 3.5.1 event-time audit; NOT the current Stage 4 projection.
Run inside the market-context container; captures current state without changing history.
"""
import asyncio,copy,hashlib,json,urllib.request,urllib.parse
from datetime import datetime,timezone
from sqlalchemy import select,func
from app.config import Settings
from app.storage.database import make_database
from app.storage.models import ContextRevision,MarketContext,OutboxEvent
from app.storage.contract import ContextContract
from app.causal import POLICY,point_role,validate_points,decision_view
from app.domain import parse
from app.publishers.nats import JetStreamBus

def get(url):return json.load(urllib.request.urlopen(url,timeout=10))
def digest(p):return hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest()
async def main():
    settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value());bus=JetStreamBus(settings.nats_url.get_secret_value())
    contract=ContextContract(settings.output_schema_path);event_id='d9b482b8-af7e-4fc9-970a-52b30196142e'
    try:
        for attempt in range(60):
            with sessions() as s:
                rows=s.scalars(select(MarketContext)).all()
                pending=s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status=='pending'))
                if rows and all(r.lookup_policy==POLICY for r in rows) and pending==0:break
            await asyncio.sleep(.5)
        else:raise AssertionError('causal recomputation or publication incomplete')
        with sessions() as s:
            rows=s.scalars(select(MarketContext)).all();verified=0;decisions=0;rejected_anchors=0
            for row in rows:
                assert row.lookup_policy==POLICY;contract.validate(row.payload);validate_points(row.payload['points'],row.payload['anchor']);verified+=1
                if row.payload['anchor']['at'] is None:rejected_anchors+=1;continue
                d=decision_view(row.payload,POLICY)
                assert [q['offset_seconds'] for q in d['points']]==[-900,-300,0]
                assert all(q['role']=='causal' and (not q['available'] or parse(q['price_at'])<=parse(q['target_at'])<=parse(d['as_of'])) for q in d['points'])
                mutated=copy.deepcopy(row.payload);mutated['revision']=999999;mutated['generated_at']='2099-01-01T00:00:00Z';mutated['status']={'future':'SECRET'}
                for q in mutated['points'][3:]:q.update(price='SECRET',candle={'secret':'SECRET'},status='SECRET')
                assert decision_view(mutated,POLICY)==d
                decisions+=1
            fed=s.scalar(select(MarketContext).where(MarketContext.event_id==event_id));assert fed
            d=decision_view(fed.payload,POLICY);assert d['complete']
            middle=next(p for p in d['points'] if p['offset_seconds']==0)
            assert middle['target_at']=='2026-04-29T18:00:00Z'
            assert middle['price_at']=='2026-04-29T17:59:59.999000Z'
            for p in d['points']:
                response=get(settings.market_data_url+'/market/snapshot?symbol=BTCUSDT&mode=causal&at='+urllib.parse.quote(p['target_at']))
                assert response['candle_1m']['close_time']==p['price_at'] and response['candle_1m']['close']==p['price']
            revisions=s.scalars(select(ContextRevision).order_by(ContextRevision.context_id,ContextRevision.revision)).all()
            hashes={r.context_id+':'+str(r.revision):{'message_id':r.message_id,'payload_sha256':digest(r.payload),'lookup_policy':r.lookup_policy} for r in revisions}
            fed_revisions=[{'lookup_policy':r.lookup_policy,'payload':r.payload} for r in revisions if r.context_id==fed.id]
        await bus.connect();info=await bus.js.stream_info('MARKET_CONTEXTS');published={}
        for seq in range(info.state.first_seq,info.state.last_seq+1):
            raw=await bus.js.get_msg('MARKET_CONTEXTS',seq=seq);p=json.loads(raw.data)
            key=p['context_id']+':'+str(p['revision'])
            if hashes[key]['lookup_policy']==POLICY:
                contract.validate(p);validate_points(p['points'],p['anchor']);assert digest(p)==hashes[key]['payload_sha256']
                published[key]={'sequence':seq,'subject':raw.subject,'message_id':p['message_id']}
        assert len(published)==sum(v['lookup_policy']==POLICY for v in hashes.values())
        readiness={name:get(f'http://{name}:{port}/ready') for name,port in [('ingestion',8000),('enrichment',8001),('events',8002),('market-data',8003),('market-context',8004)]}
        print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'verified_causal_contexts':verified,'verified_decision_views':decisions,'unresolvable_anchor_contexts':rejected_anchors,'all_price_cutoffs_verified':True,'outcome_mutation_cannot_change_decision':True,'revision_hashes':hashes,'verified_causal_nats_publications':published,'fed_decision':d,'fed_revision_history':fed_revisions,'readiness':readiness},ensure_ascii=False,indent=2))
    finally:await bus.close();engine.dispose()
asyncio.run(main())

"""Read-only, revision-pinned decision package with explicit observation/simulation time."""
import asyncio,copy
from datetime import timedelta
import httpx
from app.domain import parse,iso,UTC,now,resolve_point,returns
from app.causal import CAUSAL_OFFSETS
from app.freshness import FRESHNESS_POLICY,freshness_limits,fresh_point
from app.storage.contract import Contract

class DecisionUnavailable(ValueError):pass

class DecisionInputs:
    def __init__(self,bus,settings):
        self.bus=bus
        self.client=httpx.AsyncClient(base_url=settings.events_url,timeout=8,limits=httpx.Limits(max_connections=4))
        self.contract=Contract(settings.enriched_schema_path)
    async def canonical_available_at(self,input_row):
        meta=input_row.jetstream_metadata
        if meta.get('synthetic_fixture'):raise DecisionUnavailable('synthetic input has no observed canonical publication')
        if meta.get('published_at'):
            return parse(meta['published_at'])
        # Older inputs predate local recording of the NATS timestamp. Read original
        # retained message, never substitute source publication or request time.
        await self.bus.connect()
        raw=await self.bus.js.get_msg('EVENTS',seq=meta['stream_sequence'])
        if raw.data!=input_row.exact_payload or raw.subject!=input_row.subject or raw.time is None:
            raise DecisionUnavailable('canonical publication provenance mismatch')
        return raw.time.astimezone(UTC)
    async def evidence(self,reference):
        response=await self.client.get('/documents/'+reference['document_id']+'/input')
        if response.status_code==404:raise DecisionUnavailable('required immutable evidence unavailable')
        response.raise_for_status();data=response.json();self.contract.validate(data['document'])
        return data
    async def close(self):await self.client.aclose()

class DecisionResolver:
    def __init__(self,inputs,market,settings,clock=now):
        self.inputs=inputs;self.market=market;self.settings=settings;self.clock=clock
    async def build(self,context_id,input_row,basis='live',additional_input_available_at=None):
        if basis not in ('live','research_hypothetical'):raise DecisionUnavailable('unsupported decision basis')
        event=copy.deepcopy(input_row.payload)
        canonical_available=await self.inputs.canonical_available_at(input_row)
        semaphore=asyncio.Semaphore(4)
        async def evidence(reference):
            async with semaphore:record=await self.inputs.evidence(reference)
            doc=record['document']
            if (doc['document_id']!=reference['document_id'] or doc['message_id']!=reference['input_message_id'] or
                doc['lineage']['source_message_id']!=reference['source_message_id'] or doc['source']['id']!=reference['source_id']):
                raise DecisionUnavailable('event revision and document lineage mismatch')
            received=parse(record['input_received_at']);timestamps=doc['timestamps']
            enriched=parse(timestamps['enriched_at']);ingested=parse(timestamps['received_at'])
            fetched=parse(doc['fetch']['fetched_at']) if doc['fetch']['fetched_at'] else None
            available=max(t for t in (received,enriched,ingested,fetched) if t is not None)
            published=parse(timestamps['published_at']) if timestamps['published_at'] else None
            return {'document':copy.deepcopy(doc),'evidence_available_at':iso(available),
                'availability_basis':'event_engine_input_received_and_document_provenance',
                'event_engine_input_received_at':iso(received),'evidence_enriched_at':iso(enriched),
                'evidence_fetched_at':iso(fetched) if fetched else None,
                'late_enrichment':published is not None and (available-published).total_seconds()>self.settings.late_enrichment_seconds,
                'historical_content_verified':False,'historical_content_verification':'no_archival_publication_time_content_proof'}
        documents=await asyncio.gather(*(evidence(ref) for ref in event['evidence']['documents']))
        available=max(parse(d['evidence_available_at']) for d in documents)
        fetched=[parse(d['evidence_fetched_at']) for d in documents if d['evidence_fetched_at']]
        generated=max(parse(event['time']['first_detected_at']),parse(event['time']['last_updated_at']))
        # Earliest joint availability evidenced by existing durable-pipeline clocks.
        live_at=max(canonical_available,available,generated)
        if additional_input_available_at is not None:
            if basis!='live':raise DecisionUnavailable('additional input availability is only valid for live decisions')
            live_at=max(live_at,parse(additional_input_available_at))
        if basis=='live':decision_at=live_at
        else:
            published=event['time']['earliest_source_published_at']
            if published is None:raise DecisionUnavailable('research source publication time unavailable')
            decision_at=parse(published)
        if live_at>self.clock() or decision_at>self.clock():raise DecisionUnavailable('provenance timestamp is in the future')
        async def point(offset):
            target=decision_at+timedelta(seconds=offset)
            data=await self.market.lookup(target,known_at=decision_at if basis=='live' else None)
            p=resolve_point(offset,target,data,self.clock(),self.settings.data_grace_seconds)
            if p['available'] and not parse(p['price_at'])<=target<=decision_at:raise DecisionUnavailable('noncausal decision market point')
            return {**fresh_point(p,freshness_limits(self.settings)),'role':'causal'}
        points=returns(await asyncio.gather(*(point(o) for o in CAUSAL_OFFSETS)))
        simulation=basis=='research_hypothetical'
        complete=all(p['available'] for p in points)
        ready=next(p['available'] for p in points if p['offset_seconds']==0)
        return {'context_id':context_id,'event':{'event_id':event['event']['id'],'event_revision':event['event']['revision']},
            'event_time':event['time']['event_time'],'event_time_precision':event['time']['event_time_precision'],
            'decision_at':iso(decision_at),'as_of':iso(decision_at),'decision_mode':basis,
            'decision_basis':'source_published_at' if simulation else 'live_observed','historical_simulation':simulation,
            'availability_scope':'durable_pipeline','canonical_available_at':iso(canonical_available),
            'canonical_generated_at':iso(generated),'resolver_observed_at':iso(input_row.received_at.replace(tzinfo=UTC)),
            'live_inputs_available_at':iso(live_at),'evidence_available_at':iso(available),
            'evidence_fetched_at':iso(max(fetched)) if fetched else None,'historical_content_verified':False,
            'content_assumption':'later_observed_content_hypothetically_available_at_publication' if simulation else 'exact_observed_inputs_available_by_decision_at',
            'known_information':{'canonical_event':event,'evidence':documents},
            'market':{'provider':'binance_spot','symbol':'BTCUSDT'},'lookup_policy':FRESHNESS_POLICY,
            'freshness_policy':{'version':FRESHNESS_POLICY,'max_age_seconds':freshness_limits(self.settings)},
            'market_availability_basis':'historical_observation_time_only' if simulation else 'locally_collected_by_decision_at',
            'points':points,'complete':complete,'decision_ready':ready,
            'market_data_status':'available' if complete else 'market_data_unavailable'}

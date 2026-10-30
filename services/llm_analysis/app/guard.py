"""Independent fail-closed validation and allowlisted immutable LLM input."""
import copy,math
from datetime import timedelta
from decimal import Decimal
from app.domain import parse,now
from app.storage.contract import Contract
class Blocked(ValueError):pass

def build_input(package,expected,settings):
    try:return _build(package,expected,settings)
    except Blocked:raise
    except Exception:raise Blocked('invalid_decision_provenance') from None

def _build(p,expected,settings):
    def require(ok,reason):
        if not ok:raise Blocked(reason)
    require(p['decision_ready'] is True,'market_decision_not_ready')
    require(p['lookup_policy']=='causal_asof_fresh_v1','unsupported_market_policy')
    require(p['market']=={'provider':'binance_spot','symbol':'BTCUSDT'},'market_identity_mismatch')
    require(p['event']==expected,'event_revision_mismatch')
    decision=parse(p['decision_at']);simulation=p['historical_simulation']
    require(decision<=now() and parse(p['as_of'])==decision,'invalid_decision_cutoff')
    require(p['market_availability_basis']==('historical_observation_time_only' if simulation else 'locally_collected_by_decision_at'),'invalid_market_availability_basis')
    require(type(simulation) is bool,'invalid_simulation_marker')
    require((p['decision_mode'],p['decision_basis'])==(('research_hypothetical','source_published_at') if simulation else ('live','live_observed')),'inconsistent_decision_basis')
    event=p['known_information']['canonical_event']
    Contract(settings.contracts_dir/'event/canonical/v1.schema.json').validate(event)
    require({'event_id':event['event']['id'],'event_revision':event['event']['revision']}==expected,'canonical_revision_mismatch')
    if simulation:require(parse(event['time']['earliest_source_published_at'])==decision,'research_publication_mismatch')
    else:
        for k in ('canonical_available_at','canonical_generated_at','live_inputs_available_at','evidence_available_at'):
            require(parse(p[k])<=decision,'live_input_after_decision')
        for k in ('first_detected_at','last_updated_at'):require(parse(event['time'][k])<=decision,'canonical_after_decision')
    refs={r['document_id']:r for r in event['evidence']['documents']}
    docs=p['known_information']['evidence']
    require(len(refs)==len(docs)==event['evidence']['document_count'],'missing_evidence')
    selected=[];seen=set()
    for item in docs:
        doc=item['document'];Contract(settings.contracts_dir/'document/enriched/v1.schema.json').validate(doc)
        ref=refs[doc['document_id']]
        require(doc['document_id'] not in seen,'duplicate_evidence');seen.add(doc['document_id'])
        require(doc['message_id']==ref['input_message_id'] and doc['lineage']['source_message_id']==ref['source_message_id'] and doc['source']['id']==ref['source_id'],'evidence_revision_mismatch')
        available=parse(item['evidence_available_at'])
        require((parse(item['evidence_fetched_at']) if item['evidence_fetched_at'] else None)==(parse(doc['fetch']['fetched_at']) if doc['fetch']['fetched_at'] else None),'fetch_provenance_mismatch')
        stamps=[parse(item[k]) for k in ('event_engine_input_received_at','evidence_enriched_at')]
        stamps += [parse(doc['timestamps'][k]) for k in ('received_at','enriched_at')]
        if doc['fetch']['fetched_at']:stamps.append(parse(doc['fetch']['fetched_at']))
        require(available>=max(stamps),'inconsistent_evidence_availability')
        require(item['historical_content_verified'] is False and p['historical_content_verified'] is False,'unsupported_historical_verification')
        if not simulation:require(available<=decision,'live_evidence_after_decision')
        selected.append({k:copy.deepcopy(item[k]) for k in ('document','evidence_available_at','evidence_fetched_at','evidence_enriched_at','late_enrichment','historical_content_verified')})
    require([q['offset_seconds'] for q in p['points']]==[-900,-300,0],'outcomes_or_invalid_offsets')
    limits=p['freshness_policy']['max_age_seconds']
    require(p['freshness_policy']['version']==p['lookup_policy'],'freshness_version_mismatch')
    for key in ('realtime_1s','candle_1m'):require(isinstance(limits[key],(int,float)) and math.isfinite(limits[key]) and limits[key]>0,'invalid_freshness_limit')
    points=[]
    for q in p['points']:
        require(q['role']=='causal','outcome_point')
        target=parse(q['target_at']);require(target==decision+timedelta(seconds=q['offset_seconds']),'invalid_target')
        if q['available']:
            age=(target-parse(q['price_at'])).total_seconds()
            require(0<=age<=limits[q['resolution']] and age==q['age_seconds'] and q['max_age_seconds']==limits[q['resolution']],'stale_or_future_market_data')
            require(Decimal(q['price']).is_finite() and Decimal(q['price'])>0,'invalid_market_price')
            if q['resolution']=='candle_1m':
                require(q['candle']['close_time']==q['price_at'] and q['candle']['close']==q['price'] and parse(q['candle']['open_time'])<=parse(q['price_at']),'candle_mismatch')
            elif q['resolution']!='realtime_1s':raise Blocked('unsupported_resolution')
        else:
            require(q['offset_seconds']!=0,'missing_t')
            require(all(q[k] is None for k in ('price','price_at','candle','bid','ask','spread_bps','return_pct_from_anchor','absolute_return_pct')),'unavailable_price_leak')
        # Never forward arbitrary nested metadata, snapshot payloads or derived returns.
        points.append({k:copy.deepcopy(q[k]) for k in ('offset_seconds','target_at','available','reason','resolution','price','price_at','age_seconds','max_age_seconds','bid','ask','spread_bps')})
    return {'event_identity':copy.deepcopy(expected),'event':copy.deepcopy(event),'evidence':selected,
        'decision':{k:copy.deepcopy(p[k]) for k in ('decision_at','decision_basis','decision_mode','historical_simulation','historical_content_verified','content_assumption','canonical_available_at','evidence_available_at','evidence_fetched_at','availability_scope')},
        'market_context':{'symbol':'BTCUSDT','lookup_policy':p['lookup_policy'],'freshness_policy':{'version':p['lookup_policy'],'max_age_seconds':{k:limits[k] for k in ('realtime_1s','candle_1m')}},'market_availability_basis':p['market_availability_basis'],'points':points},
        'unavailable_data':['market_surprise','consensus_expectation','probability_of_fed_action']}

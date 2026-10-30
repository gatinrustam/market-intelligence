"""Opt-in pinned intelligence input; legacy inputs and prompt remain unchanged."""
import copy
import httpx
from app.domain import digest,parse,now
from app.guard import Blocked
from app.storage.contract import Contract

PROMPT='btc_event_intelligence_v1'
class IntelligenceClient:
    def __init__(self,url):self.client=httpx.AsyncClient(base_url=url,timeout=10)
    async def fetch(self,key):
        response=await self.client.get('/intelligence/'+key+'/availability')
        if response.status_code in (404,409):raise Blocked('event_intelligence_unavailable')
        response.raise_for_status();return response.json()
    async def close(self):await self.client.aclose()

def attach(package,envelope,key,settings):
    try:
        value=envelope['intelligence']
        available=parse(envelope['available_at'])
        if envelope['availability_basis']!='confirmed_jetstream_publication':raise ValueError('availability basis')
        Contract(settings.contracts_dir/'event/intelligence/v1.schema.json').validate(value)
        if value['intelligence_id']!=key or value['event']!=package['event_identity'] or value['asset']['symbol']!='BTCUSDT':raise ValueError('identity')
        if value['basis']['canonical_hash']!=digest(package['event']):raise ValueError('canonical hash')
        hashes=[{'document_id':e['document']['document_id'],'message_id':e['document']['message_id'],'content_hash':e['document']['integrity']['content_hash']} for e in package['evidence']]
        if sorted(hashes,key=lambda e:e['document_id'])!=sorted(value['basis']['evidence_hashes'],key=lambda e:e['document_id']):raise ValueError('evidence hashes')
        generated=parse(value['generated_at']);decision=parse(package['decision']['decision_at'])
        if not generated<=available<=now():raise ValueError('invalid availability time')
        simulation=package['decision']['historical_simulation']
        if not simulation and available>decision:raise Blocked('intelligence_available_after_decision')
        # v1 has no consensus provider; do not accept an unsupported availability claim.
        if value['surprise']['status']!='unavailable' or value['basis']['expectations_basis']!='no_external_provider':raise ValueError('unsupported expectations provider')
        result=copy.deepcopy(package);result['event_intelligence']=copy.deepcopy(value)
        result['intelligence_availability']={'available_at':envelope['available_at'],'availability_basis':envelope['availability_basis'],'hypothetical_derivation':simulation,
            'assumption':'current_rules_on_pinned_historical_evidence' if simulation else None}
        return result
    except Blocked:raise
    except Exception:raise Blocked('invalid_event_intelligence') from None

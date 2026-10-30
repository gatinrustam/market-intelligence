import asyncio,json
import httpx
from app.domain import prompt,normalize,validate_output
from app.provider import request_body,ProviderError
from app.guard import build_input,Blocked
from app.storage.contract import Contract
from app.intelligence import attach,PROMPT
class DecisionClient:
    def __init__(self,url):self.client=httpx.AsyncClient(base_url=url,timeout=35)
    async def fetch(self,context_id,basis,additional_input_available_at=None):
        params={'basis':basis}
        if additional_input_available_at is not None:params['additional_input_available_at']=additional_input_available_at
        r=await self.client.get('/contexts/'+context_id+'/decision',params=params)
        if r.status_code in (404,409):raise Blocked('decision_provenance_unavailable')
        r.raise_for_status();return r.json()
    async def close(self):await self.client.aclose()
class Worker:
    def __init__(self,repo,decisions,provider,settings,intelligence=None):
        self.repo=repo;self.decisions=decisions;self.provider=provider;self.settings=settings;self.intelligence=intelligence
    async def run_once(self):
        job=await asyncio.to_thread(self.repo.claim)
        if job is None:return False
        run_id=None
        try:
            uses_intelligence=job.configuration['prompt_version']==PROMPT
            intelligence_id=job.configuration.get('intelligence_id')
            if uses_intelligence != bool(intelligence_id):raise Blocked('intelligence_mode_mismatch')
            if job.input_id:input_row=await asyncio.to_thread(self.repo.input,job.input_id)
            else:
                intelligence_envelope=None
                if uses_intelligence:
                    if self.intelligence is None:raise Blocked('event_intelligence_unavailable')
                    intelligence_envelope=await self.intelligence.fetch(intelligence_id)
                if uses_intelligence and job.basis=='live':
                    package=await self.decisions.fetch(job.context_id,job.basis,additional_input_available_at=intelligence_envelope['available_at'])
                else:package=await self.decisions.fetch(job.context_id,job.basis)
                if package['decision_mode']!=job.basis:raise Blocked('requested_basis_mismatch')
                value=build_input(package,{'event_id':job.event_id,'event_revision':job.event_revision},self.settings)
                if uses_intelligence:
                    value=attach(value,intelligence_envelope,intelligence_id,self.settings)
                input_row=await asyncio.to_thread(self.repo.freeze,job,value)
            if uses_intelligence:
                frozen=json.loads(input_row.canonical_json)
                checked=attach(frozen,{'intelligence':frozen.get('event_intelligence'),**{k:frozen['intelligence_availability'][k] for k in ('available_at','availability_basis')}},intelligence_id,self.settings)
                if checked!=frozen:raise Blocked('intelligence_frozen_input_mismatch')
            _,schema,prompt_hash=prompt(job.configuration['prompt_version'])
            if prompt_hash!=job.prompt_hash:raise Blocked('prompt_integrity_failure')
            request=request_body(job.configuration,input_row.canonical_json)
            run_id=await asyncio.to_thread(self.repo.start_run,job,request)
            result=await asyncio.wait_for(self.provider.analyze(request),timeout=self.settings.request_timeout_seconds)
            validate_output(result['output'],schema)
            payload=normalize(job,input_row,result['output'])
            Contract(self.settings.contracts_dir/'analysis/v1.schema.json').validate(payload)
            await asyncio.to_thread(self.repo.finish,job,run_id,payload,result['audit'])
        except Blocked as exc:await asyncio.to_thread(self.repo.finish,job,run_id,error=str(exc),blocked=True)
        except ProviderError as exc:
            await asyncio.to_thread(self.repo.finish,job,run_id,audit=exc.audit,error=exc.code,retry=exc.transient or exc.invalid,invalid=exc.invalid,blocked=exc.code=='missing_api_key')
        except (TimeoutError,httpx.TimeoutException,httpx.NetworkError):
            await asyncio.to_thread(self.repo.finish,job,run_id,error='transport_timeout_or_connection',retry=True)
        except httpx.HTTPStatusError as exc:
            await asyncio.to_thread(self.repo.finish,job,run_id,error='decision_http_'+str(exc.response.status_code),retry=exc.response.status_code==429 or exc.response.status_code>=500)
        except Exception as exc:
            await asyncio.to_thread(self.repo.finish,job,run_id,error=type(exc).__name__)
        return True

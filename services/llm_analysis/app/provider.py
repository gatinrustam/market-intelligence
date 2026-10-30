"""Responses API transport. No tools, sessions, retrieval or reasoning trace persistence."""
import json,time
from typing import Protocol
import httpx
from app.domain import prompt,validate_output
class ProviderError(Exception):
    def __init__(self,code,transient=False,invalid=False,audit=None):
        super().__init__(code);self.code=code;self.transient=transient;self.invalid=invalid;self.audit=audit or {}
class LLMProvider(Protocol):
    async def analyze(self,request:dict)->dict:...

def request_body(configuration,input_json):
    instructions,schema,_=prompt(configuration['prompt_version'])
    return {'model':configuration['model'],'reasoning':{'effort':configuration['reasoning_effort']},
        'max_output_tokens':configuration['max_output_tokens'],'store':False,'tools':[],'tool_choice':'none',
        'input':[{'role':'developer','content':instructions},{'role':'user','content':input_json}],
        'text':{'format':{'type':'json_schema','name':configuration['prompt_version'],'strict':True,'schema':schema}}}

class OpenAIProvider:
    def __init__(self,key,timeout=120,client=None):
        self.key=key;self.client=client or httpx.AsyncClient(timeout=timeout)
    async def analyze(self,request):
        started=time.monotonic()
        if not self.key:raise ProviderError('missing_api_key')
        try:
            response=await self.client.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+self.key},json=request)
        except (httpx.TimeoutException,httpx.NetworkError) as exc:
            raise ProviderError(type(exc).__name__,transient=True,audit={'latency_ms':round((time.monotonic()-started)*1000)}) from None
        audit={'latency_ms':round((time.monotonic()-started)*1000),'http_status':response.status_code,'request_id':response.headers.get('x-request-id')}
        if response.status_code>=400:
            # Never store raw error bodies/headers: proxies can echo credentials or requests.
            raise ProviderError('http_'+str(response.status_code),transient=response.status_code==429 or response.status_code>=500,audit=audit)
        try:body=response.json()
        except ValueError:raise ProviderError('invalid_provider_json',invalid=True,audit=audit) from None
        audit.update(provider_response_id=body.get('id'),model=body.get('model'),usage=body.get('usage'),status=body.get('status'),cost_usd=None,cost_basis='not_returned_by_provider')
        texts=[];refusal=False
        for item in body.get('output',[]):
            if item.get('type')=='reasoning':continue # internal reasoning is neither requested nor saved
            if item.get('type')!='message':raise ProviderError('unexpected_provider_tool_output',invalid=True,audit=audit)
            for content in item.get('content',[]):
                if content.get('type')=='refusal':refusal=True
                elif content.get('type')=='output_text':texts.append(content.get('text',''))
        audit['raw_structured_response']=''.join(texts)
        if refusal:raise ProviderError('provider_refusal',audit=audit)
        if body.get('status')!='completed':raise ProviderError('incomplete_response',invalid=True,audit=audit)
        try:
            value=json.loads(audit['raw_structured_response'])
            validate_output(value,request['text']['format']['schema'])
        except Exception:raise ProviderError('invalid_structured_output',invalid=True,audit=audit) from None
        return {'output':value,'audit':audit}
    async def close(self):await self.client.aclose()

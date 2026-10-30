import httpx
from app.domain import iso
class MarketDataClient:
    def __init__(self,url):self.client=httpx.AsyncClient(base_url=url,timeout=8,limits=httpx.Limits(max_connections=4))
    async def lookup(self,target,known_at=None):
        params={'symbol':'BTCUSDT','at':iso(target),'mode':'causal'}
        if known_at is not None:params['known_at']=iso(known_at)
        response=await self.client.get('/market/snapshot',params=params)
        response.raise_for_status();return response.json()
    async def close(self):await self.client.aclose()

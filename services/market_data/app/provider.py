import asyncio
import json
import random
from typing import Protocol, AsyncIterator
import httpx
from websockets.asyncio.client import connect
from app.domain import Trade, Book, Candle, decimal, epoch, now
from app.logging import log

class MarketDataProvider(Protocol):
    def events(self) -> AsyncIterator[Trade | Book | Candle]: ...
    async def klines(self, start_ms: int, end_ms: int, limit: int=1000) -> list[Candle]: ...

def normalize(payload, received):
    d=payload.get('data',payload)
    if d.get('s') != 'BTCUSDT': raise ValueError('unexpected symbol')
    if d.get('e')=='aggTrade':
        price=decimal(d['p'])
        if price<=0: raise ValueError('zero price')
        return Trade(int(d['a']),price,epoch(d['E']),received)
    if 'b' in d and 'B' in d:
        b=Book(int(d['u']),decimal(d['b']),decimal(d['a']),decimal(d['B']),decimal(d['A']),received)
        if b.bid<=0 or b.ask<b.bid: raise ValueError('invalid book')
        return b
    if d.get('e')=='kline':
        k=d['k']
        if k['i']!='1m' or k.get('s','BTCUSDT')!='BTCUSDT': raise ValueError('unexpected candle')
        if k['x'] is not True: return None
        return candle([k['t'],k['o'],k['h'],k['l'],k['c'],k['v'],k['T'],k['q'],k['n'],k['V'],k['Q']])
    raise ValueError('unknown market event')

def candle(row):
    c=Candle(epoch(row[0]),epoch(row[6]),*[decimal(row[i]) for i in [1,2,3,4,5,7]],int(row[8]),decimal(row[9]),decimal(row[10]))
    if int(row[0])%60000 or int(row[6])!=int(row[0])+59999 or c.trade_count<0 or c.low>min(c.open,c.close) or c.high<max(c.open,c.close) or c.low<=0:
        raise ValueError('invalid final candle')
    return c

def retry_delay(attempt): return min(60,2**min(attempt,6))+random.uniform(0,1)

class BinanceSpotProvider:
    url='wss://data-stream.binance.vision/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker/btcusdt@kline_1m'
    def __init__(self,state,rest_interval=1,connector=connect):
        self.state=state; self.rest_interval=rest_interval; self.connector=connector
        self.rest_lock=asyncio.Lock(); self.next_request=0
    async def events(self):
        attempt=0
        while True:
            try:
                async with self.connector(self.url,ping_interval=None,open_timeout=15,close_timeout=5,max_queue=32) as ws:
                    self.state.connected=True
                    log('provider_connected',provider='binance_spot')
                    started=asyncio.get_running_loop().time()
                    async for raw in ws:
                        data=json.loads(raw)
                        if data.get('data',data).get('e')=='serverShutdown': raise ConnectionError('server shutdown')
                        event=normalize(data,now())
                        if asyncio.get_running_loop().time()-started>30: attempt=0
                        if event: yield event
                    raise ConnectionError('stream ended')
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.state.reset(); self.state.reconnect_count+=1
                delay=retry_delay(attempt); attempt+=1
                log('provider_reconnect',error_type=type(exc).__name__,delay_seconds=delay)
                await asyncio.sleep(delay)
            finally: self.state.reset()
    async def request(self,client,path,params=None):
        loop=asyncio.get_running_loop()
        for attempt in range(6):
            await asyncio.sleep(max(0,self.next_request-loop.time()))
            self.next_request=loop.time()+self.rest_interval
            r=await client.get(path,params=params)
            if r.status_code in (429,418):
                wait=max(float(r.headers.get('Retry-After','60')),retry_delay(attempt))
                self.next_request=loop.time()+wait
                log('rest_rate_limited',status=r.status_code,retry_seconds=wait)
                if attempt==5: r.raise_for_status()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError('REST retries exhausted')
    async def klines(self,start_ms,end_ms,limit=1000):
        async with self.rest_lock:
            async with httpx.AsyncClient(base_url='https://data-api.binance.vision',timeout=30) as client:
                server=await self.request(client,'/api/v3/time')
                data=await self.request(client,'/api/v3/klines',{'symbol':'BTCUSDT','interval':'1m','startTime':start_ms,'endTime':end_ms-1,'limit':limit})
                # Exchange time, taken before the kline request, prevents local clock skew
                # from promoting a still-open bar to canonical history.
                return [candle(row) for row in data if int(row[6])<int(server['serverTime'])]

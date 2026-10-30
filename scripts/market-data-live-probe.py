"""Run inside market-data container; inject one real WS disconnect, verify reconnect."""
import asyncio,json
from websockets.asyncio.client import connect
from app.domain import MarketState,Trade,Book
from app.provider import BinanceSpotProvider

async def main():
    state=MarketState();connections=0;seen=set();first=set()
    class Socket:
        async def __aenter__(self):
            nonlocal connections
            self.context=connect(BinanceSpotProvider.url,ping_interval=None,open_timeout=15)
            self.ws=await self.context.__aenter__();connections+=1;return self
        async def __aexit__(self,*args):return await self.context.__aexit__(*args)
        def __aiter__(self):return self
        async def __anext__(self):
            if connections==1 and seen=={'Trade','Book'}:
                first.update(seen);seen.clear()
                await self.ws.close(code=1000,reason='Stage 3 reconnect smoke')
                raise ConnectionError('intentional smoke disconnect')
            return await self.ws.recv()
    provider=BinanceSpotProvider(state,connector=lambda *a,**k:Socket())
    events=provider.events()
    try:
        async with asyncio.timeout(45):
            async for event in events:
                if isinstance(event,(Trade,Book)):
                    state.apply(event);seen.add(type(event).__name__)
                if connections>=2 and seen=={'Trade','Book'}:
                    assert first==seen and state.reconnect_count==1
                    print(json.dumps({'real_websocket_connections':connections,'intentional_disconnects':1,'automatic_reconnects':state.reconnect_count,'fresh_trade_and_book_after_reconnect':True}))
                    break
    finally:await events.aclose()
asyncio.run(main())

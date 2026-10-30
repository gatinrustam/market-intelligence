"""UTC, minute-aligned, half-open [from,to) historical candle import."""
import argparse
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.config import Settings
from app.domain import MarketState, now
from app.provider import BinanceSpotProvider
from app.storage.database import make_database
from app.storage.models import BackfillJob, new_id, utcnow
from app.storage.repository import naive, aware, insert_candle
from app.logging import configure_logging, log

class Backfill:
    def __init__(self,sessions,provider): self.sessions=sessions; self.provider=provider
    def claim(self,start,end):
        key=hashlib.sha256(f'binance_spot:BTCUSDT:1m:{start.isoformat()}:{end.isoformat()}'.encode()).hexdigest()
        try:
            with self.sessions.begin() as s:
                if s.get(BackfillJob,key) is None:
                    s.add(BackfillJob(id=key,start_at=naive(start),end_at=naive(end),cursor_at=naive(start)))
        except IntegrityError: pass
        with self.sessions.begin() as s:
            job=s.scalar(select(BackfillJob).where(BackfillJob.id==key).with_for_update())
            if job.status=='completed': return job,None
            if job.lease_until and job.lease_until>utcnow(): raise RuntimeError('backfill job is leased')
            token=new_id(); job.lease_token=token; job.lease_until=utcnow()+timedelta(seconds=90)
            job.status='running'; job.last_error=None
            s.flush(); return job,token
    def renew(self,key,token):
        with self.sessions.begin() as s:
            result=s.execute(update(BackfillJob).where(BackfillJob.id==key,BackfillJob.lease_token==token).values(lease_until=utcnow()+timedelta(seconds=90)))
            if result.rowcount!=1: raise RuntimeError('lost backfill lease')
    async def heartbeat(self,key,token):
        while True:
            await asyncio.sleep(20)
            await asyncio.to_thread(self.renew,key,token)
    def commit_page(self,key,token,rows,cursor,end):
        with self.sessions.begin() as s:
            job=s.scalar(select(BackfillJob).where(BackfillJob.id==key).with_for_update())
            if job.lease_token!=token: raise RuntimeError('lost backfill lease')
            for c in rows: insert_candle(s,c,'rest')
            job.cursor_at=naive(cursor); job.pages+=1; job.candles_seen+=len(rows); job.updated_at=utcnow()
            if cursor>=end: job.status='completed'; job.lease_token=None; job.lease_until=None
    def failed(self,key,token,error):
        with self.sessions.begin() as s:
            s.execute(update(BackfillJob).where(BackfillJob.id==key,BackfillJob.lease_token==token).values(status='pending',lease_token=None,lease_until=None,last_error=error,updated_at=utcnow()))
    async def run(self,start,end):
        if start.tzinfo is None or end.tzinfo is None: raise ValueError('UTC-aware range required')
        start=start.astimezone(timezone.utc); end=end.astimezone(timezone.utc)
        if start>=end or any(t.second or t.microsecond for t in (start,end)): raise ValueError('minute-aligned nonempty range required')
        if end>now().replace(second=0,microsecond=0): raise ValueError('range must contain only closed minutes')
        job,token=await asyncio.to_thread(self.claim,start,end)
        if token is None: return job.id
        heartbeat=asyncio.create_task(self.heartbeat(job.id,token))
        try:
            cursor=aware(job.cursor_at)
            while cursor<end:
                if heartbeat.done(): heartbeat.result()
                # Fixed windows prevent an empty response skipping the entire remainder.
                page_end=min(end,cursor+timedelta(minutes=1000))
                rows=await self.provider.klines(int(cursor.timestamp()*1000),int(page_end.timestamp()*1000),1000)
                expected=int((page_end-cursor).total_seconds()/60)
                # BTCUSDT 1m is continuous. Never mark an incomplete window complete.
                if len(rows)!=expected or any(c.open_time!=cursor+timedelta(minutes=i) or c.close_time>=page_end for i,c in enumerate(rows)):
                    log('candle_gap',start_at=cursor.isoformat(),expected=expected,received=len(rows))
                    raise ValueError('incomplete or unordered candle page; resumable cursor unchanged')
                await asyncio.to_thread(self.commit_page,job.id,token,rows,page_end,end)
                cursor=page_end
            log('backfill_completed',job_id=job.id)
            return job.id
        except BaseException as exc:
            await asyncio.to_thread(self.failed,job.id,token,type(exc).__name__)
            raise
        finally:
            heartbeat.cancel(); await asyncio.gather(heartbeat,return_exceptions=True)

def timestamp(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if len(value)==10: t=t.replace(tzinfo=timezone.utc)
    if t.tzinfo is None: raise ValueError('timestamp requires timezone; dates mean UTC')
    return t.astimezone(timezone.utc)

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',choices=['BTCUSDT'],default='BTCUSDT'); parser.add_argument('--interval',choices=['1m'],default='1m')
    parser.add_argument('--from',dest='start',required=True,type=timestamp); parser.add_argument('--to',dest='end',required=True,type=timestamp)
    args=parser.parse_args(); settings=Settings(); configure_logging()
    engine,sessions=make_database(settings.database_url.get_secret_value())
    try: print(await Backfill(sessions,BinanceSpotProvider(MarketState(),settings.rest_interval_seconds)).run(args.start,args.end))
    finally: engine.dispose()
if __name__=='__main__': asyncio.run(main())

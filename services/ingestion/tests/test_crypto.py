import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.config import SourceConfig
from app.adapters.base import FetchResult
from app.adapters.parsers import parse_entries, SourceParseError, incident_identity
from app.normalization.rss import normalize
from app.storage.models import Base, RawPayload, NewsItem, FailedItem
from app.workers.ingest import Ingestor


def source(kind, fmt=None, corporate=None):
    c={'type':kind, 'url':'https://status.kraken.com/api/v2/incidents.json'}
    if fmt:c['format']=fmt
    if corporate:c['corporate']=corporate
    return SourceConfig(id='crypto_test',name='Test',connector=c,language='en')


def payload():
    return {'incidents':[{'id':'incident1','name':'Funding unavailable','incident_updates':[
        {'id':status,'status':status,'body':'Funding is '+status,'created_at':f'2026-09-20T12:0{i}:00Z'}
        for i,status in enumerate(('investigating','identified','monitoring','resolved'))]}]}


def test_status_lifecycle_replay_and_revision(contract):
    src=source('statuspage','incidents');data=payload()
    items=parse_entries(src,json.dumps(data).encode())
    assert len(items)==4
    assert {incident_identity(x['id']) for x in items}=={'incident1'}
    assert len({x['id'] for x in items})==4
    assert items==parse_entries(src,json.dumps(data).encode())
    data['incidents'][0]['incident_updates'][0]['body']='Corrected investigating description'
    assert {x['id'] for x in items}!={x['id'] for x in parse_entries(src,json.dumps(data).encode())}
    for item in items:contract.validate(normalize(item,src,str(uuid4()),datetime.now(timezone.utc)))


def test_status_storage_restart_dedup_and_malformed_audit(contract):
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);sessions=sessionmaker(engine)
    src=source('statuspage','incidents');now=datetime.now(timezone.utc)
    fetched=FetchResult(json.dumps(payload()).encode(),now,'application/json')
    assert Ingestor(sessions,contract).process(src,fetched)['created']==4
    assert Ingestor(sessions,contract).process(src,fetched)['duplicates']==4
    edited=payload();edited['incidents'][0]['incident_updates'][0]['status']='identified'
    assert Ingestor(sessions,contract).process(src,FetchResult(json.dumps(edited).encode(),now,'application/json'))['created']==1
    assert Ingestor(sessions,contract).process(src,FetchResult(b'<html>403</html>',now,'text/html'))['failed']==1
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawPayload))==4
        assert db.scalar(select(func.count()).select_from(NewsItem))==5
        assert db.scalar(select(func.count()).select_from(FailedItem))==1


def test_binance_promotional_hint():
    src=source('announcement_page','binance')
    data={'code':'000000','data':{'catalogs':[{'articles':[{'code':'abc','title':'Earn rewards in trading competition','releaseDate':1750000000000}]}]}}
    parsed=parse_entries(src,json.dumps(data).encode())
    assert parsed[0]['_categories']==['content_hint:promotional']
    with pytest.raises(SourceParseError):parse_entries(src,b'{"code":"403"}')


def test_filings_company_specific_and_no_invented_body():
    src=source('sec_filing',corporate={'cik':'1050446','issuer':'Strategy'})
    data={'cik':'1050446','filings':{'recent':{'form':['8-K'],'accessionNumber':['0001193125-26-389858'],'primaryDocument':['mstr.htm'],'filingDate':['2026-09-14'],'acceptanceDateTime':['2026-09-14T12:00:00Z']}}}
    item=parse_entries(src,json.dumps(data).encode())[0]
    assert item['summary']==''
    assert item['link']=='https://www.sec.gov/Archives/edgar/data/1050446/000119312526389858/mstr.htm'
    data['cik']='1'
    with pytest.raises(SourceParseError):parse_entries(src,json.dumps(data).encode())


@pytest.mark.parametrize('fmt',['coinbase','circle'])
def test_changed_layout_not_silent_empty(fmt):
    with pytest.raises(SourceParseError):parse_entries(source('announcement_page',fmt),b'<html>Changed template</html>')


def test_circle_article_title_date_and_summary():
    src=source('announcement_page','circle')
    data=b'<a class="press-link w-inline-block" href="/pressroom/arc"><p>September 16, 2026</p><p fs-list-field="title">Circle Launches Arc</p><p fs-list-field="description">100 builders</p></a>'
    item=parse_entries(src,data)[0]
    assert item['title']=='Circle Launches Arc'
    assert item['published_parsed'][:3]==(2026,9,16)
    assert 'publication_precision:day' in item['_categories']

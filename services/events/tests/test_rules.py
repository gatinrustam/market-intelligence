import copy
import re
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.taxonomy.configuration import Bundle,Taxonomy,Rule,load_bundle
from app.extraction.quality import quality_gate
from app.extraction.time import extract_title_time
from app.correlation.policy import exact_key,jaccard


@pytest.mark.parametrize('source,title,url,expected,rule',[
 ('fed_monetary_policy','Federal Reserve issues FOMC statement','','central_bank.policy_statement','fed.fomc_statement'),
 ('fed_monetary_policy','Minutes of the Federal Open Market Committee, June 16-17, 2026','','central_bank.minutes','fed.minutes'),
 ('fed_monetary_policy','Federal Reserve releases economic projections','','central_bank.projections','fed.projections'),
 ('ecb_press','Christine Lagarde: Interview with Ouest-France','/press/key/test','central_bank.interview','ecb.interview'),
 ('ecb_press','Conversation','/press/inter/test','central_bank.interview','ecb.interview'),
 ('ecb_press','Philip R. Lane: Diversity','/press/key/test.pdf','central_bank.speech','ecb.speech'),
 ('ecb_press','ECB wage tracker results','','central_bank.data_release','ecb.wage_tracker'),
 ('ecb_press','Monetary policy decisions','','central_bank.policy_statement','ecb.policy_statement'),
 ('sec_press_releases','SEC Proposes a rule','','regulator.rule_proposal','sec.rule_proposal'),
 ('sec_press_releases','SEC Adopts Rule','','regulator.rule_adoption','sec.rule_adoption'),
 ('sec_press_releases','SEC issues Final Rule','','regulator.rule_adoption','sec.rule_adoption'),
 ('sec_press_releases','SEC Updates FAQs','','regulator.guidance','sec.guidance'),
 ('sec_press_releases','SEC Guidance on filings','','regulator.guidance','sec.guidance'),
 ('sec_press_releases','SEC Charges executives','','regulator.enforcement','sec.enforcement'),
 ('sec_press_releases','SEC Enforcement action','','regulator.enforcement','sec.enforcement'),
 ('sec_press_releases','SEC Settles action','','regulator.enforcement','sec.enforcement'),
 ('sec_press_releases','SEC Announces Meeting','','regulator.meeting','sec.meeting'),
 ('sec_press_releases','SEC Announces Roundtable','','regulator.meeting','sec.meeting'),
 ('sec_press_releases','SEC Report released','','regulator.report','sec.report'),
 ('sec_press_releases','SEC Announces Departure','','regulator.personnel','sec.personnel'),
 ('sec_press_releases','SEC Appoints director','','regulator.personnel','sec.personnel'),
 ('sec_press_releases','SEC Names chair','','regulator.personnel','sec.personnel'),
 ('sec_press_releases','A different notification','','regulator.other','fallback.sec_press_releases'),
 ('ecb_press','A different notification','','central_bank.other','fallback.ecb_press'),
 ('unknown_source','A different notification','','unknown','fallback.unknown')])
def test_patterns(extractor,document,source,title,url,expected,rule):
 document['source'].update(id=source,url='https://example.org'+url)
 document['content']['title']=title
 candidates=extractor.extract(document)
 assert len(candidates)==1 and candidates[0].event_type==expected
 assert candidates[0].matched_rule_ids==[rule]
 assert 'confidence' not in candidates[0].model_dump()


@pytest.mark.parametrize('source,actor,jurisdiction',[('fed_monetary_policy','organization:federal_reserve','US'),('sec_press_releases','organization:sec','US'),('ecb_press','organization:ecb','EU')])
def test_issuer(extractor,document,source,actor,jurisdiction):
 document['source']['id']=source
 c=extractor.extract(document)[0]
 assert c.actors[0].entity_id==actor and c.jurisdictions==[jurisdiction]


def test_unresolved_speaker(extractor,document):
 document['source']['id']='ecb_press';document['content']['title']='Christine Lagarde: Interview with a newspaper'
 actor=extractor.extract(document)[0].actors[1]
 assert actor.entity_id is None and actor.resolution=='unresolved' and actor.name=='Christine Lagarde'


@pytest.mark.parametrize('status,title,body,quality,usable',[
 ('ready','Useful title','Detailed body. '*100,'high',True),
 ('partial','Useful title','Shorter but meaningful original body. '*4,'medium',True),
 ('partial','Useful title','Useful title','low',True),
 ('failed','Useful title','','low',True),
 ('rejected','Useful title','','low',True),
 ('failed','   ','  ','low',False),
 ('ready',' ','Meaningful body without title. '*30,'high',True)])
def test_quality(bundle,extractor,document,status,title,body,quality,usable):
 document['enrichment']['status']=status;document['content'].update(title=title,body=body)
 result=quality_gate(document,bundle.sources.quality)
 assert (result.quality,result.usable)==(quality,usable)
 assert bool(extractor.extract(document))==usable
 if not title.strip() and usable:
  assert extractor.extract(document)[0].canonical_title==''


@pytest.mark.parametrize('title,value,precision',[
 ('FOMC statement April 29, 2026','2026-04-29','date'),
 ('Minutes June 16–17, 2026','2026-06-16/2026-06-17','date_range'),
 ('Meeting 2026-06-17','2026-06-17','date'),
 ('February 30, 2026',None,'unknown'),
 ('April 29',None,'unknown'),
 ('April 29, 2026 and June 17, 2026',None,'unknown'),
 ('September 16-15, 2026',None,'unknown'),
 ('No date here',None,'unknown')])
def test_time(title,value,precision):
 assert extract_title_time(title)[:2]==(value,precision)


def test_publication_not_event_time(extractor,document):
 c=extractor.extract(document)[0]
 assert c.event_time is None and c.exact_event_key is None


def test_date_and_type_separate_identity():
 a=exact_key('central_bank.policy_statement','organization:federal_reserve','2026-04-29','date','fomc.meeting')
 b=exact_key('central_bank.policy_statement','organization:federal_reserve','2026-06-17','date','fomc.meeting')
 c=exact_key('central_bank.projections','organization:federal_reserve','2026-06-17','date','fomc.meeting')
 assert len({a,b,c})==3
 assert exact_key('x','y',None,'unknown','z') is None
 assert exact_key('x','y','2026-06-17','date',None) is None


@pytest.mark.parametrize('mutation',[
 lambda d:d['taxonomy'].pop('version'),lambda d:d['taxonomy']['event_types'].append('bad type'),
 lambda d:d['taxonomy']['topics'].append(d['taxonomy']['topics'][0]),
 lambda d:d['rules']['rules'][0].update(event_type='fake.type'),
 lambda d:d['rules']['rules'][0].update(topics=['bullish']),
 lambda d:d['rules']['rules'][0].update(source_id=['not_configured']),
 lambda d:d['rules']['rules'][0].update(title_regex=['[']),
 lambda d:d['rules']['rules'].append(d['rules']['rules'][0]),
 lambda d:d['sources']['sources']['fed_monetary_policy'].update(issuer='organization:fake'),
 lambda d:d['sources']['sources']['fed_monetary_policy'].update(jurisdictions=['ZZ']),
 lambda d:d['registry'].pop('version'),
 lambda d:d['rules']['rules'][0].update(confidence=.93)])
def test_bad_configuration(bundle,mutation):
 data=bundle.model_dump();mutation(data)
 with pytest.raises((ValidationError,ValueError,re.error)):
  Bundle.model_validate(data)


def test_configuration_fingerprint(bundle,settings):
 assert bundle.fingerprint()==load_bundle(settings.config_dir).fingerprint()
 changed=bundle.model_copy(deep=True);changed.sources.quality.high_body_characters+=1
 assert changed.fingerprint()!=bundle.fingerprint()


def test_topics_not_single_body_keyword(extractor,document):
 document['content']['body']='bitcoin inflation wages employment '*30
 assert extractor.extract(document)[0].topics==['monetary_policy','interest_rates']


def test_structural_fixtures_valid(input_contract):
 for p in (Path(__file__).parent/'fixtures').glob('*.json'):
  input_contract.validate(json.loads(p.read_text()))

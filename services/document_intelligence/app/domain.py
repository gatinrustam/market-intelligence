import hashlib,json
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def uid(*parts):return str(uuid5(NAMESPACE_URL,'document.intelligence:'+':'.join(map(str,parts))))
def iso(value):return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def now():return datetime.now(timezone.utc)
def load_configuration(settings):
    rules=json.loads(settings.rules_path.read_text());registry=json.loads((settings.config_dir/rules['registry_file']).read_text())
    if rules['pipeline_version']!='1.0':raise ValueError('unsupported pipeline version')
    if any(r['fact_type'] not in rules['taxonomy'] or not set(r['topics'])<=set(rules['topics']) for r in rules['rules']):raise ValueError('invalid taxonomy')
    return {'pipeline_version':rules['pipeline_version'],'rules':rules,'registry':registry,'models':{'en':'en_core_web_sm-3.8.0','ru':'ru_core_news_sm-3.8.0'},'spacy_version':'3.8.14','language_detector':'langdetect-1.0.9-seed0-rules1', 'language_profiles':json.loads((settings.config_dir/'languages.v1.json').read_text())}
def version_key(c):return '/'.join((c['pipeline_version'],c['rules']['version'],c['registry']['version']))
def identity(doc,c):return uid(doc['document_id'],version_key(c))

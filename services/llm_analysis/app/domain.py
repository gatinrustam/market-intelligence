import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
from jsonschema import Draft202012Validator,FormatChecker
UTC=timezone.utc
HORIZONS=[60,300,900,3600]
def now():return datetime.now(UTC)
def iso(t):return t.astimezone(UTC).isoformat().replace('+00:00','Z')
def parse(s):
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('timezone required')
    return t.astimezone(UTC)
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def identity(event,config,basis,run_key='live'):
    # Live identity intentionally excludes effort/output limit; changing those requires an explicit research run.
    parts=[event,'BTCUSDT',config['provider'],config['model'],config['prompt_version'],basis,run_key]
    if config.get('intelligence_id'):parts.append(config['intelligence_id'])
    return str(uuid5(NAMESPACE_URL,canonical(parts)))
def prompt(version):
    root=Path(__file__).parent/'prompts';manifest=json.loads((root/'manifest.json').read_text())
    names=[version+'.txt',version+'.schema.json']
    if any(n not in manifest for n in names):raise ValueError('unknown prompt version')
    for name in names:
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=manifest[name]:raise ValueError('prompt version modified')
    return (root/names[0]).read_text(),json.loads((root/names[1]).read_text()),manifest[names[0]]
def validate_output(value,schema):
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)
    if [p['horizon_seconds'] for p in value['forecast']]!=HORIZONS:raise ValueError('invalid horizons')
def normalize(job,input_row,output):
    package=json.loads(input_row.canonical_json)
    return {'schema_version':'1.0','message_id':job.id,'analysis_id':job.id,'event':package['event_identity'],
        'decision':{k:package['decision'][k] for k in ('decision_at','decision_basis','historical_simulation')},
        'asset':{'symbol':'BTCUSDT','relevance':output['relevance']},
        **{k:output[k] for k in ('interpretation','forecast','uncertainties','unavailable_data')},
        'confidence_basis':'model_reported_not_calibrated','audit':{k:job.configuration[k] for k in ('provider','model','prompt_version','reasoning_effort')}|{'input_hash':input_row.id}}

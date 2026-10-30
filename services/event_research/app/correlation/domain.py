"""Conservative, explainable identity. Publication is never an identity field."""
import copy
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from app.di_schema import Strict
from app.domain import canonical, digest, uid
from app.schema import Output

FIELDS = {'event_type', 'primary_actor', 'action', 'object', 'measurements', 'explicit_event_time', 'jurisdiction', 'topics'}

class ExactRule(Strict):
    fact_types: list[str] = Field(min_length=1)
    required: list[str] = Field(min_length=5)
    measurement_kinds: list[str] = Field(min_length=1)
    allowed_actions: list[str] = Field(min_length=1)

class Policy(Strict):
    ruleset_version: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,32}$')
    fingerprint_version: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,32}$')
    input_ruleset_version: str
    exact_rules: dict[str, ExactRule]
    suggestion_required: list[str]
    title_similarity_threshold: float = Field(ge=0, le=1)
    publication_proximity_seconds: int = Field(ge=0)

    @model_validator(mode='after')
    def safe_identity(self):
        minimum = {'event_type', 'primary_actor', 'action', 'measurements', 'explicit_event_time'}
        for rule in self.exact_rules.values():
            if not minimum <= set(rule.required) <= FIELDS:
                raise ValueError('Exact identity must include fact actor/action/value/explicit time')
        if set(self.suggestion_required) != {'event_type', 'primary_actor', 'action', 'measurements'}:
            raise ValueError('Suggestions require linked facts, not title/proximity alone')
        return self

def load_policy(path):
    return Policy.model_validate_json(Path(path).read_text()).model_dump()

def scope(policy):
    return uid('correlation.research', policy['ruleset_version'], policy['fingerprint_version'], policy['input_ruleset_version'])

def projection(result, snapshot):
    """Select structured, fact-linked fields only; never forward DI/raw document body."""
    Output.model_validate(result)
    di = snapshot['intelligence']
    meta = snapshot['metadata']
    if digest(di) != result['basis']['input_hash'] or di['intelligence_id'] != result['document']['intelligence_id']:
        raise ValueError('DI input identity mismatch')
    if any(meta[k] != result['document'][k] for k in ('document_id', 'input_message_id', 'body_hash')):
        raise ValueError('Document metadata mismatch')
    facts = {f['fact_id']: f for f in di['facts']}
    relations = {r['relation_id']: r for r in di['relations']}
    entities = {e['mention_id']: e for e in di['entities']}
    rows = []
    for candidate in result['candidates']:
        semantics = []
        for key in candidate['primary_fact_ids'] + candidate['supporting_fact_ids']:
            fact = facts[key]; relation = relations[fact['relation_id']]
            entity = entities[fact['subject']['mention_id']]
            obj = relation['object']; obj_entity = entities.get(obj['mention_id'])
            semantics.append({'fact_id': key, 'fact_type': fact['fact_type'],
                'primary_actor': entity['entity_id'] if entity['registry'] else None,
                'action': fact['action'] if relation['modality'] == 'asserted' else None,
                'object': obj_entity['entity_id'] if obj_entity and obj_entity['registry'] else None,
                'relation': copy.deepcopy(relation)})
        rows.append({'candidate': copy.deepcopy(candidate), 'facts': semantics,
            'document': copy.deepcopy(result['document']),
            'metadata': {k: copy.deepcopy(meta[k]) for k in ('source', 'title', 'published_at')},
            'research_id': result['research_id'], 'input_ruleset_version': result['basis']['ruleset_version'],
            'input_hash': digest(result), 'extraction': copy.deepcopy(result['basis']['extraction']),
            'v1_event_ids': sorted({e['event']['id'] for e in snapshot['v1_events']})})
    return rows

def number(value, factor=Decimal(1)):
    if value is None:
        return None
    d = Decimal(str(value)) * factor
    if not d.is_finite():
        raise ValueError('Nonfinite measurement')
    return format(d.normalize(), 'f')

def measurement(m):
    kind, unit = m['kind'], m['unit'].strip().lower()
    # Rate levels and changes remain separate dimensions even when numbers coincide.
    if kind in ('rate', 'percentage') and unit in ('%', 'percent', 'percentage', 'fraction', 'ratio', 'bp', 'bps', 'basis_points', 'basis points'):
        factor = Decimal(100) if unit in ('fraction', 'ratio') else Decimal('.01') if unit in ('bp', 'bps', 'basis_points', 'basis points') else Decimal(1)
        kind, unit = 'rate_level' if kind == 'rate' else 'percentage', 'percent'
    elif kind in ('basis_points', 'percentage_points') and unit in ('bp', 'bps', 'basis_points', 'basis points', 'percentage_points', 'percentage points', 'pp'):
        factor = Decimal('.01') if unit in ('bp', 'bps', 'basis_points', 'basis points') else Decimal(1)
        kind, unit = 'rate_change', 'percentage_points'
    elif kind in ('money', 'price', 'quantity', 'ratio') and unit:
        factor = Decimal(1)
    else:
        raise ValueError('Unsupported measurement unit')
    values = [number(m.get(k), factor) for k in ('value', 'min', 'max')]
    if values[0] is None and (values[1] is None or values[2] is None):
        raise ValueError('Incomplete measurement')
    if values[1] is not None and values[2] is not None and Decimal(values[1]) > Decimal(values[2]):
        raise ValueError('Inverted range')
    return {'kind': kind, 'unit': unit, 'currency': m.get('currency'), **dict(zip(('value', 'min', 'max'), values))}

def instant(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Unzoned time')
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def fingerprint(row, policy):
    c = row['candidate']; facts = row['facts']; issues = []
    def unique(field):
        values = {f[field] for f in facts if f.get(field)}
        if len(values) > 1:
            issues.append('ambiguous_' + field)
        return next(iter(values)) if len(values) == 1 and all(f.get(field) for f in facts) else None
    values = []; invalid = False
    for linked in c['measurements']:
        if not set(linked['fact_ids']) <= {f['fact_id'] for f in facts}:
            raise ValueError('Unlinked measurement')
        try:
            values.append(measurement(linked['measurement']))
        except (ValueError, InvalidOperation):
            invalid = True
    if invalid:
        issues.append('unsupported_measurement')
    values = [v for _, v in sorted({canonical(v): v for v in values}.items())]
    explicit_dates = sorted({d['date']['normalized'][:10] for d in c['dates']
        if d['date']['kind'] == 'date' and d['date']['normalized']
        and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T.*)?', d['date']['normalized'])})
    event_time = instant(c['event_time']) if c['event_time_basis'] == 'explicit_fact_datetime' else None
    components = {'event_type': c['event_type'], 'primary_actor': unique('primary_actor'),
        'action': unique('action'), 'object': unique('object'), 'measurements': values,
        'explicit_event_time': event_time, 'explicit_dates': explicit_dates, 'jurisdiction': None, 'topics': sorted(set(c['topics']))}
    rule = policy['exact_rules'].get(c['event_type'])
    eligible = bool(rule and facts and c['classification_basis'] == 'primary_fact' and not issues)
    if event_time and explicit_dates and explicit_dates != [event_time[:10]]:
        issues.append('conflicting_linked_dates')
        eligible = False
    if len(explicit_dates) > 1:
        issues.append('ambiguous_linked_dates')
        eligible = False
    if rule:
        eligible = eligible and all(components[f] for f in rule['required'])
        eligible = eligible and all(f['fact_type'] in rule['fact_types'] for f in facts)
        eligible = eligible and components['action'] in rule['allowed_actions']
        eligible = eligible and any(m['measurement']['kind'] in rule['measurement_kinds'] for m in c['measurements'])
    identity = {k: components[k] for k in rule['required']} if eligible else None
    # Guard fields participate too: no group can bypass a pairwise conflict via transitivity.
    guard = {k: components[k] for k in ('event_type', 'primary_actor', 'action', 'object', 'measurements', 'explicit_event_time', 'explicit_dates', 'jurisdiction')}
    return {'version': policy['fingerprint_version'], 'ruleset_version': policy['ruleset_version'],
        'hash': digest({'version': policy['fingerprint_version'], 'components': components}),
        'components': components, 'exact_key': digest({'identity': identity, 'guard': guard}) if eligible else None,
        'missing_identity_fields': [k for k in (rule['required'] if rule else []) if not components[k]],
        'issues': issues, 'exact_rule_configured': rule is not None}

def correlate(a, b, fa, fb, policy):
    x, y = fa['components'], fb['components']; matched = []; conflicts = []
    for k in ('event_type', 'primary_actor', 'action', 'object', 'measurements', 'explicit_event_time', 'explicit_dates', 'jurisdiction'):
        if x[k] and y[k]:
            (matched if x[k] == y[k] else conflicts).append(k)
    topics_a, topics_b = set(x['topics']), set(y['topics'])
    tokens_a = set(re.findall(r'\w+', a['metadata']['title'].casefold()))
    tokens_b = set(re.findall(r'\w+', b['metadata']['title'].casefold()))
    title_similarity = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a | tokens_b else 0
    pub_a, pub_b = instant(a['metadata']['published_at']), instant(b['metadata']['published_at'])
    distance = abs((datetime.fromisoformat(pub_a) - datetime.fromisoformat(pub_b)).total_seconds()) if pub_a and pub_b else None
    features = {'same_event_type': x['event_type'] == y['event_type'],
        'same_primary_actor': 'primary_actor' in matched, 'same_action': 'action' in matched,
        'measurement_similarity': 'equal' if 'measurements' in matched else 'conflict' if 'measurements' in conflicts else 'unknown',
        'date_similarity': 'equal' if 'explicit_event_time' in matched else 'conflict' if 'explicit_event_time' in conflicts else 'unknown',
        'topic_overlap': sorted(topics_a & topics_b), 'title_similarity': round(title_similarity, 6),
        'title_similarity_support': title_similarity >= policy['title_similarity_threshold'],
        'publication_distance_seconds': distance,
        'publication_proximity': distance is not None and distance <= policy['publication_proximity_seconds']}
    if conflicts:
        mode, reason = 'separate', 'Material identity conflict; title/proximity cannot override it'
    elif fa['exact_key'] and fa['exact_key'] == fb['exact_key']:
        mode, reason = 'exact_match', 'All configured fact identity and guard fields agree'
    elif not fa['issues'] and not fb['issues'] and all(k in matched for k in policy['suggestion_required']):
        mode, reason = 'suggestion', 'Linked actor/action/measurements agree; complete exact identity is unavailable'
    else:
        mode, reason = 'insufficient_data', 'Not enough linked fact identity; actor/title/publication alone are insufficient'
    return {'mode': mode, 'auto_merge': mode == 'exact_match', 'reason': reason,
        'candidate_a': a['candidate']['candidate_id'], 'candidate_b': b['candidate']['candidate_id'],
        'document_ids': sorted({a['document']['document_id'], b['document']['document_id']}),
        'fingerprint_version': policy['fingerprint_version'], 'ruleset_version': policy['ruleset_version'],
        'fingerprints': [fa['hash'], fb['hash']], 'matched_fields': matched, 'conflicting_fields': conflicts,
        'features': features, 'v1_same_event': bool(set(a['v1_event_ids']) & set(b['v1_event_ids']))}

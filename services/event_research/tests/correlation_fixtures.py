"""Synthetic structured candidates: invented evidence, never mixed with real corpus."""
from app.domain import uid, digest

def rate(name, source='fed', title='Fed holds target rate at 3.50–3.75%', date='2026-09-20T18:00:00Z'):
    doc = uid('synthetic.document', name); fid = uid(doc, 'fact'); rid = uid(doc, 'relation')
    evidence = {'document_id': doc, 'sentence_id': 0, 'start_char': 0, 'end_char': len(title), 'text': title}
    extraction = {'method': 'rule_based', 'extractor': 'synthetic', 'rule_id': 'fixture', 'extractor_version': '1.0'}
    measurement = {'measurement_id': uid(doc, 'rate'), 'kind': 'rate', 'value': None, 'min': '3.50', 'max': '3.75',
        'unit': 'percent', 'currency': None, 'evidence': evidence, 'extraction': extraction}
    actor = {'entity_id': 'organization:federal_reserve', 'mention_id': uid(doc, 'actor'), 'name': 'Federal Reserve', 'entity_type': 'organization', 'resolution': 'canonical'}
    c = {'candidate_id': uid(doc, 'candidate'), 'document_id': doc, 'event_type': 'central_bank.policy_statement',
        'primary_fact_ids': [fid], 'supporting_fact_ids': [],
        'fact_references': [{'document_id': doc, 'fact_id': fid, 'fact_type': 'monetary_policy.rate_decision', 'relation_id': rid, 'evidence': evidence, 'extraction': extraction}],
        'actors': [actor], 'topics': ['interest_rates'], 'measurements': [{'fact_ids': [fid], 'measurement': measurement}],
        'dates': [], 'event_time': date, 'event_time_basis': 'explicit_fact_datetime' if date else 'unavailable',
        'classification_basis': 'primary_fact', 'signals': []}
    return {'candidate': c, 'facts': [{'fact_id': fid, 'fact_type': 'monetary_policy.rate_decision',
        'primary_actor': actor['entity_id'], 'action': 'hold', 'object': None, 'relation': {'relation_id': rid}}],
        'document': {'document_id': doc, 'input_message_id': uid(doc, 'input'), 'intelligence_id': uid(doc, 'di'), 'source_message_id': uid(doc, 'source'), 'body_hash': digest(title)},
        'metadata': {'source': {'id': source, 'url': 'https://example.invalid/'+name}, 'title': title, 'published_at': '2026-09-20T18:01:00Z'},
        'research_id': uid(doc, 'research'), 'input_ruleset_version': '2.0', 'input_hash': digest(c), 'extraction': {'synthetic': True}, 'v1_event_ids': [uid('v1', name)]}

def corpus():
    a = rate('same-a'); b = rate('same-b', 'wire', 'US central bank leaves its policy range unchanged'); c = rate('same-c', 'fed', 'FOMC maintains federal funds target')
    different = rate('different-value'); different['candidate']['measurements'][0]['measurement'].update(min='4.25', max='4.50')
    projections = rate('projections'); projections['candidate']['event_type'] = 'central_bank.projections'
    proposal = rate('proposal'); proposal['candidate']['event_type'] = 'regulator.rule_proposal'; proposal['facts'][0].update(primary_actor='organization:sec',action='propose',fact_type='regulation.rule_proposal')
    enforcement = rate('enforcement'); enforcement['candidate']['event_type'] = 'regulator.enforcement'; enforcement['facts'][0].update(primary_actor='organization:sec',action='charge',fact_type='regulation.enforcement')
    return {'same_event': [a,b,c], 'different_values': [rate('values-a'),different],
        'same_meeting_different_types': [rate('policy'),projections], 'sec_different_actions': [proposal,enforcement],
        'missing_date': [rate('missing-a',date=None),rate('missing-b',date=None)]}

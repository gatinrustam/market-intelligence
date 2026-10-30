import copy
from pathlib import Path

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as ConfigError

from app.config import Policies, SourcePolicy, load_policies
from app.extraction.extractors import extract_document
from app.normalization.document import build_document
from app.normalization.text import normalize_text, content_hash
from app.policies.sufficiency import EnrichmentPolicy


@pytest.mark.parametrize('body,reason', [('', 'rss_body_empty'), (' Original SOURCE title ', 'rss_body_equals_title'),
    ('tiny', 'rss_body_short'), ('Long useful text. '*30+'…', 'rss_body_truncated'), ('Long useful text. '*30+'...', 'rss_body_truncated')])
def test_insufficient(event, policy, body, reason):
    event['content']['body'] = body
    decision = EnrichmentPolicy(policy).evaluate(event)
    assert decision.required and decision.reason == reason


def test_sufficient_modes(event, policy):
    event['content']['body'] = 'This is useful source content. '*30
    decision = EnrichmentPolicy(policy).evaluate(event)
    assert not decision.required and decision.sufficient
    assert EnrichmentPolicy(policy.model_copy(update={'mode': 'always'})).evaluate(event).required
    event['content']['body'] = ''
    decision = EnrichmentPolicy(policy.model_copy(update={'mode': 'never'})).evaluate(event)
    assert not decision.required and not decision.sufficient


def test_html_boilerplate_removed(html_bytes, extraction_context):
    result = extract_document(html_bytes, extraction_context)
    assert result.status == 'success' and result.method == 'trafilatura'
    assert 'committee' in result.text and '\n' in result.text
    for noise in ('HOME NAVIGATION', 'FOOTER COOKIE', 'secret_script_payload'):
        assert noise not in result.text
    assert result.extracted_title


def test_plain_text_charset(extraction_context):
    context = extraction_context | {'content_type': 'text/plain', 'content_type_header': 'text/plain; charset=iso-8859-1'}
    result = extract_document(('café policy statement. '*20).encode('latin1'), context)
    assert result.status == 'success' and 'café' in result.text


def test_pdf(pdf_bytes, extraction_context):
    result = extract_document(pdf_bytes, extraction_context | {'content_type': 'application/pdf'})
    assert result.status == 'success' and result.method == 'pypdf' and 'committee' in result.text


def test_invalid_pdf(extraction_context):
    result = extract_document(b'%PDF-this is not a PDF', extraction_context | {'content_type': 'application/pdf'})
    assert result.status == 'failed' and result.reason == 'invalid_pdf'


def test_empty_pdf(extraction_context):
    data = (Path(__file__).parent/'fixtures/empty.pdf').read_bytes()
    result = extract_document(data, extraction_context | {'content_type': 'application/pdf'})
    assert result.status == 'text_unavailable'


def test_pdf_page_limit(pdf_bytes, extraction_context):
    result = extract_document(pdf_bytes, extraction_context | {'content_type': 'application/pdf', 'max_pdf_pages': 0})
    assert result.status == 'rejected'


def test_unsupported(extraction_context):
    assert extract_document(b'zip', extraction_context | {'content_type': 'application/zip'}).status == 'unsupported'


def test_integrity_and_paragraphs():
    body = normalize_text('  cafe\u0301  \r\n\r\nAnother   paragraph. ')
    assert body == 'café\n\nAnother paragraph.'
    assert content_hash('Title', body, 'en') == content_hash('Title', 'café\n\nAnother paragraph.', 'en')
    assert content_hash('Title', body+'!', 'en') != content_hash('Title', body, 'en')


def test_contract_and_lineage(event, policy, output_contract):
    event['content']['body'] = 'Sufficient body. '*30
    document = build_document(event, EnrichmentPolicy(policy).evaluate(event))
    output_contract.validate(document)
    assert document['content']['title'] == event['content']['title']
    assert document['classification'] == event['classification']
    assert document['timestamps']['ingestion_delay_seconds'] == 261 * 86400
    assert document['lineage']['input_content_hash'] == 'a'*64
    assert document['enrichment']['status'] == 'ready'
    other = build_document(event, EnrichmentPolicy(policy).evaluate(event))
    assert document['message_id'] != other['message_id'] and document['integrity'] == other['integrity']
    bad = copy.deepcopy(document)
    bad['enrichment']['status'] = 'bullish'
    with pytest.raises(ValidationError): output_contract.validate(bad)
    del bad['lineage']
    with pytest.raises(ValidationError): output_contract.validate(bad)


def test_unknown_published_date(event, policy, output_contract):
    event['timestamps']['published_at'] = None
    result = build_document(event, EnrichmentPolicy(policy).evaluate(event))
    output_contract.validate(result)
    assert result['timestamps']['ingestion_delay_seconds'] is None


@pytest.mark.parametrize('hosts', [['*.example.org'], ['http://example.org'], ['db'], ['user:secret@example.org']])
def test_invalid_allowlist(hosts):
    with pytest.raises(ConfigError): SourcePolicy(allowed_hosts=hosts)


def test_policy_configuration(settings):
    policies = load_policies(settings.policy_path).sources
    assert len(policies) == 6
    for source, hosts in {'cbr_events_ru': {'cbr.ru', 'www.cbr.ru'}, 'cbr_press_ru': {'cbr.ru', 'www.cbr.ru'}, 'moex_news_ru': {'moex.com', 'www.moex.com'}}.items():
        assert policies[source].mode == 'when_needed'
        assert set(policies[source].allowed_hosts) == hosts
    with pytest.raises(ConfigError): SourcePolicy(mode='maybe', allowed_hosts=['example.org'])

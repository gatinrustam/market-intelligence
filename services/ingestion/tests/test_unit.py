import copy
from pathlib import Path
from uuid import uuid4

import feedparser
import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as ConfigError

from app.config import load_sources, SourceConfig
from app.normalization.rss import normalize, content_hash, clean


def test_rss_normalization(source, feed, contract):
    event = normalize(feedparser.parse(feed.body).entries[0], source, str(uuid4()), feed.received_at)
    contract.validate(event)
    assert event['content'] == {'title': 'Policy update', 'body': 'Rates & outlook.', 'language': 'en'}
    assert event['timestamps']['published_at'] == '2026-09-18T12:30:00+00:00'
    assert event['source']['external_id'] == 'release-1'


def test_missing_dates_ids_links(source, feed, contract):
    event = normalize({'title': 'No metadata'}, source, str(uuid4()), feed.received_at)
    contract.validate(event)
    assert event['timestamps']['published_at'] is None
    assert event['source']['external_id'] is None
    assert event['url'] is None


def test_deterministic_hash(source, feed):
    entry = feedparser.parse(feed.body).entries[0]
    a = normalize(entry, source, str(uuid4()), feed.received_at)
    b = normalize(entry, source, str(uuid4()), feed.received_at)
    assert a['message_id'] != b['message_id']
    assert a['integrity'] == b['integrity']
    assert content_hash({'body': 'x', 'title': 'y'}) == content_hash({'title': 'y', 'body': 'x'})
    assert clean('<p>cafe\u0301</p><script>secret</script>') == 'café'
    assert clean(' A\n B ') == clean('A B')
    assert clean('Monetary policy statement (with Q&A)') == 'Monetary policy statement (with Q&A)'
    b['content']['body'] += '!'
    assert content_hash(a['content']) != content_hash(b['content'])


@pytest.mark.parametrize('field,value', [('message_id', 'bad'), ('schema_version', '2.0'), ('url','file:///etc/passwd'), ('url', 'https://example.org/invalid space'), ('url', 'https://')])
def test_schema_rejects_invalid(source, feed, contract, field, value):
    event = normalize({'title': 'Valid'}, source, str(uuid4()), feed.received_at)
    event[field] = value
    with pytest.raises(ValidationError):
        contract.validate(event)


def test_schema_nested_extra_and_invalid_timestamp(source, feed, contract):
    event = normalize({'title': 'Valid'}, source, str(uuid4()), feed.received_at)
    invalid = copy.deepcopy(event)
    invalid['content']['secret'] = 'oops'
    with pytest.raises(ValidationError):
        contract.validate(invalid)
    event['timestamps']['received_at'] = 'yesterday'
    with pytest.raises(ValidationError):
        contract.validate(event)


@pytest.mark.parametrize('change', [
    {'poll': {'interval_seconds': 0}}, {'connector': {'type': 'unknown', 'url': 'https://example.org'}},
    {'id': 'BAD ID'}, {'typo': True}, {'connector': {'type': 'rss', 'url': 'https://user:password@example.org'}}])
def test_invalid_source(source, change):
    with pytest.raises(ConfigError):
        SourceConfig.model_validate(source.model_dump() | change)


def test_config_loading(tmp_path):
    with pytest.raises(ValueError, match='No source'):
        load_sources(tmp_path)
    path = tmp_path / 'a.yaml'
    path.write_text('id: test\nname: Test\nconnector:\n  type: rss\n  url: https://example.org/feed\n')
    assert load_sources(tmp_path)[0].id == 'test'
    (tmp_path / 'b.yaml').write_text(path.read_text())
    with pytest.raises(ValueError, match='Duplicate'):
        load_sources(tmp_path)
    (tmp_path / 'b.yaml').write_text('bad: [')
    with pytest.raises(ValueError, match='b.yaml'):
        load_sources(tmp_path)


def test_shipped_source_configs():
    sources = load_sources(Path(__file__).resolve().parents[3] / 'config/sources')
    assert len(sources) >= 3


def test_distinct_releases_same_text_and_relative_link(source, feed):
    first = normalize({'title': 'Rates unchanged', 'link': '/releases/1#top'}, source, str(uuid4()), feed.received_at)
    second = normalize({'title': 'Rates unchanged', 'link': '/releases/2'}, source, str(uuid4()), feed.received_at)
    assert first['url'] == 'https://example.org/releases/1'
    assert first['integrity'] != second['integrity']


def test_missing_format_validator_fails_startup(monkeypatch):
    from jsonschema import FormatChecker
    from app.normalization.contract import Contract
    monkeypatch.delitem(FormatChecker.checkers, 'uri')
    with pytest.raises(RuntimeError, match='format validators'):
        Contract(Path('unused.json'))


@pytest.mark.parametrize('code,key,expected', [
    (1062, 'uq_news_external', True), (1062, 'uq_news_content', True),
    (1062, 'unrelated_unique_key', False), (1452, 'foreign_key', False),
])
def test_dedup_only_suppresses_news_identity_conflicts(code, key, expected):
    from sqlalchemy.exc import IntegrityError
    from app.workers.ingest import duplicate_violation
    error = IntegrityError('insert', {}, Exception(code, f'constraint {key}'))
    assert duplicate_violation(error) is expected

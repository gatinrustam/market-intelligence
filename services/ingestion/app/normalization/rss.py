import calendar
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from uuid import uuid4
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.config import SourceConfig


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'li'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li'):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', ''.join(parser.parts))).strip()


def content_hash(content: dict, url=None, published_at=None) -> str:
    canonical = json.dumps({'content': content, 'url': url, 'published_at': published_at}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def normalize(entry, source: SourceConfig, payload_id: str, received_at: datetime) -> dict:
    title = clean(entry.get('title', ''))
    if not title:
        raise ValueError('missing title')
    body = clean(entry.get('content', [{}])[0].get('value', '') or entry.get('summary') or '')
    content = {'title': title, 'body': body, 'language': source.language}
    published = entry.get('published_parsed')
    # Missing or unparseable publication date is explicitly unknown, not receive time.
    published_at = datetime.fromtimestamp(calendar.timegm(published), timezone.utc).isoformat() if published else None
    link = urljoin(str(source.connector.url), entry['link']) if entry.get('link') else None
    if link:
        parts = urlsplit(link)
        link = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ''))
    return {
        'schema_version': '1.0', 'message_id': str(uuid4()),
        'source': {'id': source.id, 'type': source.connector.type,
                   'external_id': str(entry.get('id') or '').strip() or None},
        'timestamps': {'published_at': published_at, 'received_at': received_at.isoformat()},
        'content': content, 'classification': {'categories': list(dict.fromkeys(source.classification.categories + entry.get('_categories', [])))},
        'url': link,
        'integrity': {'content_hash': content_hash(content, link, published_at)}, 'raw': {'payload_id': payload_id},
    }

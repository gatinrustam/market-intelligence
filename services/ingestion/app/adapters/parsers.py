"""Official source formats -> internal normalization entries (not public contracts)."""
import hashlib
import json
import re
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser


class SourceParseError(ValueError):
    pass


def date(value):
    if not value:
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).utctimetuple()
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).utctimetuple()
    except ValueError:
        for fmt in ('%B %d, %Y', '%b %d, %Y'):
            try:
                return datetime.strptime(value, fmt).timetuple()
            except ValueError:
                pass
    raise ValueError('unrecognized source timestamp')


def entry(identity, title, body, link, published, categories=()):
    if not identity or not title or not link:
        raise ValueError('incomplete source item')
    return {'id': identity, 'title': escape(title), 'summary': escape(body), 'link': link,
            'published_parsed': date(published), '_categories': list(categories)}


def incident_identity(external_id):
    parts = (external_id or '').split('/')
    return parts[1] if len(parts) >= 4 and parts[0] == 'incident' and parts[2] == 'update' else None


def statuspage(source, payload):
    incidents = payload[source.connector.format]
    entries = []
    for incident in incidents:
        for update in incident['incident_updates']:
            # An edited update is a new observation, sharing immutable incident/update identity.
            revision = hashlib.sha256(json.dumps(update, sort_keys=True).encode()).hexdigest()[:16]
            identity = f"incident/{incident['id']}/update/{update['id']}/{revision}"
            entries.append(entry(identity, incident['name'], update['status'] + ': ' + update['body'],
                                 f"https://{source.connector.url.host}/incidents/{incident['id']}",
                                 update.get('display_at') or update['created_at'],
                                 ['incidents', 'lifecycle:' + update['status']]))
    return sorted(entries, key=lambda e: e['published_parsed'], reverse=True)


def filings(source, payload):
    corporate = source.connector.corporate
    if int(payload['cik']) != int(corporate.cik):
        raise ValueError('issuer identity mismatch')
    recent = payload['filings']['recent']
    fields = ('form', 'accessionNumber', 'primaryDocument', 'filingDate', 'acceptanceDateTime')
    if len({len(recent[k]) for k in fields}) != 1:
        raise ValueError('malformed filing arrays')
    entries = []
    for i, form in enumerate(recent['form']):
        if form not in corporate.forms:
            continue
        accession, document = recent['accessionNumber'][i], recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.\-]+', document):
            raise ValueError('invalid archive identifier')
        link = f"https://www.sec.gov/Archives/edgar/data/{int(corporate.cik)}/{accession.replace('-', '')}/{document}"
        # Metadata is not the filing text. Enrichment must fetch the actual evidence.
        entries.append(entry(accession, f"{corporate.issuer} — {form} — {recent['filingDate'][i]}", '', link,
                             recent['acceptanceDateTime'][i], ['filing_metadata_only']))
    return entries


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def text(self):
        if self.tag in ('script', 'style'):
            return ''
        return ' '.join(x.text() if isinstance(x, Node) else x for x in self.children)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def announcements(source, body):
    if source.connector.format == 'binance':
        payload = json.loads(body)
        if str(payload.get('code')) != '000000':
            raise ValueError('announcement API unsuccessful')
        data = payload['data']
        articles = data.get('articles') or [a for c in data['catalogs'] for a in c['articles']]
        if not articles:
            raise ValueError('announcement catalogue unexpectedly empty')
        return [entry(a['code'], a['title'], '',
                      'https://www.binance.com/en/support/announcement/' + a['code'], a['releaseDate'],
                      ['content_hint:promotional'] if re.search(r'(?i)competition|tournament|earn rewards|campaign|promotion|referral|voucher|giveaway', a['title']) else [])
                for a in articles]
    tree = Tree()
    tree.feed(body.decode('utf-8'))
    results = {}
    for anchor in tree.root.nodes():
        href = anchor.attrs.get('href', '')
        if anchor.tag != 'a':
            continue
        if source.connector.format == 'circle':
            if not href.startswith('/pressroom/') or 'press-link' not in anchor.attrs.get('class', '').split():
                continue
            container = anchor
            titles = [n for n in container.nodes() if n.attrs.get('fs-list-field') == 'title']
        else:
            if not re.match(r'^(https://www.coinbase.com)?/blog/[^/?#]+$', href):
                continue
            container, titles = anchor, []
            for _ in range(5):
                if container is None:
                    break
                titles = [n for n in container.nodes() if n.attrs.get('data-testid') == 'card-article-title']
                if titles:
                    break
                container = container.parent
        if len(titles) != 1:
            continue
        text = re.sub(r'\s+', ' ', container.text()).strip()
        published = re.search(r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}', text)
        if not published:
            continue
        title = re.sub(r'\s+', ' ', titles[0].text()).strip()
        link = urljoin(str(source.connector.url), href)
        # Date-only timestamps preserve source granularity; no fabricated time of day.
        results[link] = entry(link, title, text, link, published.group(), ['publication_precision:day'])
    if not results:
        raise ValueError('announcement page layout unrecognized')
    return list(results.values())


def parse_entries(source, body):
    try:
        kind = source.connector.type
        if kind == 'rss':
            parsed = feedparser.parse(body, sanitize_html=False, resolve_relative_uris=False)
            if not parsed.version or (parsed.bozo and not parsed.entries):
                raise ValueError('invalid feed')
            return parsed.entries
        if kind == 'statuspage':
            return statuspage(source, json.loads(body))
        if kind == 'sec_filing':
            return filings(source, json.loads(body))
        return announcements(source, body)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError) as exc:
        raise SourceParseError(type(exc).__name__) from None

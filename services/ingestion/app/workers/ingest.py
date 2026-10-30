import hashlib

from app.adapters.parsers import parse_entries, SourceParseError
from jsonschema.exceptions import ValidationError
from sqlalchemy.exc import IntegrityError

from app.logging import log
from app.normalization.rss import normalize
from app.storage.models import RawPayload, NewsItem, OutboxEvent, FailedItem, new_id


class InvalidFeed(ValueError):
    pass


def duplicate_violation(exc: IntegrityError) -> bool:
    # Only duplicate-key errors, never FK/null/check violations.
    args = getattr(exc.orig, 'args', ())
    if args and args[0] == 1062:
        return any(key in str(exc.orig) for key in ('uq_news_external', 'uq_news_content'))
    return 'UNIQUE constraint failed: news_items.source_id' in str(exc.orig)


class Ingestor:
    def __init__(self, sessions, contract):
        self.sessions, self.contract = sessions, contract

    def process(self, source, fetched, *, selected_indices=None):
        raw_id = new_id()
        counts = {'created': 0, 'duplicates': 0, 'failed': 0}
        with self.sessions.begin() as session:
            session.add(RawPayload(id=raw_id, source_id=source.id, body=fetched.body,
                                   content_type=fetched.content_type,
                                   received_at=fetched.received_at.replace(tzinfo=None)))
            session.flush()
            log('raw_stored', source_id=source.id, payload_id=raw_id)
            try:
                entries = parse_entries(source, fetched.body)
            except SourceParseError:
                entries = None
            if entries is None:
                session.add(FailedItem(source_id=source.id, raw_payload_id=raw_id,
                                       item_index=None, error_type='InvalidFeed'))
                counts['failed'] += 1
                log('feed_failed', source_id=source.id, payload_id=raw_id, error_type='InvalidFeed')
            else:
                if selected_indices is not None:
                    if any(not isinstance(i,int) or i<0 or i>=len(entries) for i in selected_indices):
                        raise ValueError('Invalid explicit research selection')
                    selected=set(selected_indices)
                else:
                    selected=set(range(min(len(entries),source.max_items_per_poll or len(entries))))
                if selected_indices is not None or source.max_items_per_poll is not None:
                    counts['deferred']=len(entries)-len(selected)
                for index, entry in enumerate(entries):
                    if index not in selected:continue
                    try:
                        event = normalize(entry, source, raw_id, fetched.received_at)
                        self.contract.validate(event)
                    except (ValueError, TypeError, KeyError, IndexError, OverflowError, ValidationError) as exc:
                        session.add(FailedItem(source_id=source.id, raw_payload_id=raw_id,
                                               item_index=index, error_type=type(exc).__name__))
                        counts['failed'] += 1
                        log('item_failed', source_id=source.id, payload_id=raw_id,
                            item_index=index, error_type=type(exc).__name__)
                        continue
                    ext_id = event['source']['external_id']
                    try:
                        with session.begin_nested():
                            session.add(NewsItem(message_id=event['message_id'], source_id=source.id,
                                                 external_id_hash=hashlib.sha256(ext_id.encode()).hexdigest() if ext_id else None,
                                                 content_hash=event['integrity']['content_hash'],
                                                 raw_payload_id=raw_id, item_index=index, event=event))
                            session.flush()
                            session.add(OutboxEvent(message_id=event['message_id'], payload=event))
                            session.flush()
                    except IntegrityError as exc:
                        if not duplicate_violation(exc):
                            raise
                        counts['duplicates'] += 1
                        continue
                    counts['created'] += 1
                    log('item_staged', source_id=source.id, payload_id=raw_id, message_id=event['message_id'])
        log('feed_committed', source_id=source.id, payload_id=raw_id, **counts)
        return counts

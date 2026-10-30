from datetime import datetime, timezone
from uuid import uuid4

from app.normalization.text import normalize_text, content_hash


def build_document(event, decision, *, snapshot=None, extracted=None, error=None, attempts=0):
    rss = normalize_text(event['content']['body'])
    body, content_source = rss, 'rss'
    if extracted and extracted.status == 'success':
        body = extracted.text
        content_source = {'trafilatura': 'html', 'pypdf': 'pdf', 'plain_text': 'plain_text'}[extracted.method]
    elif extracted and extracted.status == 'text_unavailable' and len(extracted.text) > len(rss):
        body = extracted.text
        content_source = {'trafilatura': 'html', 'pypdf': 'pdf', 'plain_text': 'plain_text'}[extracted.method]
    if (error and error.rejected) or (extracted and extracted.status == 'rejected'):
        status = 'rejected'
    elif extracted and extracted.status == 'success':
        status = 'ready'
    elif not decision.required and decision.sufficient:
        status = 'ready'
    else:
        status = 'partial' if body else 'failed'
    failure_reason = error.reason if error else (extracted.reason if extracted else None)
    if status != 'ready' and not failure_reason:
        failure_reason = 'insufficient_rss_content'
    received = datetime.fromisoformat(event['timestamps']['received_at'].replace('Z', '+00:00'))
    published = event['timestamps']['published_at']
    delay = (received - datetime.fromisoformat(published.replace('Z', '+00:00'))).total_seconds() if published else None
    metadata = error.metadata if error else {}
    fetch = {
        'status': 'not_requested' if not decision.required else 'unavailable',
        'requested_url': event['url'] if decision.required else None, 'final_url': None,
        'http_status': None, 'content_type': None, 'snapshot_id': None, 'fetched_at': None,
        'redirect_count': 0, 'attempt_count': attempts if decision.required else 0, 'error_reason': None}
    if snapshot:
        fetch.update(status='success', requested_url=snapshot.requested_url, final_url=snapshot.final_url,
                     http_status=snapshot.http_status, content_type=snapshot.content_type,
                     snapshot_id=snapshot.id, fetched_at=snapshot.fetched_at.replace(tzinfo=timezone.utc).isoformat(),
                     redirect_count=snapshot.redirect_count)
    elif error:
        fetch.update({key: value for key, value in metadata.items() if key in fetch})
        fetch.update(status='rejected' if error.rejected else ('unsupported' if error.reason == 'unsupported_encoding' else 'failed'),
                     error_reason=error.reason)
    if extracted:
        extraction = {'status': extracted.status, 'method': extracted.method,
                      'library_version': extracted.library_version, 'processor_version': '1.0',
                      'warnings': extracted.warnings, 'error_reason': extracted.reason}
    else:
        extraction = {'status': 'not_requested', 'method': 'rss', 'library_version': '1.0',
                      'processor_version': '1.0', 'warnings': [], 'error_reason': None}
    title = event['content']['title']  # Source title is never overwritten by an extractor.
    return {
        'schema_version': '1.0', 'message_id': str(uuid4()), 'document_id': str(uuid4()),
        'lineage': {'source_message_id': event['message_id'], 'input_subject': 'news.raw.v1',
                    'input_content_hash': event['integrity']['content_hash']},
        'source': {**event['source'], 'url': event['url']},
        'timestamps': {**event['timestamps'], 'enriched_at': datetime.now(timezone.utc).isoformat(),
                       'ingestion_delay_seconds': delay},
        'content': {'title': title, 'extracted_title': extracted.extracted_title if extracted else None,
                    'body': body, 'body_length': len(body), 'language': event['content']['language'],
                    'content_source': content_source},
        'classification': event['classification'],
        'enrichment': {'status': status, 'required': decision.required, 'reason': decision.reason,
                       'failure_reason': failure_reason},
        'fetch': fetch, 'extraction': extraction,
        'integrity': {'content_hash': content_hash(title, body, event['content']['language'])}}

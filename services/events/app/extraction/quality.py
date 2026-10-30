import unicodedata
from app.extraction.models import InputQuality


def normalize(value):
    return ' '.join(unicodedata.normalize('NFC',value).split())


def quality_gate(document, settings):
    title,body=normalize(document['content']['title']),normalize(document['content']['body'])
    title_usable=len(title)>=settings.title_min_characters and any(c.isalnum() for c in title)
    body_usable=len(body)>=settings.body_min_characters and any(c.isalnum() for c in body)
    usable=title_usable or body_usable
    status=document['enrichment']['status']
    title_only=body.casefold()==title.casefold()
    if usable and not title_only and status=='ready' and len(body)>=settings.high_body_characters:
        quality,reason='high','ready_substantial'
    elif usable and not title_only and status=='partial' and body_usable:
        quality,reason='medium','partial_meaningful'
    else:
        quality,reason='low','limited_evidence' if usable else 'no_usable_content'
    return InputQuality(usable=usable,quality=quality,reason=reason,document_status=status,
                        title_characters=len(title),body_characters=len(body))

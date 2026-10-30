from dataclasses import asdict, dataclass, field
from importlib.metadata import version
from io import BytesIO
from typing import Protocol

from app.normalization.text import normalize_text


@dataclass
class ExtractionResult:
    status: str
    method: str
    library_version: str
    text: str = ''
    extracted_title: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


class ContentExtractor(Protocol):
    def supports(self, content_type: str) -> bool: ...
    def extract(self, document: bytes, context: dict) -> ExtractionResult: ...


class HtmlContentExtractor:
    def supports(self, content_type):
        return content_type in ('text/html', 'application/xhtml+xml')

    def extract(self, document, context):
        import trafilatura
        from lxml import etree, html
        try:
            # Disable network/entity resolution; remove executable/style nodes before generic extraction.
            tree = html.fromstring(document, parser=html.HTMLParser(no_network=True, recover=True))
            for element in tree.xpath('//script|//style|//noscript|//nav|//footer'):
                element.drop_tree()
            metadata = trafilatura.extract_metadata(tree, default_url=context.get('url'))
            extracted_title = normalize_text(metadata.title)[:4096] if metadata and metadata.title else None
            text = trafilatura.extract(tree, url=context.get('url'), output_format='txt',
                include_comments=False, include_tables=True, favor_precision=True) or ''
            return finish_result('trafilatura', version('trafilatura'), text, context, extracted_title)
        except (ValueError, etree.Error):
            return ExtractionResult('failed', 'trafilatura', version('trafilatura'), reason='invalid_html')


class PdfContentExtractor:
    def supports(self, content_type):
        return content_type == 'application/pdf'

    def extract(self, document, context):
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
        try:
            if not document.startswith(b'%PDF-'):
                raise ValueError('invalid signature')
            reader = PdfReader(BytesIO(document), strict=False)
            if reader.is_encrypted:
                return ExtractionResult('unsupported', 'pypdf', version('pypdf'), reason='encrypted_pdf')
            if len(reader.pages) > context['max_pdf_pages']:
                return ExtractionResult('rejected', 'pypdf', version('pypdf'), reason='pdf_page_limit')
            parts, length = [], 0
            for page in reader.pages:
                part = page.extract_text() or ''
                length += len(part)
                if length > context['max_output_characters']:
                    return ExtractionResult('rejected', 'pypdf', version('pypdf'), reason='extracted_text_too_large')
                parts.append(part)
            title = reader.metadata.title if reader.metadata else None
            return finish_result('pypdf', version('pypdf'), '\n\n'.join(parts), context,
                                 normalize_text(str(title))[:4096] if title else None)
        except (PyPdfError, ValueError, TypeError, KeyError, IndexError):
            return ExtractionResult('failed', 'pypdf', version('pypdf'), reason='invalid_pdf')


class PlainTextExtractor:
    def supports(self, content_type):
        return content_type == 'text/plain'

    def extract(self, document, context):
        from email.message import Message
        message = Message()
        message['content-type'] = context.get('content_type_header', 'text/plain')
        encoding = message.get_content_charset() or 'utf-8'
        warnings = []
        try:
            text = document.decode(encoding)
        except (UnicodeError, LookupError):
            text = document.decode('utf-8', errors='replace')
            warnings.append('encoding_replacement')
        result = finish_result('plain_text', 'stdlib', text, context)
        result.warnings.extend(warnings)
        return result


def finish_result(method, library_version, text, context, extracted_title=None):
    text = normalize_text(text)
    if len(text) > context['max_output_characters']:
        return ExtractionResult('rejected', method, library_version, reason='extracted_text_too_large')
    if len(text) < context['minimum_extracted_characters']:
        return ExtractionResult('text_unavailable', method, library_version, text=text,
                                extracted_title=extracted_title, reason='insufficient_extracted_text')
    return ExtractionResult('success', method, library_version, text=text, extracted_title=extracted_title)


def extract_document(document, context):
    for extractor in (HtmlContentExtractor(), PdfContentExtractor(), PlainTextExtractor()):
        if extractor.supports(context['content_type']):
            return extractor.extract(document, context)
    return ExtractionResult('unsupported', 'none', '1.0', reason='unsupported_content_type')

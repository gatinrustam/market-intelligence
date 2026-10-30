"""Connector-specific parsing with the shared bounded/retrying HTTP transport.

Original response bytes are persisted by Ingestor before parsing. No synthetic RSS.
"""
from app.adapters.rss import GenericRSSAdapter


class StatuspageAdapter(GenericRSSAdapter):
    pass


class AnnouncementPageAdapter(GenericRSSAdapter):
    pass


class SECFilingAdapter(GenericRSSAdapter):
    pass


def make_adapter(source, client, settings):
    adapter = {'rss': GenericRSSAdapter, 'statuspage': StatuspageAdapter,
               'announcement_page': AnnouncementPageAdapter, 'sec_filing': SECFilingAdapter}[source.connector.type]
    return adapter(source, client, settings)

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {'timestamp': datetime.now(timezone.utc).isoformat(),
                'level': record.levelname, 'event': record.getMessage()}
        data.update(getattr(record, 'context', {}))
        return json.dumps(data, ensure_ascii=False)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # HTTP and NATS exception messages can contain credential-bearing URLs.
    for name in ('httpx', 'httpcore', 'nats'):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def log(event, **context):
    logging.getLogger('ingestion').info(event, extra={'context': context})

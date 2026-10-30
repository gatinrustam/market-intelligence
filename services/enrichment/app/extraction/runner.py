import asyncio
import base64
import json
import sys
import time
from importlib.metadata import version

from app.extraction.extractors import ExtractionResult
from app.logging import log


class ExtractionRunner:
    def __init__(self, settings):
        self.settings = settings

    async def extract(self, snapshot):
        context = {'url': snapshot.final_url, 'content_type': snapshot.content_type,
                   'content_type_header': snapshot.safe_headers.get('content-type', snapshot.content_type),
                   'max_pdf_pages': self.settings.max_pdf_pages,
                   'minimum_extracted_characters': self.settings.minimum_extracted_characters,
                   'max_output_characters': self.settings.max_output_characters}
        data = json.dumps({'body': base64.b64encode(snapshot.raw_body).decode(), 'context': context}).encode()
        method = {'text/html': 'trafilatura', 'application/xhtml+xml': 'trafilatura',
                  'application/pdf': 'pypdf', 'text/plain': 'plain_text'}.get(snapshot.content_type, 'none')
        library_version = version(method) if method in ('trafilatura', 'pypdf') else 'stdlib'
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.extraction.sandbox',
            str(self.settings.extraction_memory_mb), str(self.settings.extraction_timeout_seconds),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(data), self.settings.extraction_timeout_seconds)
            if process.returncode != 0:
                return ExtractionResult('failed', method, library_version, reason='extractor_process_failed')
            return ExtractionResult(**json.loads(stdout))
        except asyncio.TimeoutError:
            return ExtractionResult('failed', method, library_version, reason='extraction_timeout')
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            log('extraction_finished', snapshot_id=snapshot.id, job_id=snapshot.job_id,
                duration_ms=round((time.monotonic() - started) * 1000))

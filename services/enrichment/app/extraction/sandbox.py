"""Fixed executable entrypoint, bounded CPU/address space; no remote code execution."""
import base64
import json
import logging
import resource
import sys


def main():
    memory_mb, seconds = int(sys.argv[1]), int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    logging.disable(logging.CRITICAL)
    from app.extraction.extractors import extract_document
    data = json.load(sys.stdin)
    result = extract_document(base64.b64decode(data['body'], validate=True), data['context'])
    print(json.dumps(result.as_dict(), ensure_ascii=False))


if __name__ == '__main__':
    main()

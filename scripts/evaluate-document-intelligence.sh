#!/bin/sh
set -eu
docker compose run --rm --no-deps -v "$PWD/datasets/document_intelligence/gold:/gold:ro" --entrypoint python document-intelligence -m app.evaluator /gold

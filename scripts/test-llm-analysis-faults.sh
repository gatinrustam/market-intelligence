#!/bin/sh
set -eu
# Run after test-llm-analysis.sh; only the isolated test broker is stopped.
trap 'docker compose --profile test start nats-test >/dev/null 2>&1 || true' EXIT
docker compose --profile test stop nats-test
docker compose --profile test run --no-deps --rm llm-analysis-tests python -m tests.fault_probe offline
docker compose --profile test up -d --wait nats-test
docker compose --profile test run --no-deps --rm llm-analysis-tests python -m tests.fault_probe recover

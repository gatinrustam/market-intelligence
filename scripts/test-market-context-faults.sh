#!/bin/sh
set -eu
# Run after test-market-context.sh; only the isolated test broker is stopped.
trap 'docker compose --profile test start nats-test >/dev/null 2>&1 || true' EXIT
docker compose --profile test stop nats-test
docker compose --profile test run --no-deps --rm market-context-tests python -m tests.fault_probe offline
docker compose --profile test up -d --wait nats-test
docker compose --profile test run --no-deps --rm market-context-tests python -m tests.fault_probe recover

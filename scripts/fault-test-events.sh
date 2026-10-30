#!/bin/sh
# Run scripts/test-events.sh first. Isolated DB/broker only; run tests serially.
set -eu
trap 'docker compose --profile test start nats-test >/dev/null 2>&1 || true' EXIT
docker compose --profile test stop nats-test
docker compose --profile test run --rm --no-deps events-tests python -m tests.recovery_probe offline
docker compose --profile test up -d --wait nats-test
docker compose --profile test run --rm --no-deps events-tests python -m tests.recovery_probe recover

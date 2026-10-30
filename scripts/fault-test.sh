#!/bin/sh
# Run scripts/test.sh first. Uses test DB and test broker only.
set -eu
trap 'docker compose --profile test start nats-test >/dev/null 2>&1 || true' EXIT
docker compose --profile test stop nats-test
docker compose --profile test run --rm --no-deps tests python tests/recovery_probe.py offline
docker compose --profile test up -d --wait nats-test
docker compose --profile test run --rm --no-deps tests python tests/recovery_probe.py recover

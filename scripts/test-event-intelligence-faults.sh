#!/bin/sh
set -eu
docker compose --profile test build event-intelligence-tests
trap 'docker compose --profile test up -d nats-test >/dev/null' EXIT
docker compose --profile test stop nats-test
docker compose --profile test run --rm --no-deps event-intelligence-tests python -m tests.fault_probe offline
docker compose --profile test up -d --wait nats-test
docker compose --profile test run --rm --no-deps event-intelligence-tests python -m tests.fault_probe recover

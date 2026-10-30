#!/bin/sh
set -eu
docker compose --profile test run --build --rm --no-deps dashboard-tests

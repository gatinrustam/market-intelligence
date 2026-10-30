#!/bin/sh
set -eu
docker compose up -d db nats market-context-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS market_context_test; GRANT ALL PRIVILEGES ON market_context_test.* TO '\''market_context'\''@'\''%'\'';"'
docker compose --profile test run --build --rm market-context-tests "$@"

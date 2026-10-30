#!/bin/sh
set -eu
docker compose up -d db nats enrichment-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS enrichment_test; GRANT ALL PRIVILEGES ON enrichment_test.* TO '\''enrichment'\''@'\''%'\'';"'
docker compose --profile test run --build --rm enrichment-tests "$@"

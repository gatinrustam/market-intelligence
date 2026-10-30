#!/bin/sh
set -eu
docker compose up -d db nats migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS ingestion_test; GRANT ALL PRIVILEGES ON ingestion_test.* TO '\''ingestion'\''@'\''%'\'';"'
docker compose --profile test run --build --rm tests "$@"

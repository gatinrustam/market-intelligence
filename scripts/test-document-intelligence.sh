#!/bin/sh
set -eu
docker compose up -d db nats document-intelligence-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS document_intelligence_test; GRANT ALL PRIVILEGES ON document_intelligence_test.* TO '\''document_intelligence'\''@'\''%'\'';"'
docker compose --profile test run --build --rm document-intelligence-tests "$@"

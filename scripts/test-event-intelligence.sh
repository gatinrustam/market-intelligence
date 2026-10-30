#!/bin/sh
set -eu
docker compose up -d db nats event-intelligence-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS event_intelligence_test; GRANT ALL PRIVILEGES ON event_intelligence_test.* TO '\''event_intelligence'\''@'\''%'\'';"'
docker compose --profile test run --build --rm event-intelligence-tests "$@"

#!/bin/sh
set -eu
docker compose up -d db nats event-research-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS event_research_test; GRANT ALL PRIVILEGES ON event_research_test.* TO '\''event_research'\''@'\''%'\'';"'
docker compose --profile test run --build --rm event-research-tests "$@"

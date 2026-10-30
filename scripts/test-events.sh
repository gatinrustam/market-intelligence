#!/bin/sh
set -eu
docker compose up -d db nats events-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS events_test; GRANT ALL PRIVILEGES ON events_test.* TO '\''events'\''@'\''%'\'';"'
docker compose --profile test run --build --rm events-tests "$@"

#!/bin/sh
set -eu
docker compose up -d db nats market-data-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS market_data_test; GRANT ALL PRIVILEGES ON market_data_test.* TO '\''market_data'\''@'\''%'\'';"'
docker compose --profile test run --build --rm market-data-tests "$@"

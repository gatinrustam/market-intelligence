#!/bin/sh
set -eu
docker compose up -d db nats article-router-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS article_routing_test; GRANT ALL PRIVILEGES ON article_routing_test.* TO '\''article_routing'\''@'\''%'\'';"'
docker compose --profile test run --build --rm article-router-tests "$@"

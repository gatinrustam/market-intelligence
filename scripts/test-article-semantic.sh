#!/bin/sh
set -eu
docker compose up -d db nats article-semantic-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS article_semantic_test; GRANT ALL PRIVILEGES ON article_semantic_test.* TO '\''article_semantic'\''@'\''%'\'';"'
docker compose --profile test run --build --rm article-semantic-tests "$@"

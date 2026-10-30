#!/bin/sh
set -eu
docker compose up -d db nats llm-analysis-migrate
docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS llm_analysis_test; GRANT ALL PRIVILEGES ON llm_analysis_test.* TO '\''llm_analysis'\''@'\''%'\'';"'
docker compose --profile test run --build --rm llm-analysis-tests "$@"

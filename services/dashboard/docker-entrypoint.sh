#!/bin/sh
set -eu
mkdir -p storage/app storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs
: "${APP_KEY:?APP_KEY is required}"
: "${DB_DATABASE:=/var/www/html/storage/app/dashboard.sqlite}"
export DB_DATABASE
[ -e "$DB_DATABASE" ] || touch "$DB_DATABASE"
php artisan migrate --force --no-interaction
php artisan dashboard:bootstrap --no-interaction
chown -R www-data:www-data storage bootstrap/cache
exec runuser -u www-data -- "$@"

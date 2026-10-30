FROM php:8.5.10-cli-bookworm AS base
RUN apt-get update && apt-get install -y --no-install-recommends libicu-dev libzip-dev libsqlite3-dev unzip git ca-certificates \
    && docker-php-ext-install intl zip bcmath pdo_sqlite && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2.10.3 /usr/bin/composer /usr/bin/composer
WORKDIR /var/www/html
COPY services/dashboard/composer.json services/dashboard/composer.lock ./
RUN composer install --no-interaction --prefer-dist --no-scripts --no-autoloader
COPY services/dashboard .
RUN mkdir -p bootstrap/cache storage/app storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs \
    && composer dump-autoload --optimize && php artisan filament:assets \
    && chown -R www-data:www-data storage bootstrap/cache
FROM base AS test
RUN touch .env
ENV APP_ENV=testing DB_CONNECTION=sqlite DB_DATABASE=:memory: CACHE_STORE=array SESSION_DRIVER=array
USER www-data
CMD ["php", "artisan", "test"]
FROM base AS runtime
COPY services/dashboard/docker-entrypoint.sh /usr/local/bin/dashboard-entrypoint
RUN chmod +x /usr/local/bin/dashboard-entrypoint
EXPOSE 8006
ENTRYPOINT ["dashboard-entrypoint"]
CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8006", "--no-reload"]

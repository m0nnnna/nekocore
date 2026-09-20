# NekoCore website
#
# Build context is this directory (website/). The public tree goes to the
# Apache docroot; the helper library and CLI tools go to a private directory
# outside it. No credentials are baked in -- everything comes from the
# environment (see docker.env.example).

FROM php:8.3-apache

# gmp        SRP6 password math (registration, reset, admin login)
# pdo_mysql  AzerothCore databases
# mbstring   slugs / excerpts
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgmp-dev libonig-dev curl \
 && docker-php-ext-install -j"$(nproc)" gmp pdo_mysql mbstring opcache \
 && a2enmod headers rewrite \
 && rm -rf /var/lib/apt/lists/*

# Production php.ini plus a few overrides.
RUN mv "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini" \
 && { \
      echo 'expose_php = Off'; \
      echo 'upload_max_filesize = 8M'; \
      echo 'post_max_size = 8M'; \
      echo 'session.cookie_httponly = 1'; \
      echo 'session.use_strict_mode = 1'; \
      echo 'opcache.enable = 1'; \
      echo 'opcache.validate_timestamps = 0'; \
    } > "$PHP_INI_DIR/conf.d/nekocore.ini"

COPY docker/apache/nekocore.conf /etc/apache2/conf-enabled/nekocore.conf

# Private helpers: shared with the Laragon deployment, plus env-driven
# connection files that replace the credential-bearing ones.
ENV NEKO_PRIVATE_DIR=/var/www/private
COPY mailer.php srp6.php tokens.php news_schema.sql import_announcements.php create_announcement.php /var/www/private/
COPY docker/private/ /var/www/private/

# Public site.
COPY www/ /var/www/html/
RUN mkdir -p /var/www/html/downloads && chown -R www-data:www-data /var/www/html

WORKDIR /var/www/html
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost/healthz.php > /dev/null || exit 1

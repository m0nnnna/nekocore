# NekoCore website

Plain PHP 8 site for the realm. `www/` is the web root; everything else in this
directory is **private** and is deployed to `C:\laragon` (the path in
`www/inc/bootstrap.php` → `NEKO_PRIVATE`). Nothing in `www/` holds a secret.

## Layout

```
www/
  index.php            home: hero, latest news, realm status, downloads, top 5
  news.php             news list: categories, search, pinned post, pagination
  post.php             single post (?slug=…), prev/next, related
  feed.php             RSS 2.0
  register.php         account creation (was on the home page)
  lb.php  dropsearch.php  exchange.php
  forgot_password.php  reset_password.php  verify_email.php
  announcements.php    301 → news.php (old links keep working)
  admin/               news admin: login.php, index.php, edit.php, preview.php, logout.php
  inc/
    bootstrap.php      config array, e(), neko_db(), realm probe
    layout.php         neko_page_start()/neko_page_end(): head, nav, footer
    news.php           web_news repository + Markdown renderer
    admin_auth.php     staff sessions (SRP6 login against the game account)
  styles.css

news_schema.sql            CREATE TABLE web_news (auth database)
db_user.sql                limited MySQL account for the site (instead of root)
import_announcements.php   one-shot import of the old www/data/*.json posts
create_announcement.php    post from the CLI
```

## News

Posts live in `acore_auth.web_news` (next to the other `web_*` tables).
First-time setup:

```
mysql -u acore -p acore_auth < news_schema.sql
php import_announcements.php C:\path\to\www      # optional: bring over the old JSON posts
```

### Writing posts

Go to `/admin/` and sign in with a **game account** that has `gmlevel >= 3`
in `account_access`. The password is checked against the account's SRP6
verifier, so there is no separate admin password to manage.

The editor supports Markdown (headings, bold/italic, lists, quotes, code,
links, images), a live preview, categories (announcement, patch-notes, event,
maintenance, community), a summary line, drafts, scheduled publishing
(set a future publish date), pinning, and `[item:19019 Thunderfury]`
shortcodes that link into the drop search. Drafts and scheduled posts can be
previewed at `post.php?slug=…&preview=1` while signed in.

From the CLI:

```
php create_announcement.php "Title" "Body in **Markdown**" patch-notes [--draft] [--pin]
php create_announcement.php "Title" notes.md event
```

## Docker (deployed with the realm)

The site runs as the `neko-website` service inside the AzerothCore compose
stack (`C:\nekocore\server\docker-compose.override.yml`; master copy of the block
in `docker-compose.website.yml`). It joins `ac-network`, so it reaches
`ac-database`, `ac-authserver` and `ac-worldserver` by name, and listens on
`DOCKER_WEB_EXTERNAL_PORT` (8088, set in the stack's `.env`).

```
Dockerfile               php:8.3-apache + gmp/pdo_mysql/mbstring, opcache on
docker/apache/           vhost: deny /inc and /data, cache /downloads, trust X-Forwarded-Proto
docker/private/          env-driven db_connect*.php + mail_config.php (no secrets)
docker.env.example       copy to docker.env — SMTP creds and optional overrides
downloads/               nekocore-patch.zip (patch + realmlist, served at /downloads/)
www/healthz.php          container health check (PHP up + auth DB answering)
```

Everyday commands, from the AzerothCore checkout:

```
docker compose build neko-website          # after changing anything in website/
docker compose up -d neko-website          # (re)start just the site
docker logs -f neko-website
docker exec neko-website php /var/www/private/import_announcements.php /var/www/html
```

Config is all environment: `NEKO_BASE_URL`, `NEKO_DB_*`, `NEKO_SMTP_*`, `NEKO_AUTH_HOST`,
`NEKO_WORLD_HOST`, `NEKO_REGISTRATIONS_OPEN`, `NEKO_TZ`, … (see
`docker.env.example`). `NEKO_PRIVATE_DIR` points the site at
`/var/www/private` inside the image; outside Docker it defaults to
`C:\laragon`, so the Laragon deployment keeps working unchanged.

## Security notes

- **Keep PHP patched.** The image follows `php:8.3-apache`, so pick up PHP
  security releases with `docker compose build --pull neko-website` and check
  `docker exec neko-website php -v`.
- **`NEKO_BASE_URL` is required** for registration and password reset. Emailed
  links are built only from it, never from the request's `Host` header.
- **Don't run the site as MySQL root.** `db_user.sql` creates `neko_web` with
  just the grants the pages use; see the comments at its top for switching over.
- **Staff sign-in is throttled** per client IP (10 failures / 15 min) and per
  account (5 / 15 min), in small files under the system temp directory. Behind
  a reverse proxy every request has the proxy's IP, so the IP limit is shared
  by everyone signing in.
- Database and exception details go to the PHP error log (`docker logs
  neko-website`), not to the page.

`opcache.validate_timestamps` is off in the image — PHP changes need a
rebuild, not just a restart.

## Local development

The CLI PHP in scoop ships without extensions enabled; run the dev server with
an ini that loads `gmp`, `mbstring` and `pdo_mysql`:

```
php -c dev-php.ini -S 127.0.0.1:8089 -t www
```

Time zone: the site runs in America/Chicago (`bootstrap.php`); every DB
connection sets `SESSION time_zone` to match so publish dates and scheduling
agree with MySQL's `NOW()`.

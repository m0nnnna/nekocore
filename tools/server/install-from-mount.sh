#!/bin/sh
# First-time install of the NekoCore realm + website on a production box from
# the deploy share (Windows dev machine's Y:\nekocore-deploy, mounted here at
# $SOURCE_DIR). Same "build on the dev machine, ship images, don't compile on
# the small box" flow as nekous-deploy/update-from-mount.sh.
#
# Run ON the production box, as a user with docker permissions:
#
#   sh /mnt/deploy/nekocore-deploy/install-from-mount.sh
#
# What it does, in order:
#   1. Copies tree/ (compose files, .env, server confs, 3.1 GB client data,
#      DBC bind-mount inputs, website env + downloads, ops scripts) to
#      $DEST_DIR, laid out exactly like C:\nekocore on the dev box so the
#      relative bind mounts in server/docker-compose.override.yml resolve.
#   2. `docker load`s the prebuilt images straight from the mount.
#   3. Starts ac-database only, restores the three DB dumps (a mirror of the
#      dev/current production database), then applies the realm connection
#      row (REALM_* in server/.env).
#   4. Brings the whole stack up (db-import runs its pending updates, then
#      auth, world, and the website on port 8088).
#
# Refuses to run if $DEST_DIR already exists -- use update-from-mount.sh for
# later releases. Portable /bin/sh (Alpine ash), needs only Docker + compose v2.

set -eu

SOURCE_DIR="${SOURCE_DIR:-/mnt/deploy/nekocore-deploy}"
DEST_DIR="${DEST_DIR:-/opt/nekocore}"
RUN_UID="${RUN_UID:-1000}"   # DOCKER_USER_ID in server/.env -- the acore user inside the containers

[ -d "$SOURCE_DIR/tree/server" ] || { echo "error: $SOURCE_DIR/tree/server not found -- is the share mounted?" >&2; exit 1; }
[ -d "$DEST_DIR" ] && { echo "error: $DEST_DIR already exists -- this is a first-install script; use update-from-mount.sh" >&2; exit 1; }
command -v docker >/dev/null || { echo "error: docker not installed" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "error: docker compose v2 plugin missing (apk add docker-cli-compose)" >&2; exit 1; }

for f in images/mysql-8.4.tar images/ac-wotlk-worldserver.tar images/ac-wotlk-authserver.tar images/ac-wotlk-db-import.tar images/ac-wotlk-client-data.tar images/website.tar \
         db/acore_auth.sql.gz db/acore_characters.sql.gz db/acore_world.sql.gz \
         tree/server/.env tree/server/docker-compose.yml tree/server/docker-compose.override.yml tree/website/docker.env; do
    [ -f "$SOURCE_DIR/$f" ] || { echo "error: expected file missing from mount: $SOURCE_DIR/$f" >&2; exit 1; }
done

DB_ROOT_PASSWORD=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$SOURCE_DIR/tree/server/.env" | tail -1 | cut -d= -f2-)
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-password}"

# The mysql image first runs a TEMPORARY server during initialisation (socket
# only, port 0) and shuts it down before starting the real one -- a plain
# `mysql -e "SELECT 1"` through docker exec succeeds against that temporary
# server, and whatever runs next lands in the shutdown gap. So require the real
# server's log line ("ready for connections ... port: 3306") as well.
wait_for_mysql() {
    i=0
    until docker logs ac-database 2>&1 | grep -q 'ready for connections.*port: 3306'         && docker exec ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do
        i=$((i+1)); [ $i -gt 120 ] && { echo "error: ac-database never became ready" >&2; docker logs --tail 20 ac-database >&2; exit 1; }
        sleep 2
    done
}

echo "==> copying runtime tree to $DEST_DIR (this includes 3.1 GB of client data)"
mkdir -p "$DEST_DIR"
cp -a "$SOURCE_DIR/tree/." "$DEST_DIR/"
mkdir -p "$DEST_DIR/server/env/dist/logs" "$DEST_DIR/server/backups" "$DEST_DIR/website/downloads"
cp "$SOURCE_DIR/install-from-mount.sh" "$SOURCE_DIR/update-from-mount.sh" "$DEST_DIR/" 2>/dev/null || true
# The containers run as uid $RUN_UID and must be able to write logs/etc.
chown -R "$RUN_UID:$RUN_UID" "$DEST_DIR/server/env" 2>/dev/null || echo "warning: chown failed (not root?) -- make sure uid $RUN_UID can write $DEST_DIR/server/env/dist/{etc,logs}"

echo "==> loading images"
for t in mysql-8.4 ac-wotlk-worldserver ac-wotlk-authserver ac-wotlk-db-import ac-wotlk-client-data website; do
    docker load -i "$SOURCE_DIR/images/$t.tar"
done

cd "$DEST_DIR/server"

echo "==> starting the database"
docker compose up -d ac-database
echo "    waiting for MySQL..."
wait_for_mysql

echo "==> restoring databases (mirror of the dev/current production DB)"
for db in acore_auth acore_characters acore_world; do
    printf '    %s ... ' "$db"
    docker exec ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS \`$db\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" 2>/dev/null
    gzip -dc "$SOURCE_DIR/db/$db.sql.gz" | docker exec -i ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" "$db" 2>&1 | grep -v 'Using a password' || true
    echo done
done

echo "==> applying the realm connection row"
sh "$DEST_DIR/tools/server/apply_realmlist.sh" "$DEST_DIR/server"

echo "==> bringing the stack up (db-import applies pending updates first; this can take a few minutes)"
docker compose up -d

echo "==> done"
docker compose ps
cat <<EOF

Next:
  - watch the worldserver come up:   docker logs -f ac-worldserver   (look for 'ready...')
  - website health:                   curl -s http://localhost:8088/healthz.php
  - point the VPS nginx (wow.nekos.farm) at this box:8088 and forward 3724/8085 here
  - install the backup crontab from $DEST_DIR/tools/server/backup_db.sh's header
EOF

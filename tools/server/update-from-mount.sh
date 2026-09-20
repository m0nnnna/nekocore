#!/bin/sh
# Updates an existing NekoCore production install from a newer drop on the
# deploy share. Counterpart of install-from-mount.sh; run ON the production box:
#
#   sh /opt/nekocore/update-from-mount.sh            # images + configs
#   RESTORE_DB=1 sh /opt/nekocore/update-from-mount.sh   # ...and overwrite the DB with the dumps
#
# What it does:
#   1. Copies compose files, server confs, DBC inputs, website downloads and
#      the ops scripts from the mount. Does NOT touch server/.env or
#      website/docker.env (this box's own secrets) and does NOT re-copy the
#      3.1 GB client data unless CLIENT_DATA=1.
#   2. `docker load`s whichever image tars are on the mount.
#   3. Optionally (RESTORE_DB=1) stops the servers and overwrites all three
#      databases with the dumps from the mount -- a full mirror of the dev box.
#      Take a backup first (tools/server/backup_db.sh); this is destructive.
#      Otherwise (the normal case once players exist) it runs the freshly
#      loaded ac-db-import once, which applies any new module SQL (nekolog
#      tables, third-party tp_*.sql, ...) to the live databases in place --
#      AzerothCore's updater tracks what it has applied, so this is idempotent.
#      MODULE_SQL=0 skips that.
#   4. Re-applies the realm connection row and recreates the stack.
#
# Safe to re-run. Portable /bin/sh.

set -eu

SOURCE_DIR="${SOURCE_DIR:-/mnt/deploy/nekocore-deploy}"
DEST_DIR="${DEST_DIR:-/opt/nekocore}"
RESTORE_DB="${RESTORE_DB:-0}"
CLIENT_DATA="${CLIENT_DATA:-0}"
MODULE_SQL="${MODULE_SQL:-1}"

[ -d "$SOURCE_DIR/tree/server" ] || { echo "error: $SOURCE_DIR/tree/server not found -- is the share mounted?" >&2; exit 1; }
[ -f "$DEST_DIR/server/.env" ] || { echo "error: $DEST_DIR/server/.env missing -- not an existing install; use install-from-mount.sh" >&2; exit 1; }

DB_ROOT_PASSWORD=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$DEST_DIR/server/.env" | tail -1 | cut -d= -f2-)
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-password}"

echo "==> copying configs"
cp "$SOURCE_DIR/tree/server/docker-compose.yml" "$SOURCE_DIR/tree/server/docker-compose.override.yml" "$DEST_DIR/server/"
cp "$SOURCE_DIR/tree/server/conf/dist/env.ac" "$DEST_DIR/server/conf/dist/"
cp -a "$SOURCE_DIR/tree/server/env/dist/etc/." "$DEST_DIR/server/env/dist/etc/"
cp -a "$SOURCE_DIR/tree/server/env/dist/lua_scripts/." "$DEST_DIR/server/env/dist/lua_scripts/" 2>/dev/null || true
cp -a "$SOURCE_DIR/tree/data/." "$DEST_DIR/data/"
cp -a "$SOURCE_DIR/tree/client-patch/." "$DEST_DIR/client-patch/"
cp -a "$SOURCE_DIR/tree/tools/." "$DEST_DIR/tools/"
cp -a "$SOURCE_DIR/tree/website/downloads/." "$DEST_DIR/website/downloads/"
cp "$SOURCE_DIR/tree/website/docker.env.example" "$DEST_DIR/website/" 2>/dev/null || true
cp "$SOURCE_DIR/install-from-mount.sh" "$SOURCE_DIR/update-from-mount.sh" "$DEST_DIR/" 2>/dev/null || true
if [ "$CLIENT_DATA" = "1" ]; then
    echo "==> re-copying client data (3.1 GB)"
    cp -a "$SOURCE_DIR/tree/server/env/dist/data/." "$DEST_DIR/server/env/dist/data/"
fi

echo "==> loading images"
for t in "$SOURCE_DIR"/images/*.tar; do
    docker load -i "$t"
done

cd "$DEST_DIR/server"

if [ "$RESTORE_DB" = "1" ]; then
    echo "==> RESTORE_DB=1: stopping servers and overwriting the databases from the mount"
    docker compose stop ac-worldserver ac-authserver neko-website
    docker compose up -d ac-database
    until docker exec ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do sleep 2; done
    for db in acore_auth acore_characters acore_world; do
        printf '    %s ... ' "$db"
        docker exec ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS \`$db\`; CREATE DATABASE \`$db\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" 2>/dev/null
        gzip -dc "$SOURCE_DIR/db/$db.sql.gz" | docker exec -i ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" "$db" 2>/dev/null
        echo done
    done
elif [ "$MODULE_SQL" = "1" ]; then
    echo "==> applying module SQL to the live databases (ac-db-import)"
    docker compose stop ac-worldserver ac-authserver
    docker compose up -d ac-database
    until docker exec ac-database mysql -uroot -p"$DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do sleep 2; done
    docker compose up --exit-code-from ac-db-import ac-db-import
fi

echo "==> realm connection row"
sh "$DEST_DIR/tools/server/apply_realmlist.sh" "$DEST_DIR/server"

echo "==> recreating containers"
docker compose up -d --force-recreate

echo "==> done"
docker compose ps

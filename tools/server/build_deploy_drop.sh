#!/bin/sh
# Rebuilds the production drop on the deploy share from this dev box:
# DB dumps, docker images, and the runtime tree that install-from-mount.sh /
# update-from-mount.sh consume. Run from the repo root in Git Bash:
#
#   sh tools/server/build_deploy_drop.sh                 # -> Y:/nekocore-deploy
#   DROP_DIR=/y/other sh tools/server/build_deploy_drop.sh
#   CLIENT_DATA=1 ...                                    # also re-copy the 3.1 GB maps/vmaps/mmaps/dbc
#   SKIP_IMAGES=1 ...                                    # tree + dumps only (images unchanged)
#
# What it does NOT do: touch the drop's README (write the changelog by hand),
# or the mysql image (saved once, never changes). Secrets DO go in the tree
# (server/.env, website/docker.env) -- the share is private and the box
# scripts never overwrite them once installed.
#
# Portable /bin/sh; uses docker, gzip, cp -- no robocopy, so the same script
# would work from a Linux dev box.

set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DROP_DIR="${DROP_DIR:-/y/nekocore-deploy}"
CLIENT_DATA="${CLIENT_DATA:-0}"
SKIP_IMAGES="${SKIP_IMAGES:-0}"

[ -d "$DROP_DIR" ] || { echo "error: $DROP_DIR not found -- is the share mounted?" >&2; exit 1; }
[ -f "$REPO/server/.env" ] || { echo "error: $REPO/server/.env missing" >&2; exit 1; }

# Checked up front, before the slow dumps and image saves.
. "$REPO/tools/server/check_patch_zip.sh"

DB_ROOT_PASSWORD=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$REPO/server/.env" | tail -1 | cut -d= -f2-)
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-password}"
T="$DROP_DIR/tree"

echo "==> database dumps -> $DROP_DIR/db"
mkdir -p "$DROP_DIR/db"
for db in acore_auth acore_characters acore_world; do
    printf '    %s ... ' "$db"
    docker exec ac-database mysqldump -uroot -p"$DB_ROOT_PASSWORD" --single-transaction --quick --routines --triggers --events "$db" 2>/dev/null \
        | gzip > "$DROP_DIR/db/$db.sql.gz"
    echo "$(du -h "$DROP_DIR/db/$db.sql.gz" | cut -f1)"
done

if [ "$SKIP_IMAGES" != "1" ]; then
    echo "==> images -> $DROP_DIR/images"
    mkdir -p "$DROP_DIR/images"
    save() { printf '    %s ... ' "$2"; docker save -o "$DROP_DIR/images/$2.tar" "$1"; echo "$(du -h "$DROP_DIR/images/$2.tar" | cut -f1)"; }
    save acore/ac-wotlk-worldserver:master  ac-wotlk-worldserver
    save acore/ac-wotlk-authserver:master   ac-wotlk-authserver
    save acore/ac-wotlk-db-import:master    ac-wotlk-db-import
    save acore/ac-wotlk-client-data:master  ac-wotlk-client-data
    save nekocore/website:latest            website
    [ -f "$DROP_DIR/images/mysql-8.4.tar" ] || save mysql:8.4 mysql-8.4
fi

echo "==> runtime tree -> $T"
mkdir -p "$T/server/conf/dist" "$T/server/env/dist" "$T/data/sql" "$T/client-patch" "$T/tools/server" "$T/website/downloads"

# server/: compose files, .env, env.ac, confs (minus editor backups), lua
cp "$REPO/server/docker-compose.yml" "$REPO/server/docker-compose.override.yml" "$REPO/server/.env" "$T/server/"
cp "$REPO/server/conf/dist/env.ac" "$T/server/conf/dist/"
rm -rf "$T/server/env/dist/etc" "$T/server/env/dist/lua_scripts"
cp -a "$REPO/server/env/dist/etc" "$T/server/env/dist/etc"
find "$T/server/env/dist/etc" -name '*.bak-*' -delete
cp -a "$REPO/server/env/dist/lua_scripts" "$T/server/env/dist/lua_scripts"
if [ "$CLIENT_DATA" = "1" ]; then
    echo "    client data (3.1 GB) ..."
    rm -rf "$T/server/env/dist/data"
    cp -a "$REPO/server/env/dist/data" "$T/server/env/dist/data"
fi

# data/: generated DBCs the override bind-mounts + the module SQL
rm -rf "$T/data/generated" "$T/data/sql"
mkdir -p "$T/data/generated/dbc"
# Every data/generated file the override mounts, read from the override itself:
# a mounted file missing here makes docker create an empty directory in its
# place on the box, and the worldserver can't load that DBC.
for rel in $(grep -oE '"\.\./data/generated/[^:"]+' "$REPO/server/docker-compose.override.yml" | sed 's|^"\.\./data/generated/||' | sort -u); do
    [ -f "$REPO/data/generated/$rel" ] || { echo "error: override mounts data/generated/$rel but it doesn't exist" >&2; exit 1; }
    cp "$REPO/data/generated/$rel" "$T/data/generated/$rel"
done
cp -a "$REPO/data/sql" "$T/data/sql"

# client-patch/: mod-individual-progression's optional DBCs (bind-mounted too)
rm -rf "$T/client-patch/progression-optional"
cp -a "$REPO/client-patch/progression-optional" "$T/client-patch/progression-optional"

# tools/server: the ops scripts the box runs
cp "$REPO"/tools/server/apply_realmlist.sh "$REPO"/tools/server/apply_module_sql.sh "$REPO"/tools/server/backup_db.sh "$T/tools/server/"

# website/: env + downloads (the patch zip players get from the site; there is
# no full client download any more)
cp "$REPO/website/docker.env" "$REPO/website/docker.env.example" "$REPO/website/docker-compose.website.yml" "$T/website/"
cp "$REPO/website/downloads/realmlist.wtf" "$T/website/downloads/"
cp "$PATCH_ZIP" "$T/website/downloads/"

# box scripts
cp "$REPO"/tools/server/install-from-mount.sh "$REPO"/tools/server/update-from-mount.sh "$REPO"/tools/server/update-website-from-mount.sh "$DROP_DIR/" 2>/dev/null || true

echo "==> done: $(date '+%Y-%m-%d %H:%M')"
echo "    now update $DROP_DIR/README.md with what changed in this drop"

#!/bin/sh
# Applies the production realm connection row (data/sql/db-auth/base/
# nekocore_realmlist.sql -- public VPN-proxy address + LAN address) to the
# running ac-database. This is THE go-live step: a fresh db-import leaves the
# dev row (AzerothCore / 192.168.0.10 / 127.0.0.1), which only works on this
# box. Idempotent (REPLACE INTO); run after every db-import or DB restore.
#
# Portable /bin/sh, needs only Docker. Usage:
#   tools/server/apply_realmlist.sh [azerothcore-dir]    (default: ./server)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
AC_DIR="${1:-$REPO_ROOT/server}"
SQL="$REPO_ROOT/data/sql/db-auth/base/nekocore_realmlist.sql"
CONTAINER="${AC_DB_CONTAINER:-ac-database}"

[ -f "$SQL" ] || { echo "error: $SQL missing" >&2; exit 1; }
[ -f "$AC_DIR/.env" ] || { echo "error: $AC_DIR/.env not found -- pass the server dir as arg 1" >&2; exit 1; }
DB_ROOT_PASSWORD=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$AC_DIR/.env" | tail -1 | cut -d= -f2-)
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-password}"

docker exec -i "$CONTAINER" mysql -uroot -p"$DB_ROOT_PASSWORD" acore_auth < "$SQL"
echo "realmlist now:"
docker exec "$CONTAINER" mysql -uroot -p"$DB_ROOT_PASSWORD" -t -e \
    "SELECT id, name, address, localAddress, localSubnetMask, port FROM acore_auth.realmlist" 2>/dev/null
echo "Note: authserver caches the realm list -- 'docker compose restart ac-authserver' to make it pick this up now."

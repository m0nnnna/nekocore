#!/bin/sh
# Writes this box's realm connection row (acore_auth.realmlist id 1) into the
# running ac-database. A fresh db-import or a DB restore leaves AzerothCore's
# default row (127.0.0.1), so `nekocore update` runs this as its last step.
# Idempotent (REPLACE INTO).
#
# The values come from the server dir's .env, so no address lives in the repo:
#   REALM_NAME=NekoCore
#   REALM_ADDRESS=203.0.113.5         what players connect to (the public IP the
#                                     authserver hands out; see docs/deploy.md)
#   REALM_LOCAL_ADDRESS=192.168.1.20  what LAN clients get instead
#   REALM_SUBNET_MASK=255.0.0.0
# With REALM_ADDRESS unset it leaves the row alone.
#
# Portable /bin/sh, needs only Docker. Usage:
#   tools/server/apply_realmlist.sh [azerothcore-dir]    (default: ./server)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
AC_DIR="${1:-$REPO_ROOT/server}"
CONTAINER="${AC_DB_CONTAINER:-ac-database}"

[ -f "$AC_DIR/.env" ] || { echo "error: $AC_DIR/.env not found -- pass the server dir as arg 1" >&2; exit 1; }
env_get() { grep -E "^$1=" "$AC_DIR/.env" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
DB_ROOT_PASSWORD=$(env_get DOCKER_DB_ROOT_PASSWORD)
[ -n "$DB_ROOT_PASSWORD" ] || { echo "error: DOCKER_DB_ROOT_PASSWORD missing from $AC_DIR/.env" >&2; exit 1; }
REALM_ADDRESS=$(env_get REALM_ADDRESS)
if [ -z "$REALM_ADDRESS" ]; then
    echo "REALM_ADDRESS not set in $AC_DIR/.env -- realmlist left as it is"
    exit 0
fi
REALM_NAME=$(env_get REALM_NAME); REALM_NAME=${REALM_NAME:-NekoCore}
REALM_LOCAL_ADDRESS=$(env_get REALM_LOCAL_ADDRESS); REALM_LOCAL_ADDRESS=${REALM_LOCAL_ADDRESS:-127.0.0.1}
REALM_SUBNET_MASK=$(env_get REALM_SUBNET_MASK); REALM_SUBNET_MASK=${REALM_SUBNET_MASK:-255.255.255.0}
for v in "$REALM_NAME" "$REALM_ADDRESS" "$REALM_LOCAL_ADDRESS" "$REALM_SUBNET_MASK"; do
    case "$v" in *"'"*|*'\'*) echo "error: quote or backslash in a REALM_* value" >&2; exit 1 ;; esac
done

printf "REPLACE INTO \`realmlist\` (\`id\`, \`name\`, \`address\`, \`localAddress\`, \`localSubnetMask\`, \`port\`, \`icon\`, \`flag\`, \`timezone\`, \`allowedSecurityLevel\`, \`population\`, \`gamebuild\`) VALUES (1, '%s', '%s', '%s', '%s', 8085, 0, 0, 2, 0, 0, 12340);\n" \
    "$REALM_NAME" "$REALM_ADDRESS" "$REALM_LOCAL_ADDRESS" "$REALM_SUBNET_MASK" \
    | docker exec -i "$CONTAINER" mysql -uroot -p"$DB_ROOT_PASSWORD" acore_auth 2>&1 | grep -v 'Using a password' || true
echo "realmlist now:"
docker exec "$CONTAINER" mysql -uroot -p"$DB_ROOT_PASSWORD" -t -e \
    "SELECT id, name, address, localAddress, localSubnetMask, port FROM acore_auth.realmlist" 2>/dev/null
echo "Note: authserver caches the realm list -- 'docker compose restart ac-authserver' to make it pick this up now."

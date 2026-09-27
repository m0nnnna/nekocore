#!/usr/bin/env bash
# Restarts (or recreates) the worldserver ONLY if nobody is logged in.
#
# Exists because "check the online count, then restart" as two commands in a
# shell chain does not actually guard anything: `&&` tests whether the query
# RAN, not what it returned, so it happily restarts with players online. That
# mistake disconnected the user twice during this project's era-spell work.
#
# Usage:
#   ./restart_if_empty.sh [restart|up]     (default: restart)
#
#   restart -- picks up changed file CONTENT (a rebuilt DBC, new SQL)
#   up      -- recreates the container, needed after a docker-compose change
#              such as adding a bind mount or building a new image
#
# Exits 0 when it restarted, 1 when it refused because someone is online.
set -euo pipefail

MODE="${1:-restart}"
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../server" && pwd)"
PASS="$(sed -n 's/\r$//;s/^DOCKER_DB_ROOT_PASSWORD=//p' "$SERVER_DIR/.env")"

ONLINE="$(docker exec -e MYSQL_PWD="$PASS" ac-database mysql -uroot -N \
    -e "SELECT COUNT(*) FROM acore_characters.characters WHERE online=1;" 2>/dev/null \
    | tr -d '[:space:]')"

if [ -z "$ONLINE" ]; then
    echo "refusing: could not read the online count (is ac-database up?)" >&2
    exit 1
fi

if [ "$ONLINE" -ne 0 ]; then
    echo "refusing: $ONLINE character(s) online -- restarting would disconnect them." >&2
    exit 1
fi

cd "$SERVER_DIR"
case "$MODE" in
    restart) docker compose restart ac-worldserver ;;
    up)      docker compose up -d ac-worldserver ;;
    *)       echo "unknown mode '$MODE' (want: restart | up)" >&2; exit 1 ;;
esac

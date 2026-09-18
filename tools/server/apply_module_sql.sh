#!/bin/sh
# Applies every installed module's SQL to the database via AzerothCore's
# own db-import tool -- NOT a standalone mysql-client script. Reuses the
# exact mechanism already proven working in this project (per-DB routing,
# update tracking via the `updates` table so reruns don't reapply the same
# file, correct handling of data/sql/db-<name>/{base,updates}/*.sql across
# every module under modules/). The only thing this script adds is doing
# the two steps (rebuild from local source, then run) in one call, since
# forgetting the rebuild step silently uses whatever db-import image was
# last pulled/built -- which has no idea any module SQL exists at all (hit
# this exact failure mode earlier in this project, see nekocore's README).
#
# Portable /bin/sh (Alpine's ash, not bash) -- no bashisms.
#
# Usage:
#   ./apply_module_sql.sh [path-to-azerothcore-checkout]
# Defaults to the current directory if no path is given (run it from
# inside the AzerothCore checkout, or pass the path explicitly).

set -eu

AC_DIR="${1:-.}"

if [ ! -f "$AC_DIR/docker-compose.yml" ]; then
    echo "error: $AC_DIR doesn't look like an AzerothCore checkout (no docker-compose.yml)" >&2
    exit 1
fi

cd "$AC_DIR"

echo "+ docker compose build ac-db-import"
docker compose build ac-db-import

echo "+ docker compose up --exit-code-from ac-db-import ac-db-import"
# --exit-code-from is required -- plain `docker compose up` always exits 0
# regardless of the service's own exit code, so a failed import (e.g. a
# bad SQL file) would otherwise look identical to a successful one to
# anything scripting around this.
docker compose up --exit-code-from ac-db-import ac-db-import

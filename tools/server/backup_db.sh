#!/bin/sh
# Dumps one AzerothCore database via `docker exec ac-database mysqldump`,
# gzips it, and prunes old backups down to a keep-count. Meant to be run
# from cron -- see the crontab block below for the actual schedule this
# project needs (acore_world daily, acore_auth/acore_characters hourly).
#
# Runs entirely through Docker (mysqldump executes INSIDE the ac-database
# container, not on the host) so it needs nothing installed beyond Docker
# itself -- same reasoning as apply_module_sql.sh, and works unchanged
# whether this is the current Windows dev box or the Alpine target.
#
# Portable /bin/sh (Alpine's ash, not bash) -- no bashisms.
#
# Usage:
#   ./backup_db.sh <db-name> [azerothcore-dir] [backup-dir] [keep-count]
#
#   db-name          acore_world | acore_auth | acore_characters
#   azerothcore-dir  default "." -- must contain .env (read for
#                    DOCKER_DB_ROOT_PASSWORD) and docker-compose.yml
#   backup-dir       default "<azerothcore-dir>/backups/<db-name>"
#   keep-count       how many most-recent backups to retain; default 24
#
# Crontab (adjust the two paths for wherever this ends up on the target
# box; keep-counts below: 14 daily world backups = 2 weeks, 48 hourly
# auth/characters backups = 2 days -- adjust to taste, these are just
# reasonable starting defaults, not a hard requirement):
#
#   0 3 * * * /path/to/tools/server/backup_db.sh acore_world /path/to/azerothcore /path/to/backups 14      >> /var/log/ac-backup.log 2>&1
#   0 * * * * /path/to/tools/server/backup_db.sh acore_auth /path/to/azerothcore /path/to/backups 48       >> /var/log/ac-backup.log 2>&1
#   0 * * * * /path/to/tools/server/backup_db.sh acore_characters /path/to/azerothcore /path/to/backups 48 >> /var/log/ac-backup.log 2>&1

set -eu

DB_NAME="${1:?usage: backup_db.sh <db-name> [azerothcore-dir] [backup-dir] [keep-count]}"
AC_DIR="${2:-.}"
BACKUP_ROOT="${3:-$AC_DIR/backups}"
KEEP="${4:-24}"
CONTAINER="${AC_DB_CONTAINER:-ac-database}"

if [ ! -f "$AC_DIR/.env" ]; then
    echo "error: $AC_DIR/.env not found -- pass the AzerothCore checkout dir as arg 2" >&2
    exit 1
fi

# Only need DOCKER_DB_ROOT_PASSWORD out of .env -- avoid sourcing the
# whole file (it's not meant to be `sh`-safe, just a plain KEY=VALUE list).
DB_ROOT_PASSWORD=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$AC_DIR/.env" | tail -1 | cut -d= -f2-)
if [ -z "$DB_ROOT_PASSWORD" ]; then
    echo "error: DOCKER_DB_ROOT_PASSWORD not set in $AC_DIR/.env" >&2
    exit 1
fi

if ! docker exec "$CONTAINER" true >/dev/null 2>&1; then
    echo "error: container '$CONTAINER' isn't running (checked with docker exec)" >&2
    exit 1
fi

OUT_DIR="$BACKUP_ROOT/$DB_NAME"
mkdir -p "$OUT_DIR"

STAMP=$(date +%Y%m%d_%H%M%S)
OUT_FILE="$OUT_DIR/${DB_NAME}_${STAMP}.sql.gz"
TMP_FILE="$OUT_FILE.partial"

echo "backing up $DB_NAME -> $OUT_FILE"
docker exec "$CONTAINER" mysqldump \
    -uroot -p"$DB_ROOT_PASSWORD" \
    --single-transaction --routines --triggers --events \
    "$DB_NAME" | gzip > "$TMP_FILE"
mv "$TMP_FILE" "$OUT_FILE"
echo "done: $(du -h "$OUT_FILE" | cut -f1)"

# Retention: keep the $KEEP most recent, delete the rest.
COUNT=$(find "$OUT_DIR" -maxdepth 1 -name "${DB_NAME}_*.sql.gz" | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
    PRUNE=$((COUNT - KEEP))
    echo "pruning $PRUNE old backup(s) (keeping $KEEP most recent)"
    find "$OUT_DIR" -maxdepth 1 -name "${DB_NAME}_*.sql.gz" | sort | head -n "$PRUNE" | while IFS= read -r f; do
        rm -f "$f"
        echo "  removed $f"
    done
fi

#!/bin/sh
# Packs what the realm needs that is built from the game client and so never
# goes in the public repo or on GitHub's build machines: the generated DBCs
# the compose override bind-mounts, mod-individual-progression's optional
# DBCs, and the player patch (zip + launcher manifest + realmlist.wtf).
# With WORLD=1 it also dumps acore_world from the running ac-database (the
# dev box owns the world DB, see docs/deploy.md).
#
#   tools/build/gamedata-bundle.sh OUT_DIR           -> nekocore-gamedata.tar.gz
#   WORLD=1 tools/build/gamedata-bundle.sh OUT_DIR   ... + acore_world.sql.gz
#
# `nekocore publish` runs it and uploads the result to the data
# repository's release; `nekocore update` on the realm box fetches it.
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?usage: gamedata-bundle.sh OUT_DIR}
WORLD=${WORLD:-0}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

# The patch zip must be from the same build as the DBCs (sets PATCH_ZIP, PATCH_MANIFEST).
. "$REPO/tools/server/check_patch_zip.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data/generated" "$T/client-patch" "$T/website/downloads"
# Every data/generated file the override mounts, read from the override itself:
# a mounted file missing on the box makes docker create an empty directory in
# its place, and the worldserver can't load that DBC.
for rel in $(grep -oE '"\.\./data/generated/[^:"]+' "$REPO/server-conf/docker-compose.override.yml" | sed 's|^"\.\./data/generated/||' | sort -u); do
    [ -f "$REPO/data/generated/$rel" ] || { echo "error: the override mounts data/generated/$rel but it doesn't exist" >&2; exit 1; }
    mkdir -p "$T/data/generated/$(dirname "$rel")"
    cp "$REPO/data/generated/$rel" "$T/data/generated/$rel"
done
cp -a "$REPO/client-patch/progression-optional" "$T/client-patch/progression-optional"
cp "$PATCH_ZIP" "$PATCH_MANIFEST" "$REPO/website/downloads/realmlist.wtf" "$T/website/downloads/"
tr -d '[:space:]' < "$REPO/data/generated/patch-version.txt" > "$T/PATCH_VERSION"
tar -C "$T" -czf "$OUT/nekocore-gamedata.tar.gz" .
(cd "$OUT" && sha256sum nekocore-gamedata.tar.gz > nekocore-gamedata.tar.gz.sha256)
echo "$OUT/nekocore-gamedata.tar.gz ($(du -h "$OUT/nekocore-gamedata.tar.gz" | cut -f1), patch $(cat "$T/PATCH_VERSION"))"

if [ "$WORLD" = "1" ]; then
    pw=$(grep -E '^DOCKER_DB_ROOT_PASSWORD=' "$REPO/server/.env" | tail -1 | cut -d= -f2-)
    [ -n "$pw" ] || { echo "error: DOCKER_DB_ROOT_PASSWORD missing from server/.env" >&2; exit 1; }
    docker exec ac-database true 2>/dev/null || { echo "error: ac-database isn't running -- start the dev realm for WORLD=1" >&2; exit 1; }
    docker exec ac-database mysqldump -uroot -p"$pw" --single-transaction --quick --routines --triggers --events acore_world 2>/dev/null \
        | gzip > "$OUT/acore_world.sql.gz.partial"
    mv "$OUT/acore_world.sql.gz.partial" "$OUT/acore_world.sql.gz"
    (cd "$OUT" && sha256sum acore_world.sql.gz > acore_world.sql.gz.sha256)
    echo "$OUT/acore_world.sql.gz ($(du -h "$OUT/acore_world.sql.gz" | cut -f1))"
fi

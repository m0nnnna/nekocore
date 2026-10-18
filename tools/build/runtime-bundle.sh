#!/usr/bin/env bash
# Packs the runtime tree a realm box needs next to the images: compose files,
# server and module confs, Lua scripts, module SQL, the ops scripts and the
# `nekocore` command, laid out like /opt/nekocore. No secrets and no game
# data go in it (those stay on the box / come from the private data release).
#
#   tools/build/runtime-bundle.sh OUT_DIR VERSION
#     -> OUT_DIR/nekocore-runtime.tar.gz (+ .sha256)
#
# Needs a prepared server/ (tools/build/prepare-server.sh). GitHub Actions
# attaches the result to every release; `nekocore update` unpacks it.
set -euo pipefail
REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
OUT=${1:?usage: runtime-bundle.sh OUT_DIR VERSION}
VERSION=${2:?usage: runtime-bundle.sh OUT_DIR VERSION}
S="$REPO/server"
[ -f "$S/docker-compose.override.yml" ] || { echo "runtime-bundle: run tools/build/prepare-server.sh first" >&2; exit 1; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
R="$T/nekocore"

mkdir -p "$R/server/conf/dist" "$R/server/env/dist" "$R/data" "$R/tools" "$R/bin" "$R/website"
cp "$S/docker-compose.yml" "$S/docker-compose.override.yml" "$R/server/"
cp "$S/conf/dist/env.ac" "$R/server/conf/dist/"
cp "$REPO/server-conf/env.example" "$R/server/.env.example"
cp -a "$S/env/dist/etc" "$R/server/env/dist/etc"
find "$R/server/env/dist/etc" -name '*.bak*' -delete
# The repo copies carry no TOTPMasterSecret; `nekocore update` puts the box's back.
for f in worldserver authserver dbimport; do cp "$REPO/server-conf/$f.conf" "$R/server/env/dist/etc/$f.conf"; done
cp -a "$S/env/dist/lua_scripts" "$R/server/env/dist/lua_scripts"
cp -a "$REPO/data/sql" "$R/data/sql"
cp -a "$REPO/tools/server" "$R/tools/server"
rm -rf "$R/tools/server/__pycache__"
cp "$REPO/bin/nekocore" "$R/bin/"
cp "$REPO/website/docker.env.example" "$R/website/"
printf '%s\n' "$VERSION" > "$R/VERSION"
git -C "$REPO" rev-parse HEAD > "$R/COMMIT"

tar -C "$T" -czf "$OUT/nekocore-runtime.tar.gz" nekocore
(cd "$OUT" && sha256sum nekocore-runtime.tar.gz > nekocore-runtime.tar.gz.sha256)
echo "$OUT/nekocore-runtime.tar.gz ($(du -h "$OUT/nekocore-runtime.tar.gz" | cut -f1), $VERSION)"

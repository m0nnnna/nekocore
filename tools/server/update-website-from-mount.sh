#!/bin/sh
# Updates ONLY the website on an existing NekoCore production install from
# the drop on the deploy share -- the realm keeps running. Run ON the box:
#
#   sh /opt/nekocore/update-website-from-mount.sh
#
# What it does:
#   1. Copies website/downloads (client patch zip, realmlist.wtf) and
#      docker.env.example from the mount. Does NOT touch website/docker.env
#      (this box's own settings: SMTP login, Discord link, ...).
#   2. `docker load`s images/website.tar only.
#   3. Recreates just neko-website. ac-worldserver / ac-authserver /
#      ac-database are never stopped -- use update-from-mount.sh for
#      anything that touches the servers or databases.
#
# Safe to re-run. Portable /bin/sh.

set -eu

SOURCE_DIR="${SOURCE_DIR:-/mnt/deploy/nekocore-deploy}"
DEST_DIR="${DEST_DIR:-/opt/nekocore}"

[ -f "$SOURCE_DIR/images/website.tar" ] || { echo "error: $SOURCE_DIR/images/website.tar not found -- is the share mounted?" >&2; exit 1; }
[ -f "$DEST_DIR/website/docker.env" ] || { echo "error: $DEST_DIR/website/docker.env missing -- not an existing install; use install-from-mount.sh" >&2; exit 1; }

echo "==> copying website files (docker.env untouched)"
mkdir -p "$DEST_DIR/website/downloads"
cp -a "$SOURCE_DIR/tree/website/downloads/." "$DEST_DIR/website/downloads/"
cp "$SOURCE_DIR/tree/website/docker.env.example" "$DEST_DIR/website/" 2>/dev/null || true
cp "$SOURCE_DIR/update-website-from-mount.sh" "$DEST_DIR/" 2>/dev/null || true

echo "==> loading website image"
docker load -i "$SOURCE_DIR/images/website.tar"

echo "==> recreating neko-website"
cd "$DEST_DIR/server"
docker compose up -d --force-recreate --no-deps neko-website

echo "==> done"
docker compose ps neko-website

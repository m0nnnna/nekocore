#!/bin/sh
# Website-only counterpart of build_deploy_drop.sh: rebuilds the website
# image and refreshes just the website parts of the drop on the deploy
# share. Pairs with update-website-from-mount.sh on the box, so a site fix
# never needs DB dumps, the other images, or a realm restart. Run from the
# repo root in Git Bash:
#
#   sh tools/server/build_website_drop.sh                # -> Y:/nekocore-deploy
#   SKIP_BUILD=1 sh tools/server/build_website_drop.sh   # save the image as-is
#
# Still add a line to the drop's README by hand.

set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DROP_DIR="${DROP_DIR:-/y/nekocore-deploy}"
SKIP_BUILD="${SKIP_BUILD:-0}"

[ -d "$DROP_DIR" ] || { echo "error: $DROP_DIR not found -- is the share mounted?" >&2; exit 1; }
. "$REPO/tools/server/check_patch_zip.sh"

if [ "$SKIP_BUILD" != "1" ]; then
    echo "==> building nekocore/website:latest"
    (cd "$REPO/server" && docker compose build neko-website)
fi

echo "==> image -> $DROP_DIR/images/website.tar"
mkdir -p "$DROP_DIR/images"
docker save -o "$DROP_DIR/images/website.tar" nekocore/website:latest
du -h "$DROP_DIR/images/website.tar" | cut -f1

echo "==> website tree -> $DROP_DIR/tree/website"
mkdir -p "$DROP_DIR/tree/website/downloads"
cp "$REPO/website/docker.env" "$REPO/website/docker.env.example" "$REPO/website/docker-compose.website.yml" "$DROP_DIR/tree/website/"
cp "$REPO/website/downloads/realmlist.wtf" "$DROP_DIR/tree/website/downloads/"
cp "$PATCH_ZIP" "$DROP_DIR/tree/website/downloads/"
cp "$REPO/tools/server/update-website-from-mount.sh" "$DROP_DIR/"

echo "==> done: $(date '+%Y-%m-%d %H:%M')"
echo "    on the box: sh /mnt/deploy/nekocore-deploy/update-website-from-mount.sh"
echo "    and note the change in $DROP_DIR/README.md"

# Sourced by build_deploy_drop.sh and build_website_drop.sh (expects $REPO).
# The site's "Get the patch" button serves website/downloads/nekocore-patch.zip,
# so a drop must carry one, and it must not predate the DBCs/addons it ships:
# a stale patch gives players spells/talents the realm doesn't match.

PATCH_ZIP="$REPO/website/downloads/nekocore-patch.zip"
PATCH_REBUILD="python tools/install_patch/install_client.py --wotlk-root <client> --bundle-zip website/downloads/nekocore-patch.zip"

if [ ! -f "$PATCH_ZIP" ]; then
    echo "error: $PATCH_ZIP missing -- the site links it. Build it: $PATCH_REBUILD" >&2
    exit 1
fi
stale=$( { find "$REPO/data/generated" -name '*.dbc' -newer "$PATCH_ZIP"
           find "$REPO/client-patch/Interface" -type f -newer "$PATCH_ZIP"; } | head -5)
if [ -n "$stale" ]; then
    echo "error: $PATCH_ZIP is older than:" >&2
    echo "$stale" | sed 's/^/    /' >&2
    echo "rebuild it first: $PATCH_REBUILD" >&2
    exit 1
fi

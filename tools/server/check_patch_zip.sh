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
           find "$REPO/client-patch/Interface" -type f -newer "$PATCH_ZIP"
           # the Questie fork install_client.py stages into the zip (fetch.py pin)
           [ -d "$REPO/third-party/Questie-NekoCore" ] && \
               find "$REPO/third-party/Questie-NekoCore" -name .git -prune -o -type f -newer "$PATCH_ZIP" -print; } | head -5)
if [ -n "$stale" ]; then
    echo "error: $PATCH_ZIP is older than:" >&2
    echo "$stale" | sed 's/^/    /' >&2
    echo "rebuild it first: $PATCH_REBUILD" >&2
    exit 1
fi

# The launcher manifest and the version the realm checks against must come
# from the same build as the zip (install_client.py writes all three), or
# the realm tells every player with the new patch to update.
PATCH_MANIFEST="$REPO/website/downloads/nekocore-patch.json"
PATCH_VERSION_FILE="$REPO/data/generated/patch-version.txt"
for f in "$PATCH_MANIFEST" "$PATCH_VERSION_FILE"; do
    [ -f "$f" ] || { echo "error: $f missing -- rebuild the patch: $PATCH_REBUILD" >&2; exit 1; }
done
manifest_version=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$PATCH_MANIFEST")
realm_version=$(tr -d '[:space:]' < "$PATCH_VERSION_FILE")
if [ "$manifest_version" != "$realm_version" ]; then
    echo "error: launcher manifest says patch $manifest_version, the realm expects $realm_version" >&2
    echo "rebuild the patch: $PATCH_REBUILD" >&2
    exit 1
fi

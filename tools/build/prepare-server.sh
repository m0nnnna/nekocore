#!/usr/bin/env bash
# Puts together the AzerothCore tree nekocore builds, from this repo alone:
#
#   1. AzerothCore at build/azerothcore.lock's commit -> server/
#   2. core-patches/*.patch on top, in filename order
#   3. the third-party mods at their pinned commits, plus third-party-patches/
#      (tools/third_party/fetch.py)
#   4. our hand-written modules (modules/) and the nekocore module itself
#      (tools/server/sync_module.py)
#   5. the runtime config: server-conf/ -> server/ (compose override,
#      worldserver/authserver/dbimport.conf, module confs), Lua scripts and
#      the third-party .conf.dist files (tools/server/stage_third_party.py)
#
# GitHub Actions runs it on a clean checkout before building the images; on
# the dev box it brings an existing server/ in line (steps that are already
# done are skipped, so it is safe to re-run). After it:
#   cd server && docker compose build     # images tagged :local
#
#   tools/build/prepare-server.sh            # everything
#   tools/build/prepare-server.sh --source   # 1-4 only (what the images need)
#   tools/build/prepare-server.sh --check    # dev box: is server/ what the repo says?
set -euo pipefail
REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
SERVER="$REPO/server"
MODE=${1:-all}
PY=${PYTHON:-python3}
cd "$REPO"
# shellcheck source=../../build/azerothcore.lock
. build/azerothcore.lock

say() { printf '==> %s\n' "$*"; }
die() { echo "prepare-server: $*" >&2; exit 1; }

if [ "$MODE" = "--check" ]; then
	# The dev box's server/ must hold exactly what CI will build, or a release
	# ships something other than what was tested here.
	bad=0
	base=$(git -C "$SERVER" merge-base HEAD "$AC_COMMIT" 2>/dev/null || true)
	[ "$base" = "$AC_COMMIT" ] || { echo "server/ is not based on AC_COMMIT $AC_COMMIT"; bad=1; }
	for p in core-patches/*.patch; do
		git -C "$SERVER" apply --reverse --check "$REPO/$p" 2>/dev/null || { echo "core patch not applied: $p"; bad=1; }
	done
	"$PY" - "$REPO" <<-'EOF' || bad=1
		import subprocess, sys
		sys.path.insert(0, sys.argv[1] + "/tools/third_party")
		from fetch import MODS, dest_for
		bad = False
		for name, (url, commit, kind) in MODS.items():
		    d = dest_for(name)
		    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
		    if head != commit:
		        print(f"{name}: at {head[:12] or 'missing'}, lock says {commit[:12]}"); bad = True
		sys.exit(1 if bad else 0)
	EOF
	for m in modules/*/; do
		diff -rq "$m" "$SERVER/modules/$(basename "$m")" >/dev/null || { echo "modules/$(basename "$m") differs from server/modules"; bad=1; }
	done
	[ $bad = 0 ] && echo "server/ matches the repo" || exit 1
	exit 0
fi

say "AzerothCore $AC_COMMIT"
if [ ! -d "$SERVER/.git" ]; then
	git init -q "$SERVER"
	git -C "$SERVER" remote add origin "$AC_REPO"
	git -C "$SERVER" fetch -q --depth 1 origin "$AC_COMMIT"
	git -C "$SERVER" -c advice.detachedHead=false checkout -q FETCH_HEAD
elif ! git -C "$SERVER" merge-base --is-ancestor "$AC_COMMIT" HEAD 2>/dev/null; then
	die "server/ exists but isn't based on $AC_COMMIT -- move it aside or check that commit out"
fi

say "core patches"
for p in core-patches/*.patch; do
	if git -C "$SERVER" apply --reverse --check "$REPO/$p" 2>/dev/null; then
		echo "    $(basename "$p"): already applied"
	else
		git -C "$SERVER" apply "$REPO/$p"
		echo "    $(basename "$p"): applied"
	fi
done

say "third-party mods"
"$PY" tools/third_party/fetch.py

say "our modules"
for m in modules/*/; do
	name=$(basename "$m")
	rm -rf "${SERVER:?}/modules/$name"
	cp -a "$m" "$SERVER/modules/$name"
	echo "    $name"
done
"$PY" tools/server/sync_module.py >/dev/null
echo "    nekocore (src/, data/sql/, conf/)"

[ "$MODE" = "--source" ] && { say "source ready in $SERVER"; exit 0; }

say "runtime config"
cp server-conf/docker-compose.override.yml "$SERVER/"
mkdir -p "$SERVER/env/dist/etc/modules"
for f in worldserver authserver dbimport; do
	# Keep the box's own copy if it has one: it carries TOTPMasterSecret,
	# which the repo copy leaves blank.
	if [ -f "$SERVER/env/dist/etc/$f.conf" ]; then
		secret=$(grep -E '^TOTPMasterSecret *=' "$SERVER/env/dist/etc/$f.conf" | head -1 | sed -E 's/^[^=]*= *//' || true)
	else
		secret=""
	fi
	cp "server-conf/$f.conf" "$SERVER/env/dist/etc/$f.conf"
	[ -z "$secret" ] || sed -i -E "s/^(TOTPMasterSecret *=).*/\1 $secret/" "$SERVER/env/dist/etc/$f.conf"
done
cp server-conf/modules/*.conf "$SERVER/env/dist/etc/modules/"
"$PY" tools/server/stage_third_party.py lua confs settings
say "ready: cd server && docker compose build"

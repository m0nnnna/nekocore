#!/usr/bin/env bash
# Records the SpellScripts the worldserver refused to bind to an era spell,
# for build_era_spell_sql.py to stop cloning onto that spell.
#
# At startup the core checks every script handler against the effect it
# names and logs, for each one that does not fit:
#
#   Spell `301464` Effect `Index: EFFECT_0 Name: 3` of script `spell_warr_slam`
#   did not match dbc effect data - handler bound to hook ... won't be executed
#
# It also logs a script whose Validate() rejects the spell outright ("did
# not pass Validate() function of script") -- WotLK Holy Shock demands a
# rank of WotLK's own chain -- and those pairs are recorded as well.
#
# For an effect mismatch it then runs the REST of that script anyway. On an era clone whose
# effects changed that is half a WotLK script on a spell it was not written
# for, so the generator drops the whole script from that spell. See
# load_script_mismatches in build_era_spell_sql.py.
#
# Reads the log of the CURRENT worldserver run only (since its container
# last started), and MERGES into the existing list rather than replacing it:
# a pair that was dropped no longer produces a log line, and must not come
# back on the next dump just because it went quiet.
#
# Run from anywhere; writes data/generated/era-script-mismatches.txt.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$REPO/data/generated/era-script-mismatches.txt"

STARTED="$(docker inspect -f '{{.State.StartedAt}}' ac-worldserver)"
if ! docker logs --since "$STARTED" ac-worldserver 2>&1 | grep -q "World Initialized"; then
    echo "refusing: the current worldserver run has not reached 'World Initialized' yet" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
touch "$OUT"
BEFORE="$(grep -c . "$OUT" || true)"

{
    cat "$OUT"
    docker logs --since "$STARTED" ac-worldserver 2>&1 \
        | sed 's/\x1b\[[0-9;]*m//g' \
        | sed -nE -e 's/^Spell `([34][0-9]{5})` Effect .* of script `([A-Za-z0-9_]+)` did not match dbc effect data.*/\1 \2/p' \
                 -e 's/.*Spell `([34][0-9]{5})` did not pass Validate\(\) function of script `([A-Za-z0-9_]+)`.*/\1 \2/p'
} | sort -u -k1,1n -k2,2 > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

echo "wrote $OUT ($(grep -c . "$OUT") era spell/script pair(s), $BEFORE before)"

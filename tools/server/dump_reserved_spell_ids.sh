#!/usr/bin/env bash
# Dumps every spell id the realm defines SERVERSIDE, for build_era_spells.py
# to refuse to collide with.
#
# AzerothCore loads the `spell_dbc` world table into sSpellStore AFTER
# Spell.dbc (DBCStores.cpp: LOAD_DBC(sSpellStore, "Spell.dbc", "spell_dbc")),
# so a row there wins over the same id in our generated file -- silently.
# The live realm already had six such ids sitting on era clone ids, in the
# 100000-200000 band that is conventionally used for exactly this. The era
# offsets were moved clear of it; this list is how a future addition gets
# caught at build time rather than as a spell that mysteriously stopped
# behaving like its era.
#
# Also dumps the realm's spell rank chains (`spell_ranks`), which the same
# build needs for a different reason: an era has to clone a rank chain whole
# or not at all. Some ranks are reachable in an era's SkillLineAbility and
# others are not (Pummel and Nature Resist rank 1 have no row in either era
# client), which would otherwise leave that era's chain with a hole in it.
#
# Run from anywhere; writes data/generated/reserved-spell-ids.txt and
# data/generated/spell-rank-chains.txt.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$REPO/data/generated/reserved-spell-ids.txt"
CHAINS="$REPO/data/generated/spell-rank-chains.txt"
ENV_FILE="$REPO/server/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "no $ENV_FILE -- run this against a checkout with the server stack" >&2
    exit 1
fi
PASS="$(sed -n 's/\r$//;s/^DOCKER_DB_ROOT_PASSWORD=//p' "$ENV_FILE")"

mkdir -p "$(dirname "$OUT")"
docker exec -e MYSQL_PWD="$PASS" ac-database mysql -uroot -N \
    -e "SELECT Id FROM acore_world.spell_dbc ORDER BY Id;" 2>/dev/null \
    | grep -E '^[0-9]+$' > "$OUT"

echo "wrote $OUT ($(wc -l < "$OUT") serverside spell ids, max $(tail -1 "$OUT"))"

docker exec -e MYSQL_PWD="$PASS" ac-database mysql -uroot -N --batch \
    -e "SELECT first_spell_id, spell_id FROM acore_world.spell_ranks ORDER BY first_spell_id, \`rank\`;" 2>/dev/null \
    | grep -E '^[0-9]+	[0-9]+$' > "$CHAINS"

echo "wrote $CHAINS ($(wc -l < "$CHAINS") rank-chain members)"

"""
Clones the world database's spell-keyed rows onto the era spell ids that
build_era_spells.py invented.

Why this is needed at all: a Spell.dbc row is only half of what a spell is
on AzerothCore. The other half lives in the world database, keyed by spell
id -- rank chains, spell power coefficients, proc definitions, the NAME of
the C++ SpellScript that implements it, cooldown overrides, and so on. A
clone at id 300133 inherits none of that from 133, so without this pass a
Vanilla Fireball would have no rank chain, no spell power scaling, and any
scripted behaviour would simply not run.

Every table below is keyed by spell id in a known column, so the clone is
mechanical: copy the row, rewrite the spell-id columns through the id map,
leave everything else alone. That is deliberately ALL this tool does -- it
never invents values, so a clone's proc chance or coefficient is exactly
the one the live realm already uses for the WotLK spell. Where an era
genuinely wants a different coefficient, that is a later, per-spell
decision, not something to guess at here.

Columns that hold a spell id are rewritten, and each table says which of
its columns those are. Two different kinds:

  * The row's OWN key (spell_ranks.spell_id, spell_proc.SpellId, ...) --
    always rewritten to the clone.
  * A REFERENCE to another spell (spell_ranks.first_spell_id,
    spell_linked_spell.spell_effect, spell_required.req_spell). These are
    rewritten to that spell's clone IN THE SAME ERA when it has one, and
    otherwise left pointing at the shared WotLK id -- which is correct,
    because a spell with no clone is one whose era version was identical to
    WotLK's, so the WotLK id already IS this era's version.

Output is a single idempotent .sql file: each table's era rows are deleted
by id range and re-inserted, so re-running a build never doubles rows up.

It belongs in data/sql/db-world/base/. AzerothCore's db-import scans
modules/*/data/sql/db-{world,characters,auth}/{base,updates} -- a file
under data/sql/world/base/ is simply never seen, which is a silent way to
have a generated file that looks applied and is not.

Usage:
    python build_era_spell_sql.py \\
        --id-map data/generated/era-spell-map.json \\
        --out data/sql/db-world/base/zzz_nekocore_era_spells.sql
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dbc"))
from wdbc import LOCALE_COUNT, read_dbc  # noqa: E402
from schemas import BUILD_SCHEMAS  # noqa: E402

# table -> (columns holding THIS row's spell id, columns REFERENCING another spell)
#
# Only tables whose rows are genuinely per-spell are here. Deliberately
# left out, with reasons, so the omissions are decisions rather than
# oversights:
#   spell_area          - binds a spell to a world area/quest; an era clone
#                         is granted by our own code, not by zone entry.
#   spell_dbc           - the realm's own serverside spell rows. Cloning
#                         these would fight the core for ids it owns.
#   spell_scripts       - keyed by a script id, not a spell id.
#   spell_loot_template - loot, not spell behaviour.
SPELL_TABLES: dict[str, tuple[list[str], list[str]]] = {
    # trainer_spell IS cloned, though the first attempt deliberately did not
    # clone it -- the thinking was that a runtime hook could rewrite the
    # displayed spell id per viewer instead, so one set of rows could serve
    # every era. Live testing killed that idea twice over:
    #
    #   * Buying silently failed. The client sends the DISPLAYED id back in
    #     CMSG_TRAINER_BUY_SPELL and Trainer::TeachSpell resolves it with
    #     GetSpell() against the trainer's own rows, so an id that is not
    #     really on the trainer matches nothing and does nothing.
    #   * Tooltips lied. The client renders the tooltip from its own
    #     Spell.dbc for whatever id the list carries, so a Vanilla
    #     character was shown WotLK Frostbolt's cost (6% of base mana, 11
    #     at low level) and then received the Vanilla one at a flat 25.
    #
    # Giving the trainer real era rows fixes both at the source, and the
    # runtime hook shrinks to dropping the entries that are not the
    # viewer's era. ReqAbility1-3 name other spells and are remapped with
    # everything else.
    "trainer_spell": (["SpellId"], ["ReqAbility1", "ReqAbility2", "ReqAbility3"]),
    # spell_ranks is NOT copied through the generic path -- see
    # emit_spell_ranks. Copying it row-for-row would give an era a chain
    # whose head is a WotLK spell id.
    "spell_bonus_data": (["entry"], []),
    "spell_proc": (["SpellId"], []),
    "spell_proc_event": (["entry"], []),
    "spell_script_names": (["spell_id"], []),
    "spell_custom_attr": (["spell_id"], []),
    "spell_group": (["spell_id"], []),
    "spell_linked_spell": (["spell_trigger"], ["spell_effect"]),
    "spell_required": (["spell_id"], ["req_spell"]),
    "spell_target_position": (["ID"], []),
    "spell_cooldown_overrides": (["Id"], []),
    "spell_threat": (["entry"], []),
    "spell_pet_auras": (["spell"], ["aura"]),
    "spell_cone": (["ID"], []),
    "spell_mixology": (["entry"], []),
}

# Tables this generator once cloned and no longer does. Their era rows are
# still DELETEd so a database that got the bad rows is cleaned up by
# re-applying, rather than keeping them until someone notices.
#
# spell_enchant_proc_data: `entry` is a SpellItemEnchantment id, NOT a
#   spell id -- it was in the clone list by mistake, and the worldserver
#   said so plainly on startup ("Enchancment 300324 listed in
#   `spell_enchant_proc_data` does not exist", 12 of them). An enchantment
#   has no era variant to point at.
CLEANUP_ONLY_TABLES = {"spell_enchant_proc_data": "entry"}

# Columns whose id is SIGNED, where the sign carries meaning and has to
# survive the rewrite. Found by auditing every id column this tool touches
# for negative values, after two separate bugs came from assuming a column
# held a plain positive spell id.
#
#   spell_linked_spell.spell_trigger  negative = "when this aura is removed"
#   spell_proc.SpellId                negative = "every rank of this spell"
#   spell_proc_event.entry            negative = "every rank of this spell"
#   spell_script_names.spell_id       negative = "every rank of this spell"
#
# The last three matter more than they look. Dropping the sign turned
# "this script/proc applies to the whole Fireball chain" into "it applies
# to Vanilla Fireball rank 1 only", silently, with no startup complaint --
# every higher rank quietly lost its scripted behaviour. 197 + 174 + 191
# rows carry a negative id.
SIGNED_COLUMNS = {
    "spell_linked_spell": {"spell_trigger"},
    "spell_proc": {"SpellId"},
    "spell_proc_event": {"entry"},
    "spell_script_names": {"spell_id"},
}

# Tables where a NEGATIVE key is not a spell at all, and the row must be
# skipped rather than cloned.
#
# spell_group.spell_id: negative means "this group also contains everything
#   in group N". 75 rows are like that. Cloning one as though the number
#   were a spell id produced entries such as (1084, 301075) out of
#   (1084, -1075) -- a mid-chain era spell where the core expects a chain
#   head, which it rejected with "listed in `spell_group` is not first rank
#   of spell". A group-to-group reference has no era of its own; the
#   membership it points at is cloned on its own account.
GROUP_REFERENCE_KEYS = {"spell_group": "spell_id"}

ERA_RANGES = {"Vanilla": (300_000, 399_999), "TBC": (400_000, 499_999)}

# Scripts that do not depend on the spell's effect layout, so they are right
# on ANY version of the spell and are cloned onto ported spells too.
# isAllowedToCastSpell is mod-individual-progression's Naxx40 "Corrupted
# Mind" check (blocks healing on Loatheb), keyed purely on the spell id.
ERA_AGNOSTIC_SCRIPTS = {"isAllowedToCastSpell"}

PROC_TABLES = {"spell_proc", "spell_proc_event"}

# Hand-written handlers (src/EraSpellScripts.cpp) for era spells whose
# behaviour the Vanilla/TBC core hardcoded behind a DUMMY effect. Keyed by
# era and ORIGINAL spell id; emitted onto that era's copy after the cloned
# rows, so the per-era DELETE above cannot wipe them.
ERA_SCRIPTS = {
    ("Vanilla", 20271): "spell_era_pal_judgement",
    ("TBC", 20271): "spell_era_pal_judgement",
    ("TBC", 34074): "spell_era_hun_aspect_of_the_viper",
    # Cold Snap: Vanilla's is 12472 (WotLK Icy Veins), TBC's is 11958.
    ("Vanilla", 12472): "spell_era_mag_cold_snap",
    ("TBC", 11958): "spell_era_mag_cold_snap",
    # Negative: every rank of the chain, like the core's own negative ids.
    ("Vanilla", -20473): "spell_era_pal_holy_shock",
    ("TBC", -20473): "spell_era_pal_holy_shock",
    # Vanilla Sweeping Strikes is 12292 (WotLK Death Wish). Its era row is a
    # DUMMY aura in EFFECT_0 that procs on melee, the exact shape WotLK's own
    # handler binds to, so the stock script serves it unchanged.
    ("Vanilla", 12292): "spell_warr_sweeping_strikes",
    # Furor's shapeshift half, on the forms it fires from.
    ("Vanilla", 768): "spell_era_dru_furor",
    ("Vanilla", 5487): "spell_era_dru_furor",
    ("Vanilla", 9634): "spell_era_dru_furor",
    ("TBC", 768): "spell_era_dru_furor",
    ("TBC", 5487): "spell_era_dru_furor",
    ("TBC", 9634): "spell_era_dru_furor",
    ("TBC", -18213): "spell_era_warl_improved_drain_soul",
    # Seal of Righteousness: a melee-hit dummy the 1.12 core turned into
    # damage by weapon speed. WotLK's spell_pal_seal_of_righteousness uses
    # the 3.0 formula, and was only ever on rank 1 -- ranks 2-8, ported from
    # the era, did nothing at all on hit.
    ("Vanilla", 20154): "spell_era_pal_seal_of_righteousness",
    ("Vanilla", 21084): "spell_era_pal_seal_of_righteousness",
    **{("Vanilla", s): "spell_era_pal_seal_of_righteousness"
       for s in (20287, 20288, 20289, 20290, 20291, 20292, 20293)},
    # Divine Shield, Divine Protection, Blessing of Protection: the era's
    # 1-minute Forbearance and no Avenging Wrath marker, in place of WotLK's
    # spell_pal_immunities.
    **{("Vanilla", s): "spell_era_pal_immunities" for s in (642, 1020, 498, 5573, 1022, 5599, 10278)},
}

# Era copies that must run NONE of the WotLK spell's scripts, and need no
# handler of their own: the era spell is complete as data. Keyed by era and
# ORIGINAL spell id. Vanilla Lay on Hands neither gave nor checked
# Forbearance, and had no Avenging Wrath to check; WotLK's
# spell_pal_lay_on_hands does both.
ERA_NO_WOTLK_SCRIPTS = {("Vanilla", 633), ("Vanilla", 2800), ("Vanilla", 10310)}

# ERA_SCRIPTS handlers that run NEXT TO the clone's stock scripts instead of
# replacing them: Furor rides on the druid forms, which keep WotLK's own
# spell_dru_feral_swiftness.
ERA_SCRIPTS_ALONGSIDE = {"spell_era_dru_furor"}

# spell_proc rows kept on an era clone although its effects changed: the
# row describes WHEN the talent fires (a kill, by Drain Soul) and still
# holds, and the WotLK script that used to read it is replaced by an
# ERA_SCRIPTS handler. Keyed by era and ORIGINAL spell id.
ERA_KEEP_PROCS = {("TBC", 18213)}


def effect_layout(row: dict) -> tuple:
    return tuple((row[f"Effect_{i}"], row[f"EffectAura_{i}"]) for i in range(3))


def load_clone_facts(spell_dbc: Path, maps: dict[str, dict[int, int]]) -> tuple[set[int], set[int]]:
    """(clones whose effect layout differs from the WotLK spell they were
    cloned from, clones with no proc flags of their own).

    Drives which proc rows are cloned. spell_proc/spell_proc_event rows are
    overrides of a spell's DBC proc data written for the WotLK spell's
    layout; on a clone whose layout changed they describe a proc the era
    version does not have (Vanilla Recklessness has no charges to consume,
    Lightwell Renew no hit counter), so the era's own DBC proc data is left
    in charge instead. And a row with no ProcFlags on a spell with none is
    one the core itself discards ("proc will not be triggered") -- 20 of
    those were logged at every startup.
    """
    rows = {r["ID"]: r for r in read_dbc(spell_dbc, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"],
                                          LOCALE_COUNT["3.3.5a"]).rows}
    changed, no_flags = set(), set()
    for mapping in maps.values():
        for base, clone in mapping.items():
            c, w = rows.get(clone), rows.get(base)
            if c is None:
                continue
            if w is None or effect_layout(c) != effect_layout(w):
                changed.add(clone)
            if not c["ProcTypeMask"]:
                no_flags.add(clone)
    return changed, no_flags


def load_script_mismatches(path: Path) -> set[tuple[int, str]]:
    """(era spell, ScriptName) pairs the worldserver refused to bind, from
    tools/server/dump_era_script_mismatches.sh.

    A WotLK SpellScript binds each handler to an effect index and type;
    the core checks that against the spell and skips a handler that does
    not fit ("did not match dbc effect data"), but still runs the rest of
    the script. On an era clone whose effects moved that leaves half a
    script -- Sweeping Strikes's proc check on Vanilla Death Wish -- so a
    script the core rejected any part of is not cloned onto that spell at
    all. The core's verdict, not a guess: it is the one party that knows
    which effect each handler wants.
    """
    out: set[tuple[int, str]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                out.add((int(parts[0]), parts[1]))
    return out


def emit_spell_ranks(password: str, maps: dict[str, dict[int, int]], ported: dict[str, set[int]],
                     supersede: dict[str, list[list[int]]]) -> tuple[list[str], int]:
    """Rebuilds each era's rank chains from its own members, rather than
    copying WotLK's rows through the id map.

    A straight copy gets the head wrong wherever WotLK renumbered a chain.
    Water Shield is the clear case: WotLK ADDED ranks 1-6 under new ids
    (52127..52138) and pushed TBC's own two ranks down to 7 and 8. TBC
    never had those new ids, so a copied chain would give the TBC clones
    ranks 7 and 8 under a first_spell_id pointing at 52127 -- a WotLK
    spell, in a chain with no rank 1. The same cross-era leak the talent
    work had to fix in sTalentSpellPosMap, one table over.

    So: take the members of a WotLK chain that this era actually cloned,
    keep WotLK's ordering, and renumber them 1..N within the era. The head
    is then always this era's own lowest rank, and the chain is complete by
    construction. Matches the rank LABELS too -- build_era_spells.py takes
    NameSubtext from the era row for exactly this reason.
    """
    rows = mysql("SELECT first_spell_id, spell_id, `rank` FROM acore_world.spell_ranks "
                 "ORDER BY first_spell_id, `rank`;", password)
    chains: dict[int, list[int]] = {}
    for first, spell, _rank in rows:
        chains.setdefault(int(first), []).append(int(spell))

    lines = ["-- spell_ranks (rebuilt per era, not copied -- see emit_spell_ranks)"]
    for lo, hi in ERA_RANGES.values():
        lines.append(f"DELETE FROM `spell_ranks` WHERE `first_spell_id` BETWEEN {lo} AND {hi};")

    # Ported spells (deleted by WotLK, or at an id WotLK reused) are left
    # out of WotLK's chains -- at a reused id the chain is the OTHER
    # spell's -- and joined by the era's own rank links instead
    # (SkillLineAbility SupercededBySpell, recorded by build_era_spells.py).
    # Both kinds of link run from a lower rank to the next, so each era's
    # chains are the paths through the union of the two.
    values: list[str] = []
    emitted = 0
    for label, mapping in maps.items():
        skip = ported.get(label, set())
        nxt: dict[int, int] = {}
        prev: dict[int, int] = {}

        def link(a: int, b: int) -> None:
            if a == b or a in nxt or b in prev:
                return  # never fork or merge a chain; first link wins
            nxt[a], prev[b] = b, a

        for members in chains.values():
            kept = [m for m in members if m in mapping and m not in skip]
            for a, b in zip(kept, kept[1:]):
                link(a, b)
        for a, b in supersede.get(label, []):
            if a in mapping and b in mapping:
                link(a, b)

        for start in (m for m in nxt if m not in prev):
            chain = [start]
            while chain[-1] in nxt and len(chain) <= 20:
                chain.append(nxt[chain[-1]])
            head = mapping[chain[0]]
            for rank, member in enumerate(chain, start=1):
                values.append(f"({head}, {mapping[member]}, {rank})")
                emitted += 1

    for start in range(0, len(values), 500):
        lines.append("INSERT INTO `spell_ranks` (`first_spell_id`, `spell_id`, `rank`) VALUES")
        lines.append(",\n".join(values[start:start + 500]) + ";")
    lines.append("")
    return lines, emitted


def emit_ported_spell_trainers(password: str, ported: dict[str, dict[str, dict]]) -> tuple[list[str], int, int, int]:
    """Puts the spells WotLK deleted back on the trainers that would have
    sold them.

    Every other table here clones a real row. This one cannot: WotLK has no
    record of a spell WotLK removed, so these rows are built rather than
    copied. What is real, what is derived, and what is invented:

      real      the spell, its class and its level -- read from the era
                client's own Spell.dbc and SkillLineAbility.dbc.
      derived   which trainers stock it. The `trainer` table states this
                outright: Type 0 is a class trainer and Requirement is the
                class id, so a Vanilla Mage spell goes to exactly the NPCs
                the database already calls Mage trainers. Nothing guessed.
      invented  the price, which no surviving data records. Taken as the
                median of what that same trainer charges for spells within
                a few levels, so it matches this realm's own pricing --
                including whatever the optional SQL changed -- instead of a
                formula from nowhere.

    Only CLASS spells get rows, which is the rule asked for. A ported spell
    with no class is skipped and counted: those are the hunter pet skills
    (Great Stamina, Natural Armor), taught to the pet rather than bought.

    Emitted LAST in the file on purpose. The generic pass deletes every era
    id from trainer_spell before re-inserting its clones, so these rows
    have to be written after that has run or they would be wiped by it.
    """
    trainer_class = {int(t): int(req) for t, typ, req in mysql(
        "SELECT Id, Type, Requirement FROM acore_world.trainer;", password) if int(typ) == 0 and int(req)}

    # "Class trainer" in the `trainer` table is broader than "sells class
    # spells": it also covers the starter-zone trainers (stock ends at level
    # 6) and the mage portal trainers (two teleports each). Stocking every
    # ported spell on all of them put level-50 curses in Northshire for a
    # silver. So mirror how the realm already stocks them:
    #   full trainer  -- carries at least half of its class's largest
    #                    trainer inventory: gets every ported spell.
    #   starter       -- tops out by level 10: gets ported spells up to its
    #                    own highest level, the way it stocks living ones.
    #   anything else -- a specialist (portals): gets none.
    stock: dict[int, tuple[int, int]] = {int(t): (int(n), int(top)) for t, n, top in mysql(
        "SELECT TrainerId, COUNT(*), MAX(ReqLevel) FROM acore_world.trainer_spell "
        "WHERE SpellId < 300000 GROUP BY TrainerId;", password)}
    largest: dict[int, int] = {}
    for trainer_id, class_id in trainer_class.items():
        largest[class_id] = max(largest.get(class_id, 0), stock.get(trainer_id, (0, 0))[0])

    def stocks(trainer_id: int, class_id: int, level: int) -> bool:
        count, top = stock.get(trainer_id, (0, 0))
        if count * 2 >= largest[class_id]:
            return True
        return top <= 10 and level <= top

    priced: dict[int, list[tuple[int, int]]] = {}
    for trainer_id, cost, req_level in mysql(
            "SELECT TrainerId, MoneyCost, ReqLevel FROM acore_world.trainer_spell "
            "WHERE SpellId < 300000 AND MoneyCost > 0;", password):
        priced.setdefault(int(trainer_id), []).append((int(req_level), int(cost)))

    lines = ["-- trainer_spell for the spells WotLK deleted (SYNTHESISED -- see"
             " emit_ported_spell_trainers). Must stay after the generic pass."]

    values: list[str] = []
    emitted = 0
    skipped_classless = 0
    skipped_untrainable = 0
    for era_ported in ported.values():
        for info in era_ported.values():
            class_mask = int(info.get("classMask") or 0)
            if not class_mask:
                skipped_classless += 1
                continue
            # Decided by build_era_spells.py, which has the era client open
            # (see untrainable_ported there): talent ranks, procs and
            # automatic grants are ported so they WORK, never to be sold.
            if not info.get("trainable", True):
                skipped_untrainable += 1
                continue
            level = max(1, int(info.get("level") or 1))
            clone = int(info["clone"])
            for trainer_id, class_id in trainer_class.items():
                if not (class_mask & (1 << (class_id - 1))) or not stocks(trainer_id, class_id, level):
                    continue
                cost = median_cost(priced.get(trainer_id, []), level)
                values.append(f"({trainer_id}, {clone}, {cost}, 0, 0, 0, 0, 0, {level}, 0)")
                emitted += 1

    for start_at in range(0, len(values), 500):
        lines.append("INSERT INTO `trainer_spell` (`TrainerId`, `SpellId`, `MoneyCost`, `ReqSkillLine`,"
                     " `ReqSkillRank`, `ReqAbility1`, `ReqAbility2`, `ReqAbility3`, `ReqLevel`,"
                     " `VerifiedBuild`) VALUES")
        lines.append(",\n".join(values[start_at:start_at + 500]) + ";")
    lines.append("")
    return lines, emitted, skipped_classless, skipped_untrainable


def median_cost(priced: list[tuple[int, int]], level: int) -> int:
    """What this trainer charges around this level, widening the window
    until something matches so a sparse trainer still answers from its own
    prices rather than a constant."""
    for window in (3, 6, 12, 100):
        near = sorted(cost for lvl, cost in priced if abs(lvl - level) <= window)
        if near:
            return near[len(near) // 2]
    return 100


def _unescape_batch(field: str) -> str:
    """Undoes the escaping `mysql --batch` applies to its tab-separated
    output. Without this a value containing a backslash comes back with the
    escape still in it and gets escaped a second time on the way out.
    """
    out: list[str] = []
    i = 0
    while i < len(field):
        ch = field[i]
        if ch == "\\" and i + 1 < len(field):
            nxt = field[i + 1]
            out.append({"0": "\0", "n": "\n", "r": "\r", "t": "\t", "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def mysql(sql: str, password: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-e", f"MYSQL_PWD={password}", "ac-database",
         "mysql", "-uroot", "-N", "--batch", "-e", sql],
        capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        if not line or line.startswith("mysql:"):
            continue
        # NULL is printed unescaped and unquoted, so it has to be spotted
        # before unescaping turns it into the four-character string.
        rows.append([f if f == "NULL" else _unescape_batch(f) for f in line.split("\t")])
    return rows


def sql_literal(value: str) -> str:
    if value == "NULL":
        return "NULL"
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id-map", type=Path, default=Path("data/generated/era-spell-map.json"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--env-file", type=Path, default=Path("server/.env"))
    ap.add_argument("--spell-dbc", type=Path, default=Path("data/generated/Spell.dbc"),
                    help="build_era_spells.py's Spell.dbc -- read to tell which clones' effects changed")
    ap.add_argument("--script-mismatches", type=Path, default=Path("data/generated/era-script-mismatches.txt"),
                    help="tools/server/dump_era_script_mismatches.sh output")
    args = ap.parse_args()

    password = ""
    for line in args.env_file.read_text().splitlines():
        if line.startswith("DOCKER_DB_ROOT_PASSWORD="):
            password = line.split("=", 1)[1].strip()
    if not password:
        print(f"error: no DOCKER_DB_ROOT_PASSWORD in {args.env_file}", file=sys.stderr)
        return 2

    id_map: dict[str, dict[str, int]] = json.loads(args.id_map.read_text())["id_map"]
    # era -> {wotlk spell id: clone id}
    maps = {era: {int(k): v for k, v in m.items()} for era, m in id_map.items()}
    total_clones = sum(len(m) for m in maps.values())
    spell_map = json.loads(args.id_map.read_text())
    # Spells ported wholesale from the era client: deleted by WotLK, or at
    # an id WotLK reused for a different spell (build_era_spells.py's
    # is_reused_id). WotLK's rows at such an id describe the OTHER spell --
    # Cold Snap's script on Vanilla Ice Block, Sweeping Strikes's proc on
    # Death Wish -- so none are cloned onto them, and a reference to the id
    # keeps meaning the WotLK spell it was written for.
    ported = {era: {int(k) for k in m} for era, m in spell_map.get("ported", {}).items()}
    clone_maps = {era: {k: v for k, v in m.items() if k not in ported.get(era, set())}
                  for era, m in maps.items()}
    layout_changed, no_proc_flags = load_clone_facts(args.spell_dbc, maps)
    script_mismatches = load_script_mismatches(args.script_mismatches)
    # A clone with a hand-written handler does not also get WotLK's script:
    # the core binds both, and WotLK's spell_mage_cold_snap skips only its
    # own id (11958), so on TBC Cold Snap it would reset its own cooldown.
    replaced_by_era_script = {maps.get(era, {}).get(abs(base)) for (era, base), script in ERA_SCRIPTS.items()
                              if script not in ERA_SCRIPTS_ALONGSIDE}
    replaced_by_era_script |= {maps.get(era, {}).get(base) for era, base in ERA_NO_WOTLK_SCRIPTS}
    # Spell power coefficients build_era_spells.py derived under the era's
    # own rule. An era that has them gets these INSTEAD of WotLK's rows.
    era_bonus: dict[str, dict[int, list[float]]] = {
        era: {int(k): v for k, v in rows.items()} for era, rows in spell_map.get("bonus", {}).items()}
    dropped: dict[str, int] = {}

    lines = [
        "-- GENERATED by tools/build_patch/build_era_spell_sql.py -- do not edit by hand.",
        "--",
        "-- Clones the world DB's spell-keyed rows onto the era spell ids in",
        "-- data/generated/era-spell-map.json. Re-running the generator replaces",
        "-- these rows rather than adding to them: every table is cleared by era id",
        "-- range first, so this file is safe to apply repeatedly.",
        "",
    ]

    for table, key in CLEANUP_ONLY_TABLES.items():
        lines.append(f"-- {table}: era rows removed, never re-added (see CLEANUP_ONLY_TABLES)")
        for lo, hi in ERA_RANGES.values():
            lines.append(f"DELETE FROM `{table}` WHERE `{key}` BETWEEN {lo} AND {hi};")
        lines.append("")

    rank_lines, rank_rows = emit_spell_ranks(password, maps, ported, spell_map.get("supersede", {}))
    lines.extend(rank_lines)
    print(f"  {'spell_ranks':26} rebuilt per era      -> {rank_rows:5} era row(s)", file=sys.stderr)

    summary: list[tuple[str, int, int]] = [("spell_ranks", 0, rank_rows)]
    for table, (own_cols, ref_cols) in SPELL_TABLES.items():
        cols = [c[0] for c in mysql(f"SHOW COLUMNS FROM acore_world.{table};", password)]
        key = own_cols[0]
        rows = mysql(
            f"SELECT {', '.join('`' + c + '`' for c in cols)} FROM acore_world.{table} "
            f"WHERE ABS(`{key}`) < {min(r[0] for r in ERA_RANGES.values())};", password)
        signed = SIGNED_COLUMNS.get(table, set())

        lines.append(f"-- {table}")
        for lo, hi in ERA_RANGES.values():
            lines.append(f"DELETE FROM `{table}` WHERE ABS(`{key}`) BETWEEN {lo} AND {hi};")

        emitted = 0
        values: list[str] = []
        skipped_group_refs = 0
        ref_key = GROUP_REFERENCE_KEYS.get(table)
        for row in rows:
            raw_key = int(row[cols.index(key)])
            if ref_key and raw_key < 0:
                skipped_group_refs += 1
                continue
            base_key = abs(raw_key)
            agnostic = table == "spell_script_names" and row[cols.index("ScriptName")] in ERA_AGNOSTIC_SCRIPTS
            for era, clone_mapping in clone_maps.items():
                mapping = maps[era] if agnostic else clone_mapping
                clone = mapping.get(base_key)
                if clone is None:
                    continue  # this spell has no clone in this era
                if table == "spell_bonus_data" and era in era_bonus:
                    dropped[table] = dropped.get(table, 0) + 1
                    continue
                if table in PROC_TABLES:
                    flags_col = "ProcFlags" if table == "spell_proc" else "procFlags"
                    row_flags = int(row[cols.index(flags_col)]) if flags_col in cols else 0
                    kept = (era, base_key) in ERA_KEEP_PROCS
                    if not kept and (clone in layout_changed or (not row_flags and clone in no_proc_flags)):
                        dropped[table] = dropped.get(table, 0) + 1
                        continue
                if table == "spell_script_names" and (
                        (clone, row[cols.index("ScriptName")]) in script_mismatches
                        or (clone in replaced_by_era_script and not agnostic)):
                    dropped[table] = dropped.get(table, 0) + 1
                    continue
                out_row = list(row)
                for c in own_cols:
                    i = cols.index(c)
                    negative = c in signed and int(row[i]) < 0
                    out_row[i] = str(-clone if negative else clone)
                for c in ref_cols:
                    i = cols.index(c)
                    raw = int(row[i]) if row[i] not in ("NULL", "") else 0
                    if raw:
                        mapped = mapping.get(abs(raw))
                        if mapped is not None:
                            out_row[i] = str(-mapped if raw < 0 else mapped)
                values.append("(" + ", ".join(sql_literal(v) for v in out_row) + ")")
                emitted += 1

        if table == "spell_bonus_data":
            for era, rows_for_era in era_bonus.items():
                for clone, (direct, dot, ap_dot) in sorted(rows_for_era.items()):
                    values.append(f"({clone}, {direct}, {dot}, 0, {ap_dot}, "
                                  f"{sql_literal(era + ' coefficient (build_era_spells.py)')})")
                    emitted += 1
        if values:
            col_list = ", ".join("`" + c + "`" for c in cols)
            for chunk_start in range(0, len(values), 500):
                chunk = values[chunk_start:chunk_start + 500]
                lines.append(f"INSERT INTO `{table}` ({col_list}) VALUES")
                lines.append(",\n".join(chunk) + ";")
        lines.append("")
        summary.append((table, len(rows), emitted))
        note = f"  ({skipped_group_refs} group reference(s) skipped)" if skipped_group_refs else ""
        if dropped.get(table):
            note += f"  ({dropped[table]} dropped: written for the WotLK spell's effects)"
        print(f"  {table:26} {len(rows):5} source row(s) -> {emitted:5} era row(s){note}", file=sys.stderr)

    era_script_values = []
    for (era, base), script in ERA_SCRIPTS.items():
        clone = maps.get(era, {}).get(abs(base))
        if clone is None:
            print(f"error: ERA_SCRIPTS names {era} {base}, which has no era copy", file=sys.stderr)
            return 1
        era_script_values.append(f"({-clone if base < 0 else clone}, {sql_literal(script)})")
    lines.append("-- hand-written era handlers (ERA_SCRIPTS, src/EraSpellScripts.cpp)")
    lines.append("INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`) VALUES")
    lines.append(",\n".join(era_script_values) + ";")
    lines.append("")
    print(f"  {'spell_script_names (era)':26} hand-written         -> {len(era_script_values):5} era row(s)",
          file=sys.stderr)

    ported = json.loads(args.id_map.read_text()).get("ported", {})
    if ported:
        trainer_lines, trainer_rows, classless, untrainable = emit_ported_spell_trainers(password, ported)
        lines.extend(trainer_lines)
        print(f"  {'trainer_spell (ported)':26} synthesised          -> {trainer_rows:5} era row(s)"
              f"  ({classless} classless spell(s) skipped -- pet skills;"
              f" {untrainable} talent/proc/automatic spell(s) skipped)", file=sys.stderr)
        summary.append(("trainer_spell (ported)", 0, trainer_rows))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {args.out}: {sum(s[2] for s in summary)} era rows across "
          f"{len(summary)} tables, for {total_clones} spell clones", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

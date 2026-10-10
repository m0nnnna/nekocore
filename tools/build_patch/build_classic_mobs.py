"""
Brings the abilities of Vanilla 5-man dungeon mobs back to what 1.12.1 had.

Why this exists: mod-individual-progression's dungeon_*.sql rewrites the
SmartAI of every classic dungeon mob from a later (sniffed, WotLK-era) data
set. Against a real 1.12.1 server database (cMaNGOS classic-db) that shows up
three ways, all reported by players:

  * Mobs cast abilities 1.12 never gave them (Irradiated Slime and the other
    Gnomeregan oozes cast Corrosive Ooze; Defias Convicts Rend; a Caverndeep
    Burrower Sunder Armor ...).
  * Abilities that did exist are on the wrong timer (a Scarlet Gallant cast
    Hammer of Justice every 13-22 s; 1.12 had it at 60 s).
  * The spell itself is the WotLK version: Sunder Armor is a trigger for a
    percentage armour debuff, Polymorph lasts 8 s not 20, Net 2 s not 10,
    Shield Bash 6 s not 8.

This tool diffs the realm against the 1.12.1 database and writes
  * data/sql/db-world/base/zzz_nekocore_classic_dungeon_mobs.sql -- deletes
    the casts 1.12 never had, restores 1.12's repeat timers, and points the
    casts that remain at a 1.12 copy of the spell;
  * data/generated/classic-npc-spells.txt -- the spells that need such a copy
    and are not class spells (class spells already have a Vanilla copy at
    +300000 from build_era_spells.py). build_era_spells.py --npc-spells reads
    it, so run this BEFORE build_era_spells.py.

A "1.12 copy" is the existing mechanism: id + 300000, the WotLK row with the
Vanilla client's gameplay values written over it (build_era_spells.py).
Creatures are not subject to the era gate, which only filters what a
character may learn.

What it is careful NOT to touch:
  * Raids. Naxx40/AQ40/MC/BWL in this realm are module-authored conversions
    that deliberately use later spells.
  * A creature whose 1.12 behaviour lives in C++ (cMaNGOS ScriptName) or whose
    1.12 AI has no rows at all: there is nothing to compare against.
  * Anything but timer-driven casts (SmartAI event 0, 9) when deleting: hp,
    aggro, death and out-of-combat casts are left alone.
  * A spell whose id means something else in 1.12 (id reuse).
  * For a spell that has no Vanilla copy yet: a change of effect, aura type,
    misc value or trigger. Those are structural, and 1.12 may have relied on
    core code that no longer exists. Only timing and numbers are restored.

Usage (needs the 1.12.1 and 3.3.5a clients and the dev stack's database):
    python build_classic_mobs.py \\
        --classic-db D:\\wow-db\\1.12.1\\classicmangos.sqlite \\
        --vanilla-root "D:\\Games\\World of Warcraft 1.12.1" \\
        --wotlk-root "D:\\Games\\World of Warcraft 3.3.5a"
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "dbc"))
from wdbc import LOCALE_COUNT, read_dbc  # noqa: E402
from schemas import BUILD_SCHEMAS  # noqa: E402
import mpq_source  # noqa: E402

VANILLA_OFFSET = 300_000

# Vanilla 5-man instances (map ids). Raids and Alterac Valley are not here.
DUNGEON_MAPS = [33, 34, 36, 43, 47, 48, 70, 90, 109, 129, 189, 209, 229, 230,
                289, 329, 349, 389, 429]

# SmartAI actions that cast a spell, with the spell in action_param1.
CAST_ACTIONS = (11, 85, 86, 134)
EVENT_UPDATE_IC = 0
EVENT_RANGE = 9
TIMER_EVENTS = (EVENT_UPDATE_IC, EVENT_RANGE)

# A repeat is put back only when the mob casts clearly MORE OFTEN than 1.12's
# (below this fraction of 1.12's shortest repeat) and 1.12's was a real cooldown.
# The two data sets were measured from different samples, so 12 s against
# 12.9 s is noise, and a repeat of 0 is SmartAI's "once" -- not comparable.
TIMER_TOLERANCE = 0.6
MIN_CLASSIC_COOLDOWN = 8000

# 1.12 effects that summon something. EventAI had a separate summon action, so
# a summon spell on a SmartAI timer is not evidence the ability is new.
SUMMON_EFFECTS = {28, 41, 42, 56, 74, 87, 88, 89, 90, 93, 97}

# Spell fields compared. Effect/aura/misc/trigger are "structural".
TIMING_FIELDS = ("RecoveryTime", "CategoryRecoveryTime")
STRUCTURAL = ("Effect", "EffectAura", "EffectMiscValue", "EffectTriggerSpell")
NUMERIC = ("EffectBasePoints", "EffectDieSides", "EffectAuraPeriod")
# Who a spell lands on. A player's Battle Shout or Totem is aimed at "my party"
# or "my totem slot", which a creature resolves differently, so a difference
# here means the 1.12 row is not safe to hand to a mob.
TARGETING = ("ImplicitTargetA", "ImplicitTargetB", "EffectRadiusIndex")
# Effects and auras whose numbers mean whatever a script says they mean:
# DUMMY, SCRIPT_EFFECT, and the DUMMY aura.
SCRIPTED_EFFECTS = {3, 77}
SCRIPTED_AURAS = {4}

SMART_COLUMNS = ("entryorguid", "id", "event_type", "event_phase_mask", "event_chance",
                 "event_flags", "event_param1", "event_param2", "event_param3",
                 "event_param4", "event_param5", "action_type", "action_param1",
                 "action_param2", "action_param3", "target_type", "link")


def mysql(sql: str, container: str) -> list[list[str]]:
    """Runs a query in the dev stack's database container. The root password
    is read inside the container, so nothing secret passes through here."""
    cmd = ["docker", "exec", "-i", container, "sh", "-c",
           'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -B -N --default-character-set=utf8mb4 acore_world']
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"mysql failed: {out.stderr.strip()}")
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def load_dbc(build: str, name: str, root: Path, tmp: Path):
    archive, data = mpq_source.resolve(root, name)
    path = tmp / f"{build}-{name}"
    path.write_bytes(data)
    return read_dbc(path, BUILD_SCHEMAS[build][name], LOCALE_COUNT[build])


def duration_ms(table: dict[int, dict], index: int):
    """None for 'no duration' -- 0, -1 and a missing row all mean the aura
    does not time out, so they compare equal."""
    row = table.get(index)
    if row is None or row["Duration"] in (0, -1):
        return None
    return row["Duration"]


def spell_changes(vanilla: dict, wotlk: dict, vdur: dict, wdur: dict) -> dict:
    """What differs between a spell's 1.12 and realm rows, split by kind."""
    out = {"timing": {}, "numeric": {}, "structural": {}, "unsafe": {}}
    for f in TIMING_FIELDS:
        if vanilla[f] != wotlk[f]:
            out["timing"][f] = (vanilla[f], wotlk[f])
    a, b = duration_ms(vdur, vanilla["DurationIndex"]), duration_ms(wdur, wotlk["DurationIndex"])
    if a != b:
        out["timing"]["Duration"] = (a, b)
    for i in range(3):
        retargeted = [f for f in TARGETING if vanilla[f"{f}_{i}"] != wotlk[f"{f}_{i}"]]
        scripted = [f"{side}_{i}" for side, row in (("1.12", vanilla), ("realm", wotlk))
                    if row[f"Effect_{i}"] in SCRIPTED_EFFECTS or row[f"EffectAura_{i}"] in SCRIPTED_AURAS]
        if retargeted or scripted:
            out["unsafe"][i] = retargeted + scripted
        struct = [f for f in STRUCTURAL if vanilla[f"{f}_{i}"] != wotlk[f"{f}_{i}"]]
        if struct:
            out["structural"][i] = struct
            continue  # base points of a different effect mean something else
        for f in NUMERIC:
            if vanilla[f"{f}_{i}"] != wotlk[f"{f}_{i}"]:
                out["numeric"][f"{f}_{i}"] = (vanilla[f"{f}_{i}"], wotlk[f"{f}_{i}"])
    return out


def classic_abilities(db: sqlite3.Connection):
    """creature entry -> {spell: [(repeatMin, repeatMax), ...]} from cMaNGOS's
    EventAI (cast actions) and creature_spell_list, plus the set of creatures
    that have any such data at all."""
    db.row_factory = sqlite3.Row
    abilities: dict[int, dict[int, list]] = collections.defaultdict(lambda: collections.defaultdict(list))
    has_data: set[int] = set()
    for r in db.execute("select * from creature_ai_scripts"):
        has_data.add(r["creature_id"])
        for k in (1, 2, 3):
            if r[f"action{k}_type"] == 11:
                rep = (r["event_param3"], r["event_param4"]) if r["event_type"] in TIMER_EVENTS else None
                abilities[r["creature_id"]][r[f"action{k}_param1"]].append(rep)
    for r in db.execute("select l.SpellId, l.RepeatMin, l.RepeatMax, t.Entry from creature_spell_list l "
                        "join creature_template t on t.SpellList = l.Id"):
        has_data.add(r["Entry"])
        abilities[r["Entry"]][r["SpellId"]].append((r["RepeatMin"], r["RepeatMax"]))
    return abilities, has_data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classic-db", required=True, type=Path, help="cMaNGOS classic-db sqlite (classicmangos.sqlite)")
    ap.add_argument("--vanilla-root", required=True, type=Path)
    ap.add_argument("--wotlk-root", required=True, type=Path)
    ap.add_argument("--spell-dbc", type=Path, default=REPO_ROOT / "data" / "generated" / "Spell.dbc",
                    help="the realm's Spell.dbc (the base rows creatures cast today)")
    ap.add_argument("--era-spell-map", type=Path, default=REPO_ROOT / "data" / "generated" / "era-spell-map.json")
    ap.add_argument("--open-world", action="store_true",
                    help="also give classic creatures OUTSIDE the 5-man dungeons (and outside any raid) the 1.12 "
                         "copy of the spells they cast. Off by default: the reports were about dungeons, and it "
                         "adds ~60 more spell copies (every damage spell a classic mob casts).")
    ap.add_argument("--container", default="ac-database", help="dev stack database container")
    ap.add_argument("--out-sql", type=Path,
                    default=REPO_ROOT / "data" / "sql" / "db-world" / "base" / "zzz_nekocore_classic_dungeon_mobs.sql")
    ap.add_argument("--out-spells", type=Path, default=REPO_ROOT / "data" / "generated" / "classic-npc-spells.txt")
    args = ap.parse_args()

    classic = sqlite3.connect(f"file:{args.classic_db.as_posix()}?mode=ro", uri=True)
    classic.row_factory = sqlite3.Row
    cm_creatures = {r["Entry"]: r for r in classic.execute(
        "select Entry, Name, AIName, ScriptName from creature_template")}
    cm_spells = {r["Id"] for r in classic.execute("select Id from spell_template")}
    abilities, has_data = classic_abilities(classic)

    maps = ",".join(str(m) for m in DUNGEON_MAPS)
    dungeon_creatures = {int(r[0]) for r in mysql(
        f"select distinct id from creature where map in ({maps});", args.container)}
    rows = [dict(zip(SMART_COLUMNS, (int(x) for x in r))) for r in mysql(
        f"select {','.join(SMART_COLUMNS)} from smart_scripts where source_type=0 and entryorguid>0 "
        f"order by entryorguid, id;", args.container)]
    names = {int(r[0]): r[1] for r in mysql("select entry, name from creature_template;", args.container)}
    # Creatures that spawn in an instance this tool does not handle (raids, AV,
    # the TBC/WotLK dungeons): their spells are left exactly as they are.
    elsewhere = {int(r[0]) for r in mysql(
        f"select distinct c.id from creature c join instance_template it on it.map = c.map "
        f"where c.map not in ({maps});", args.container)}

    link_targets = {(r["entryorguid"], r["link"]) for r in rows if r["link"]}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        vspell = {r["ID"]: r for r in load_dbc("1.12.1", "Spell.dbc", args.vanilla_root, tmp).rows}
        vdur = {r["ID"]: r for r in load_dbc("1.12.1", "SpellDuration.dbc", args.vanilla_root, tmp).rows}
        wdur = {r["ID"]: r for r in load_dbc("3.3.5a", "SpellDuration.dbc", args.wotlk_root, tmp).rows}
    wspell = {r["ID"]: r for r in read_dbc(args.spell_dbc, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"],
                                          LOCALE_COUNT["3.3.5a"]).rows}
    has_vanilla_copy = {int(k) for k in json.loads(args.era_spell_map.read_text())["id_map"]["Vanilla"]}
    # The map also lists the copies this tool asked for last time. Those are not
    # class spells, and counting them as such would drop them from the list on a re-run.
    if args.out_spells.exists():
        has_vanilla_copy -= {int(x) for x in args.out_spells.read_text().split()}

    # --- which creatures are in scope -----------------------------------
    def in_scope(entry: int) -> bool:
        c = cm_creatures.get(entry)
        return (entry in dungeon_creatures and c is not None and not c["ScriptName"])

    def open_world(entry: int) -> bool:
        """A classic creature outside any raid: it only gets the spell fix,
        not the ability audit (its 1.12 AI is not what the reports were about)."""
        c = cm_creatures.get(entry)
        return c is not None and not c["ScriptName"] and entry not in elsewhere

    deletes: list[dict] = []
    retimed: list[tuple[dict, tuple]] = []
    skipped_linked: list[dict] = []
    kept: list[dict] = []
    for r in rows:
        e = r["entryorguid"]
        if r["action_type"] not in CAST_ACTIONS:
            continue
        if not in_scope(e):
            if args.open_world and open_world(e):
                kept.append(r)
            continue
        spell = r["action_param1"]
        known = abilities.get(e, {}) if e in has_data else None
        v = vspell.get(spell)
        summons = v is not None and any(v[f"Effect_{i}"] in SUMMON_EFFECTS for i in range(3))
        if known is not None and spell not in known and r["event_type"] in TIMER_EVENTS and not summons:
            if r["link"] or (e, r["id"]) in link_targets:
                skipped_linked.append(r)
            else:
                deletes.append(r)
            continue
        kept.append(r)
        if known is not None and spell in known and r["event_type"] in TIMER_EVENTS:
            reps = {x for x in known[spell] if x and x[0] > 0}
            if len(reps) == 1:
                cmin, cmax = next(iter(reps))
                if (cmin >= MIN_CLASSIC_COOLDOWN and 0 < r["event_param3"] < TIMER_TOLERANCE * cmin):
                    retimed.append((r, (cmin, cmax)))

    # A creature whose every SmartAI row would go is one 1.12.1's data does not
    # describe (its behaviour is in C++ there, or a later fix added it here --
    # Razorclaw's Butcher Drain), and SmartAI refuses to load with no rows.
    remaining = collections.Counter(r["entryorguid"] for r in rows)
    for r in deletes:
        remaining[r["entryorguid"]] -= 1
    emptied = {e for e, n in remaining.items() if n <= 0}
    deletes = [r for r in deletes if r["entryorguid"] not in emptied]

    # --- which of the remaining spells need a 1.12 copy -----------------
    repoint: dict[int, str] = {}      # spell -> why
    need_copy: set[int] = set()
    for spell in sorted({r["action_param1"] for r in kept}):
        v, w = vspell.get(spell), wspell.get(spell)
        if v is None or w is None or spell not in cm_spells:
            continue
        if v["Name_lang"]["enUS"] != w["Name_lang"]["enUS"]:
            continue  # the id means a different spell in 1.12
        ch = spell_changes(v, w, vdur, wdur)
        has_copy = spell in has_vanilla_copy
        if ch["unsafe"]:
            continue
        if has_copy:
            if any(ch.values()):
                repoint[spell] = "class spell: " + ", ".join(k for k, val in ch.items() if val)
        elif (ch["timing"] or ch["numeric"]) and not ch["structural"]:
            repoint[spell] = "numbers: " + ", ".join(list(ch["timing"]) + list(ch["numeric"]))
            need_copy.add(spell)

    # --- write -----------------------------------------------------------
    args.out_spells.parent.mkdir(parents=True, exist_ok=True)
    args.out_spells.write_bytes("".join(f"{s}\n" for s in sorted(need_copy)).encode("ascii"))

    out = [
        "-- Vanilla 5-man dungeon mobs, restored to their 1.12.1 abilities.",
        "-- GENERATED by tools/build_patch/build_classic_mobs.py against a 1.12.1 server",
        "-- database. See that file for the rules; this one only holds the result.",
        "--",
        "-- mod-individual-progression rewrites every classic dungeon mob's SmartAI from",
        "-- a later data set. Three corrections:",
        "--   1. casts 1.12 never gave the mob are deleted (timer/range events only);",
        "--   2. repeat timers that drifted from 1.12 are put back;",
        "--   3. the casts that remain use the 1.12 copy of the spell (id + 300000),",
        "--      for spells whose WotLK version has different numbers or timing.",
        "-- Every statement checks the row's current values, so it is safe to re-run.",
        "",
    ]
    out.append(f"-- 1. Abilities 1.12.1 never had ({len(deletes)} casts)")
    by_entry: dict[int, list[dict]] = collections.defaultdict(list)
    for r in deletes:
        by_entry[r["entryorguid"]].append(r)
    for e, group in sorted(by_entry.items()):
        for r in group:
            out.append(
                f"DELETE FROM `smart_scripts` WHERE `source_type` = 0 AND `entryorguid` = {e} "
                f"AND `id` = {r['id']} AND `action_type` = {r['action_type']} "
                f"AND `action_param1` = {r['action_param1']} AND `event_type` = {r['event_type']} "
                f"AND `link` = 0;  -- {names.get(e, e)}: spell {r['action_param1']}")
    out.append("")
    out.append(f"-- 2. Repeat timers back to 1.12.1's ({len(retimed)} casts)")
    for r, (cmin, cmax) in retimed:
        e = r["entryorguid"]
        out.append(
            f"UPDATE `smart_scripts` SET `event_param3` = {cmin}, `event_param4` = {cmax} "
            f"WHERE `source_type` = 0 AND `entryorguid` = {e} AND `id` = {r['id']} "
            f"AND `action_param1` = {r['action_param1']} AND `event_type` = {r['event_type']} "
            f"AND `event_param3` = {r['event_param3']} AND `event_param4` = {r['event_param4']};"
            f"  -- {names.get(e, e)}: spell {r['action_param1']}")
    out.append("")
    out.append(f"-- 3. 1.12.1 copies of the spells ({len(repoint)} spells)")
    kept_entries = collections.defaultdict(set)
    for r in kept:
        if r["action_param1"] in repoint:
            kept_entries[r["action_param1"]].add(r["entryorguid"])
    for spell in sorted(repoint):
        entries = sorted(kept_entries[spell])
        in_list = ", ".join(str(e) for e in entries)
        out.append(
            f"UPDATE `smart_scripts` SET `action_param1` = {spell + VANILLA_OFFSET} "
            f"WHERE `source_type` = 0 AND `action_type` IN (11, 85, 86, 134) "
            f"AND `action_param1` = {spell} AND `entryorguid` IN ({in_list});"
            f"  -- {wspell[spell]['Name_lang']['enUS']} ({repoint[spell]})")
    out.append("")
    args.out_sql.parent.mkdir(parents=True, exist_ok=True)
    args.out_sql.write_bytes("\n".join(out).encode("utf-8"))

    print(f"creatures in scope: {sum(1 for e in dungeon_creatures if in_scope(e))}", file=sys.stderr)
    print(f"deleted casts: {len(deletes)}  (left alone because linked: {len(skipped_linked)})", file=sys.stderr)
    print(f"retimed casts: {len(retimed)}", file=sys.stderr)
    print(f"spells repointed: {len(repoint)}  (new 1.12 copies needed: {len(need_copy)})", file=sys.stderr)
    print(f"wrote {args.out_sql}\nwrote {args.out_spells}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

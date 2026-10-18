"""
Hides later-expansion items from the vendors of the classic world until the
player has reached the progression stage that introduced them.

mod-individual-progression does this with `conditions` rows (source type 23,
NPC vendor; condition QUESTREWARDED on a marker quest 66000 + stage), but its
lists are hand-written per vendor and incomplete: Light Parchment was hidden
at one vendor and sold by 25 others, Simple Flour at 33 of 64, Design:
Amulet of the Moon (a Jewelcrafting design, a TBC profession) by nobody-hid-it.

Rule, against a real 1.12.1 server database (cMaNGOS classic-db):
  for every vendor that exists in 1.12.1, every item it sells that 1.12.1 does
  not have, and that has no vendor condition yet:
    * if the item is gated at ANY other vendor, gate it the same way here
      (the lowest stage the module already chose for it);
    * otherwise gate it by the id: items from 35900 up are WotLK (66013, the
      stage the module uses for them), everything else TBC (66008).
Vendors that do not exist in 1.12.1 (Outland, Northrend) are left alone: the
zone itself is locked behind the same stages.

Two more rules, which need no 1.12.1 database, close what the first one misses:
  * Profession items. 1.12.1 ships placeholder rows for items it never sold
    (every "Design: ..." Jewelcrafting plan, Jeweler's Kit), so "is it in the
    1.12.1 item table" wrongly says they are classic. Anything that needs
    Jewelcrafting (skill 755, TBC) or Inscription (773, WotLK) is gated at every
    vendor that stands in Eastern Kingdoms / Kalimdor (map 0/1).
  * Later-expansion vendors standing in the classic world (scribes, Pilgrim's
    Bounty, Brewfest, arena/honor quartermasters, Caverns of Time...). They are
    not in 1.12.1, so rule 1 skips them as "zone is locked", but their zone is
    not locked. Every item they sell with id >= FIRST_TBC_ITEM is gated by id
    (>= FIRST_WOTLK_ITEM -> WotLK, else TBC). Needs a 1.12.1 DB to also skip
    items below the threshold that 1.12.1 had; without one the threshold alone
    decides.

Output: data/sql/db-world/base/zzz_nekocore_vendor_era_gates.sql, INSERT IGNORE
so it is safe to re-run and never overrides the module's own choice.
Without --classic-db only the two extra rules run (rule 1 needs the database) and
the result goes to zzz_nekocore_vendor_era_gates_extra.sql; a run WITH --classic-db
includes them in the main file and the extra file becomes redundant.

Usage:
    python build_vendor_gates.py --classic-db D:\\wow-db\\1.12.1\\classicmangos.sqlite
    python build_vendor_gates.py --container nkdb   # extra rules only (see above)
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Marker quests the module rewards at each progression stage (66000 + stage).
STAGE_TBC = 66008     # PRE_TBC
STAGE_WOTLK = 66013   # TBC_TIER_5, where WotLK content opens
FIRST_WOTLK_ITEM = 35900
FIRST_TBC_ITEM = 23000   # 1.12.1 item ids stop short of this; vendors new in TBC+ sell above it
SKILL_JEWELCRAFTING = 755
SKILL_INSCRIPTION = 773
CLASSIC_MAPS = (0, 1)
MARKER_RANGE = (66000, 66099)
CONDITION_QUESTREWARDED = 8
SOURCE_NPC_VENDOR = 23


def mysql(sql: str, container: str) -> list[list[str]]:
    cmd = ["docker", "exec", "-i", container, "sh", "-c",
           'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -B -N --default-character-set=utf8mb4 acore_world']
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"mysql failed: {out.stderr.strip()}")
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classic-db", type=Path, help="1.12.1 cMaNGOS sqlite; omit to run only the extra rules")
    ap.add_argument("--container", default="ac-database")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    base = REPO_ROOT / "data" / "sql" / "db-world" / "base"
    if args.out is None:
        args.out = base / ("zzz_nekocore_vendor_era_gates.sql" if args.classic_db
                           else "zzz_nekocore_vendor_era_gates_extra.sql")

    if args.classic_db:
        classic = sqlite3.connect(f"file:{args.classic_db.as_posix()}?mode=ro", uri=True)
        classic_items = {r[0] for r in classic.execute("select entry from item_template")}
        classic_creatures = {r[0] for r in classic.execute("select Entry from creature_template")}
    else:
        classic = None
        classic_items, classic_creatures = set(), set()
    classic_world_vendors = {int(r[0]) for r in mysql(
        f"select distinct id from creature where map in ({','.join(map(str, CLASSIC_MAPS))});", args.container)}
    profession_stage: dict[int, int] = {}
    for item, skill, name in mysql("select entry, RequiredSkill, name from item_template "
                                   f"where RequiredSkill in ({SKILL_JEWELCRAFTING}, {SKILL_INSCRIPTION}) "
                                   "or name = 'Jeweler\\'s Kit';", args.container):
        profession_stage[int(item)] = STAGE_WOTLK if int(skill) == SKILL_INSCRIPTION else STAGE_TBC

    vendor_rows = [(int(e), int(i)) for e, i in mysql("select entry, item from npc_vendor;", args.container)]
    gated_pairs = {(int(g), int(e)) for g, e in mysql(
        f"select SourceGroup, SourceEntry from conditions where SourceTypeOrReferenceId = {SOURCE_NPC_VENDOR};",
        args.container)}
    item_stage: dict[int, int] = {}
    for item, quest in mysql(
            f"select SourceEntry, min(ConditionValue1) from conditions "
            f"where SourceTypeOrReferenceId = {SOURCE_NPC_VENDOR} and ConditionTypeOrReference = "
            f"{CONDITION_QUESTREWARDED} and ConditionValue1 between {MARKER_RANGE[0]} and {MARKER_RANGE[1]} "
            f"group by SourceEntry;", args.container):
        item_stage[int(item)] = int(quest)
    names = {int(e): n for e, n in mysql("select entry, name from creature_template;", args.container)}
    item_names = {int(e): n for e, n in mysql("select entry, name from item_template;", args.container)}

    todo: list[tuple[int, int, int, str]] = []
    for vendor, item in sorted(set(vendor_rows)):
        if (vendor, item) in gated_pairs:
            continue
        if vendor in classic_world_vendors and item in profession_stage:
            todo.append((vendor, item, profession_stage[item], "profession introduced after Vanilla"))
            continue
        if vendor in classic_world_vendors and vendor not in classic_creatures and item >= FIRST_TBC_ITEM \
                and item not in classic_items:
            stage = item_stage.get(item) or (STAGE_WOTLK if item >= FIRST_WOTLK_ITEM else STAGE_TBC)
            todo.append((vendor, item, stage, "later-expansion vendor in the classic world"))
            continue
        if not args.classic_db or vendor not in classic_creatures or item in classic_items:
            continue
        if item in item_stage:
            todo.append((vendor, item, item_stage[item], "same stage as this item at other vendors"))
        else:
            stage = STAGE_WOTLK if item >= FIRST_WOTLK_ITEM else STAGE_TBC
            todo.append((vendor, item, stage, "later-expansion item, stage chosen by item id"))

    out = [
        "-- Later-expansion items hidden from classic vendors until their progression stage.",
        "-- GENERATED by tools/build_patch/build_vendor_gates.py" + ("" if args.classic_db else " (extra rules only, no 1.12.1 database)") + ".",
        "--",
        "-- mod-individual-progression gates vendor items with a QUESTREWARDED condition on",
        "-- marker quest 66000 + stage, but only for the vendor/item pairs its lists name. This",
        "-- adds the rest: every item a 1.12.1 vendor sells that 1.12.1 did not have. INSERT IGNORE,",
        "-- so the module's own rows win and a re-run changes nothing.",
        "",
        "INSERT IGNORE INTO `conditions` (`SourceTypeOrReferenceId`, `SourceGroup`, `SourceEntry`, `SourceId`,",
        "`ElseGroup`, `ConditionTypeOrReference`, `ConditionTarget`, `ConditionValue1`, `ConditionValue2`,",
        "`ConditionValue3`, `NegativeCondition`, `ErrorType`, `ErrorTextId`, `ScriptName`, `Comment`) VALUES",
    ]
    rows = []
    for vendor, item, stage, _why in todo:
        comment = f"{names.get(vendor, vendor)} - {item_names.get(item, item)}".replace("'", "\\'")
        rows.append(f"({SOURCE_NPC_VENDOR}, {vendor}, {item}, 0, 0, {CONDITION_QUESTREWARDED}, 0, {stage}, "
                    f"0, 0, 0, 0, 0, '', '{comment}')")
    out.append(",\n".join(rows) + ";" if rows else "SELECT 1;")
    out.append("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes("\n".join(out).encode("utf-8"))

    by_stage = collections.Counter(stage for _, _, stage, _ in todo)
    print(f"{len(todo)} vendor rows gated ({len({v for v, *_ in todo})} vendors, "
          f"{len({i for _, i, *_ in todo})} items); by stage: {dict(by_stage)}", file=sys.stderr)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

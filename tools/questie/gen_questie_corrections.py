"""
Generates Compat/NekoCore.lua for the NekoCore Questie fork
(m0nnnna/Questie-NekoCore, a fork of divial28/Questie-335).

Questie ships its own copy of the stock quest and NPC data and decides what
to show from it, never from the server. mod-uac changes that data on our
realm, so without this file Questie hides quests players can actually take
and misses NPCs that are actually there:

  * quest race masks -- mod-uac opens 100+ class quests to the whole faction
    (the Blood Knight trials and mounts, the Draenei Call of Water/Air chains,
    the Human/Dwarf paladin chains, ...). Stock Questie still filters them by
    the original race, e.g. The Path of the Adept stays Blood Elf only.
  * new quests -- mod-uac's two Call of Earth quests (6000000/6000001) don't
    exist in Questie at all.
  * new spawns -- mod-uac puts copies of class trainers in every starter
    zone. Questie only knows each trainer's stock spot, so the Call of Earth
    "!" and the trainer town icons pointed at the wrong continent.
  * chain exclusivity -- our zzz_nekocore_class_quest_exclusivity.sql locks
    the other races' paladin chains once one is started. Questie expresses
    that as exclusiveTo.

Everything is read from the SQL that makes the server change, so a rebuild
after a mod-uac bump picks up whatever it now does. Coordinates are
converted with the client's own WorldMapArea.dbc, the same bounds the world
map draws with.

Usage:
    python tools/questie/gen_questie_corrections.py \\
        --questie-dir N:/projects/Questie-NekoCore \\
        --wotlk-root "D:/Games/World of Warcraft 3.3.5a"
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from dbc import mpq_source  # noqa: E402
from dbc.wdbc import FieldSpec as F, read_dbc  # noqa: E402

UAC_SQL = REPO_ROOT / "server" / "modules" / "mod-uac" / "data" / "sql" / "db-world"
NEKO_SQL = REPO_ROOT / "data" / "sql" / "db-world" / "base"

WORLD_MAP_AREA = [
    F("ID", "int32"), F("MapID", "int32"), F("AreaID", "int32"), F("AreaName", "string"),
    F("LocLeft", "float32"), F("LocRight", "float32"), F("LocTop", "float32"), F("LocBottom", "float32"),
    F("DisplayMapID", "int32"), F("DefaultDungeonFloor", "int32"), F("ParentWorldMapID", "int32"),
]

CLASS_SHAMAN = 64


# --- SQL ---------------------------------------------------------------------

def sql_values(text: str) -> list[list[object]]:
    """Every tuple of an INSERT's VALUES list, as Python values. Handles the
    quoting mod-uac writes: '...' with '' as the escaped quote, NULL, numbers."""
    rows: list[list[object]] = []
    i, n = 0, len(text)
    row: list[object] | None = None
    while i < n:
        c = text[i]
        if row is None:
            if c == "(":
                row = []
            i += 1
            continue
        if c in " \t\r\n,":
            i += 1
        elif c == ")":
            rows.append(row)
            row = None
            i += 1
        elif c == "'":
            j, buf = i + 1, []
            while True:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    buf.append("'")
                    j += 2
                elif text[j] == "'":
                    break
                else:
                    buf.append(text[j])
                    j += 1
            row.append("".join(buf))
            i = j + 1
        else:
            m = re.match(r"[^,)\s]+", text[i:])
            tok = m.group(0)
            row.append(None if tok.upper() == "NULL" else (float(tok) if "." in tok else int(tok)))
            i += len(tok)
    return rows


INSERT = re.compile(r"INSERT\s+(?:IGNORE\s+)?INTO\s+`(\w+)`\s*\(([^)]*)\)\s*VALUES\s*(.*?);\s*$",
                    re.S | re.M | re.I)
UPDATE_RACES = re.compile(r"UPDATE\s+`quest_template`\s+SET\s+`AllowableRaces`\s*=\s*(\d+)\s+"
                          r"WHERE\s+`ID`\s*=\s*(\d+)\s*;", re.I)


def inserts(path: Path, table: str) -> list[dict[str, object]]:
    out = []
    for m in INSERT.finditer(path.read_text(encoding="utf-8")):
        if m.group(1) != table:
            continue
        cols = [c.strip().strip("`") for c in m.group(2).split(",")]
        out += [dict(zip(cols, r)) for r in sql_values(m.group(3))]
    return out


# --- coordinates -------------------------------------------------------------

class ZoneMapper:
    """World position -> (Questie zone id, x%, y%), the smallest world map
    area on that map containing the point."""

    def __init__(self, wotlk_root: Path):
        _, data = mpq_source.resolve(wotlk_root, "WorldMapArea.dbc")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "WorldMapArea.dbc"
            path.write_bytes(data)
            self.areas = [r for r in read_dbc(path, WORLD_MAP_AREA, 16).rows if r["AreaID"]]

    def locate(self, map_id: int, x: float, y: float) -> tuple[int, float, float] | None:
        best = None
        for a in self.areas:
            if a["MapID"] != map_id:
                continue
            if not (a["LocRight"] <= y <= a["LocLeft"] and a["LocBottom"] <= x <= a["LocTop"]):
                continue
            size = (a["LocLeft"] - a["LocRight"]) * (a["LocTop"] - a["LocBottom"])
            if best is None or size < best[0]:
                best = (size, a)
        if best is None:
            return None
        a = best[1]
        px = (a["LocLeft"] - y) / (a["LocLeft"] - a["LocRight"]) * 100
        py = (a["LocTop"] - x) / (a["LocTop"] - a["LocBottom"]) * 100
        return a["AreaID"], round(px, 2), round(py, 2)


# --- Lua ---------------------------------------------------------------------

def lua(v: object) -> str:
    if v is None:
        return "nil"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n") + '"'
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return "{" + ",".join(lua(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ",".join(f"[{lua(k)}]={lua(x)}" for k, x in v.items()) + "}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questie-dir", type=Path, required=True)
    ap.add_argument("--wotlk-root", type=Path, required=True)
    args = ap.parse_args()

    # Race masks: every AllowableRaces mod-uac sets, last write wins (the
    # totem file re-narrows some chains after the faction unlock).
    races: dict[int, int] = {}
    for f in sorted(UAC_SQL.glob("*.sql")):
        for m in UPDATE_RACES.finditer(f.read_text(encoding="utf-8")):
            races[int(m.group(2))] = int(m.group(1))

    # New quests (mod-uac's own quest id band).
    totem = UAC_SQL / "mod_uac_shaman_totem_quests.sql"
    addon = {r["ID"]: r for r in inserts(totem, "quest_template_addon")}
    starters = inserts(totem, "creature_queststarter")
    enders = inserts(totem, "creature_questender")
    new_quests = []
    for q in inserts(totem, "quest_template"):
        qid = q["ID"]
        races.pop(qid, None)
        new_quests.append({
            "id": qid, "name": q["LogTitle"],
            "start": [s["id"] for s in starters if s["quest"] == qid],
            "end": [e["id"] for e in enders if e["quest"] == qid],
            "minLevel": q["MinLevel"], "level": q["QuestLevel"], "races": q["AllowableRaces"],
            "classes": addon.get(qid, {}).get("AllowableClasses", 0),
            "text": q["LogDescription"], "sort": q["QuestSortID"],
        })

    # Spawns mod-uac adds to existing NPCs.
    mapper = ZoneMapper(args.wotlk_root)
    spawns: dict[int, dict[int, list[tuple[float, float]]]] = {}
    unplaced = []
    for f in ("mod_uac_starter_trainers.sql", "mod_uac_capital_trainers.sql"):
        for c in inserts(UAC_SQL / f, "creature"):
            where = mapper.locate(int(c["map"]), float(c["position_x"]), float(c["position_y"]))
            if where is None:
                unplaced.append(c["guid"])
                continue
            zone, px, py = where
            spawns.setdefault(int(c["id"]), {}).setdefault(zone, []).append((px, py))

    # Paladin chain exclusivity (CONDITION_QUESTSTATE, negated).
    exclusive: dict[int, list[int]] = {}
    for c in inserts(NEKO_SQL / "zzz_nekocore_class_quest_exclusivity.sql", "conditions"):
        if c["SourceTypeOrReferenceId"] == 19 and c["ConditionTypeOrReference"] == 47 and c["NegativeCondition"]:
            exclusive.setdefault(int(c["SourceEntry"]), []).append(int(c["ConditionValue1"]))

    out = [
        "-- GENERATED by nekocore tools/questie/gen_questie_corrections.py -- do not edit by hand.",
        "-- What the NekoCore realm changes about quests and NPCs (mod-uac, nekocore SQL),",
        "-- applied after every other correction. See that script for the why.",
        "",
        "---@type QuestieDB",
        'local QuestieDB = QuestieLoader:ImportModule("QuestieDB")',
        "",
        "-- Appends to a list field instead of replacing it.",
        "local function union(old, add)",
        "    local out, seen = {}, {}",
        "    for _, v in ipairs(old or {}) do if not seen[v] then seen[v] = true; out[#out + 1] = v end end",
        "    for _, v in ipairs(add) do if not seen[v] then seen[v] = true; out[#out + 1] = v end end",
        "    return out",
        "end",
        "",
        "local RACES = {",
        *[f"    [{q}] = {r}," for q, r in sorted(races.items())],
        "}",
        "",
        "local EXCLUSIVE = {",
        *[f"    [{q}] = {lua(sorted(set(o)))}," for q, o in sorted(exclusive.items())],
        "}",
        "",
        "local NEW_QUESTS = {",
        *[f"    [{q['id']}] = {lua(q)}," for q in new_quests],
        "}",
        "",
        "-- Quests whose kill objectives differ from Questie's WotLK data. The",
        "-- server keeps the original Classic objectives (mod-individual-progression),",
        "-- so Questie logged \"Missing objective data\" for the second one.",
        "local OBJECTIVES = {",
        "    [4501] = {{{9166}, {9167}}}, -- Beware of Pterrordax: 10 Pterrordax + 15 Frenzied",
        "}",
        "",
        "local SPAWNS = {",
        *[f"    [{npc}] = {lua({z: [list(p) for p in pts] for z, pts in sorted(zones.items())})},"
          for npc, zones in sorted(spawns.items())],
        "}",
        "",
        'QuestieCompat.RegisterCorrection("questData", function()',
        "    local questKeys = QuestieDB.questKeys",
        "    local fixes = {}",
        "    for id, mask in pairs(RACES) do",
        "        fixes[id] = { [questKeys.requiredRaces] = mask }",
        "    end",
        "    for id, others in pairs(EXCLUSIVE) do",
        "        local current = QuestieDB.questData[id]",
        "        fixes[id] = fixes[id] or {}",
        "        fixes[id][questKeys.exclusiveTo] = union(current and current[questKeys.exclusiveTo], others)",
        "    end",
        "    for id, objectives in pairs(OBJECTIVES) do",
        "        fixes[id] = fixes[id] or {}",
        "        fixes[id][questKeys.objectives] = objectives",
        "    end",
        "    for id, q in pairs(NEW_QUESTS) do",
        "        fixes[id] = {",
        "            [questKeys.name] = q.name,",
        "            [questKeys.startedBy] = {q.start},",
        "            [questKeys.finishedBy] = {q[\"end\"]},",
        "            [questKeys.requiredLevel] = q.minLevel,",
        "            [questKeys.questLevel] = q.level,",
        "            [questKeys.requiredRaces] = q.races,",
        "            [questKeys.requiredClasses] = q.classes,",
        "            [questKeys.objectivesText] = {q.text},",
        "            [questKeys.zoneOrSort] = q.sort,",
        "        }",
        "    end",
        "    return fixes",
        "end)",
        "",
        'QuestieCompat.RegisterCorrection("npcData", function()',
        "    local npcKeys = QuestieDB.npcKeys",
        "    local fixes = {}",
        "    for id, zones in pairs(SPAWNS) do",
        "        local current = QuestieDB.npcData[id]",
        "        local merged = {}",
        "        for zone, points in pairs(current and current[npcKeys.spawns] or {}) do merged[zone] = points end",
        "        for zone, points in pairs(zones) do",
        "            merged[zone] = merged[zone] or {}",
        "            for _, p in ipairs(points) do table.insert(merged[zone], p) end",
        "        end",
        "        fixes[id] = { [npcKeys.spawns] = merged }",
        "    end",
        "    for qid, q in pairs(NEW_QUESTS) do",
        "        for _, npc in ipairs(q.start) do",
        "            local current = QuestieDB.npcData[npc]",
        "            fixes[npc] = fixes[npc] or {}",
        "            fixes[npc][npcKeys.questStarts] = union(fixes[npc][npcKeys.questStarts] or (current and current[npcKeys.questStarts]), {qid})",
        "        end",
        "        for _, npc in ipairs(q[\"end\"]) do",
        "            local current = QuestieDB.npcData[npc]",
        "            fixes[npc] = fixes[npc] or {}",
        "            fixes[npc][npcKeys.questEnds] = union(fixes[npc][npcKeys.questEnds] or (current and current[npcKeys.questEnds]), {qid})",
        "        end",
        "    end",
        "    return fixes",
        "end)",
        "",
    ]
    dest = args.questie_dir / "Compat" / "NekoCore.lua"
    dest.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"wrote {dest}: {len(races)} race mask(s), {len(exclusive)} exclusivity rule(s), "
          f"{len(new_quests)} new quest(s), {sum(len(p) for z in spawns.values() for p in z.values())} "
          f"spawn(s) on {len(spawns)} NPC(s)")
    if unplaced:
        print(f"warning: no world map area for creature guid(s) {unplaced}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

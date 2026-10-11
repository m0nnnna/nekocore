"""
Spawns a Challenge Keeper (entry 9000101) in front of every dungeon and raid
entrance, and writes data/sql/db-world/base/challenge_keeper_spawns.sql.

Where "in front" is: the world database knows an entrance only as an
`areatrigger_teleport` row, and the trigger's own z is useless as a ground
height (Ruby Sanctum's sits at -100, the Oculus door above the Nexus's). But
every instance has an EXIT trigger whose target is the spot outside the door
where a player appears, on real ground and facing away from the door. So each
entrance trigger (position from the client's AreaTrigger.dbc) is paired with
the nearest exit target on the same continent, and the Keeper stands a few
yards to the side of that, facing the way the player faces, i.e. toward
people walking up to the door.

Entrances with no exit to pair with are listed in EXTRA_SPOTS below, or
reported and skipped.

Usage:
    python tools/build_patch/build_keeper_spawns.py --wotlk-root "D:\\...\\3.3.5a"
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dbc"))
import mpq_source  # noqa: E402
from build_era_spell_sql import mysql  # noqa: E402

KEEPER = 9000101
FIRST_GUID = 5300740
LAST_GUID = 5300899
MATCH_YARDS = 35.0   # exit target this close to an entrance trigger = same door
SIDE_YARDS = 3.5     # how far to the side of the arrival point the Keeper stands
MERGE_YARDS = 6.0    # two Keepers closer than this would be one door twice

# Entrances that have no exit trigger to pair with: (map, continent, x, y, z, o, label)
EXTRA_SPOTS = [
    # Naxxramas: four portals on the floating necropolis, one Keeper in the middle.
    (533, 571, 3670.0, -1270.0, 248.6, 0.0, "Naxxramas"),
    # Stratholme service gate: two triggers 35 yards apart on one gate.
    (329, 0, 3392.5, -3379.3, 143.0, 0.0, "Stratholme, Service Entrance"),
]
# Entrances deliberately skipped: no door of their own.
SKIP_TRIGGERS = {
    5290,  # Eye of Eternity: reached through the Oculus door
    3197,  # Dire Maul: Alzzin's back exit
}
# Exit triggers that are not a door out (falls, jump exits).
SKIP_EXITS = {2406, 2407, 2408, 2409, 2410, 2411, 2068, 121, 5113, 5235, 4304, 4612, 4614, 5688, 5683}


def area_triggers(root: Path) -> dict[int, tuple[int, float, float, float]]:
    _, data = mpq_source.resolve(root, "AreaTrigger.dbc")
    count, _, size, _ = struct.unpack_from("<IIII", data, 4)
    out = {}
    for i in range(count):
        tid, cont, x, y, z = struct.unpack_from("<IIfff", data, 20 + i * size)
        out[tid] = (cont, x, y, z)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path)
    ap.add_argument("--env-file", type=Path, default=Path("server/.env"))
    ap.add_argument("--out", type=Path, default=Path("data/sql/db-world/base/challenge_keeper_spawns.sql"))
    args = ap.parse_args()

    password = ""
    for line in args.env_file.read_text().splitlines():
        if line.startswith("DOCKER_DB_ROOT_PASSWORD="):
            password = line.split("=", 1)[1].strip()
    if not password:
        raise SystemExit(f"no DOCKER_DB_ROOT_PASSWORD in {args.env_file}")

    triggers = area_triggers(args.wotlk_root)
    instances = {int(r[0]) for r in mysql("SELECT map FROM acore_world.instance_template", password)}
    names = {int(r[0]): r[1] for r in mysql("SELECT ID, Name FROM acore_world.areatrigger_teleport", password)}
    entrances = [(int(r[0]), int(r[1])) for r in mysql(
        "SELECT t.ID, t.target_map FROM acore_world.areatrigger_teleport t "
        "JOIN acore_world.instance_template i ON i.map = t.target_map", password)]
    exits = [(int(r[0]), int(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in mysql(
        "SELECT t.ID, t.target_map, t.target_position_x, t.target_position_y, t.target_position_z, "
        "t.target_orientation FROM acore_world.areatrigger_teleport t "
        "WHERE t.target_map NOT IN (SELECT map FROM acore_world.instance_template)", password)]

    spots: list[tuple[int, int, float, float, float, float, str]] = []
    unmatched: list[str] = []
    for tid, imap in sorted(entrances, key=lambda e: (e[1], e[0])):
        if tid in SKIP_TRIGGERS or tid not in triggers:
            continue
        cont, ex, ey, _ = triggers[tid]
        if cont in instances:
            continue  # a door between two parts of an instance, not an entrance
        label = names.get(tid, str(tid)).strip()
        best = None
        for xid, xmap, x, y, z, o in exits:
            if xid in SKIP_EXITS or xmap != cont:
                continue
            xcont = triggers.get(xid, (None,))[0]
            if xcont != imap:
                continue  # an exit out of some other instance
            d = math.dist((ex, ey), (x, y))
            if d <= MATCH_YARDS and (best is None or d < best[0]):
                best = (d, x, y, z, o)
        if best is None:
            if not any(s[0] == imap for s in EXTRA_SPOTS):
                unmatched.append(f"{imap} {label} (trigger {tid})")
            continue
        _, x, y, z, o = best
        px, py = x + SIDE_YARDS * math.cos(o + math.pi / 2), y + SIDE_YARDS * math.sin(o + math.pi / 2)
        spots.append((imap, cont, px, py, z, o, label))
    spots += EXTRA_SPOTS

    kept: list[tuple[int, int, float, float, float, float, str]] = []
    for s in spots:
        if any(k[1] == s[1] and math.dist((k[2], k[3]), (s[2], s[3])) < MERGE_YARDS for k in kept):
            continue
        kept.append(s)

    if len(kept) > LAST_GUID - FIRST_GUID + 1:
        raise SystemExit("more spots than the reserved guid range")

    lines = [
        "-- Challenge Keeper (9000101) in front of every dungeon and raid entrance.",
        "-- GENERATED by tools/build_patch/build_keeper_spawns.py -- edit the tool, not this file.",
        f"DELETE FROM `creature` WHERE `guid` BETWEEN {FIRST_GUID} AND {LAST_GUID};",
        "INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `spawnMask`, `phaseMask`, `equipment_id`, "
        "`position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, "
        "`currentwaypoint`, `curhealth`, `curmana`, `MovementType`, `npcflag`, `unit_flags`, `dynamicflags`, "
        "`ScriptName`, `VerifiedBuild`, `CreateObject`, `Comment`) VALUES",
    ]
    rows = []
    for i, (imap, cont, x, y, z, o, label) in enumerate(kept):
        o = o % (2 * math.pi)
        label = label.replace("'", "''")
        rows.append(f"({FIRST_GUID + i}, {KEEPER}, {cont}, 0, 0, 1, 1, 0, {x:.2f}, {y:.2f}, {z:.2f}, {o:.4f}, "
                    f"300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore Challenge Keeper: {label}')")
    lines.append(",\n".join(rows) + ";")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(kept)} Keeper spawn(s) for {len({k[0] for k in kept})} instance map(s)")
    for u in unmatched:
        print(f"  no door found, skipped: {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

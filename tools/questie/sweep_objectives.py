"""Find quests whose kill/interact objectives on the server differ from
Questie's WotLK data, and write objective_fixes.json for the generator.

The server keeps the original Classic/TBC objectives (mod-individual-progression)
while Questie's WotLK DB has the Wrath ones, so the quest log can hold more
objectives than Questie knows ("Missing objective data for quest").

    python tools/questie/sweep_objectives.py --world-dump backups/acore_world/<dump>.sql.gz \\
        --questie-dir <Questie-NekoCore>
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

OUT = Path(__file__).with_name("objective_fixes.json")
TOKEN = re.compile(r"[^,)\s]+")
BARE = re.compile(r"[^,}\s]+")


def sql_values(text: str) -> list[list[object]]:
    """Tuples of a mysqldump INSERT; strings come back as None (only numbers matter)."""
    rows, i, n, row = [], 0, len(text), None
    while i < n:
        c = text[i]
        if row is None:
            if c == "(":
                row = []
            i += 1
        elif c in " \t\r\n,":
            i += 1
        elif c == ")":
            rows.append(row)
            row = None
            i += 1
        elif c == "'":
            j = i + 1
            while text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            row.append(None)
            i = j + 1
        else:
            t = TOKEN.match(text, i)
            tok = t.group(0)
            row.append(None if tok.upper() == "NULL" else (float(tok) if "." in tok else int(tok)))
            i = t.end()
    return rows


def lua_table(s: str, i: int = 0):
    while s[i] in " \t\r\n":
        i += 1
    if s[i] == "{":
        i += 1
        out = []
        while True:
            while s[i] in " \t\r\n,":
                i += 1
            if s[i] == "}":
                return out, i + 1
            v, i = lua_table(s, i)
            out.append(v)
    if s[i] == '"':
        j, buf = i + 1, []
        while s[j] != '"':
            if s[j] == "\\":
                j += 1
            buf.append(s[j])
            j += 1
        return "".join(buf), j + 1
    t = BARE.match(s, i)
    tok = t.group(0)
    return (None if tok == "nil" else (float(tok) if "." in tok else int(tok))), t.end()


def ids(lst) -> set[int]:
    return {e[0] for e in (lst or []) if isinstance(e, list) and e and isinstance(e[0], int)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world-dump", type=Path, required=True)
    ap.add_argument("--questie-dir", type=Path, required=True)
    args = ap.parse_args()

    txt = gzip.open(args.world_dump, "rt", encoding="utf-8", errors="replace").read()
    cols = re.findall(r"^  `(\w+)`", re.search(r"CREATE TABLE `quest_template` \((.*?)\n\) ENGINE", txt, re.S).group(1), re.M)
    server = {}
    for m in re.finditer(r"INSERT INTO `quest_template` VALUES (.*?);\n", txt, re.S):
        for r in sql_values(m.group(1)):
            d = dict(zip(cols, r))
            server[d["ID"]] = d

    questie = {}
    for line in (args.questie_dir / "Database/Wotlk/wotlkQuestDB.lua").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+)\] = (\{.*\}),\s*$", line)
        if m:
            try:
                questie[int(m.group(1))] = lua_table(m.group(2))[0]
            except (IndexError, ValueError):
                pass

    fixes = {}
    for qid, d in sorted(server.items()):
        if qid not in questie:
            continue
        row = questie[qid]
        o = list((row[9] if len(row) > 9 else None) or [])
        o += [None] * (3 - len(o))
        npcs = [d[f"RequiredNpcOrGo{k}"] or 0 for k in range(1, 5)]
        creatures = [n for n in npcs if n > 0]
        objects = [-n for n in npcs if n < 0]
        qc, qo = ids(o[0]), ids(o[1])
        if (len(creatures) + len(objects) != len(o[0] or []) + len(o[1] or [])
                or (creatures and not qc & set(creatures)) or (objects and not qo & set(objects))):
            fixes[qid] = [[[c] for c in creatures] or None, [[x] for x in objects] or None, o[2]]
    body = ",\n".join(f'"{q}":{json.dumps(v, separators=(",", ":"))}' for q, v in fixes.items())
    OUT.write_text("{\n" + body + "\n}\n", encoding="utf-8")
    print(f"{len(fixes)} quests differ -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

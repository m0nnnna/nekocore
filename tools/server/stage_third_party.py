"""
Stages the server-side halves of the Lua/SQL/asset third-party mods
(third-party/, fetched by tools/third_party/fetch.py) into the live
AzerothCore tree. The compiled C++ mods need nothing from this script --
fetch.py already puts them under server/modules/ where CMake finds them.

What goes where, and why there:

  Lua  -> server/env/dist/lua_scripts/            (bind-mounted into
          ac-worldserver; ALE.ScriptPath points at it, see
          docker-compose.override.yml)
            prestige/00_prestige_and_spell_choice_config.lua  (renamed: ALE
                loads scripts sorted by full path and the other prestige
                files read CONFIG.* at load time, so the config has to sort
                first -- upstream's layout only works by accident of its
                folder name "Prestige & Draft Mode" sorting after the
                root-level config)
            prestige/*.lua, ExchangeNpc.lua
          Then conf/lua-overrides/<same relative path> is copied over the
          top, so local config edits (exchange lists, Chromie location, ...)
          live in this repo instead of in a third-party checkout.

  SQL  -> server/modules/nekocore/data/sql/db-{world,characters}/base/tp_*.sql
          AzerothCore's updater only scans data/sql under *compiled* modules
          (UpdateFetcher.cpp walks the built-in module list), so SQL from
          Lua-only mods has to ride along inside our own module's tree.
          sync_module.py calls stage_sql() after it recreates that tree.
          Files are applied in filename order across all modules, so the
          tp_<mod>_<NN>_ prefixes fix the order upstream's READMEs ask for
          (Prestige: create dbc_* tables before the 18 MB INSERT IGNORE into
          them; mod-uac's playercreateinfo rows land before Prestige's
          INSERT IGNORE for the same race/class pairs).
          The files are rewritten on the way for schema changes AzerothCore
          made after these mods were written (modernize_sql): `creature`
          lost id2/id3 and renamed id1 -> id; `creature_template` lost
          modelid1-4/scale (now creature_template_model rows), trainer_*
          and the two immune masks. Everything else in them matched the
          live schema when checked (2026-09-19).

  Conf -> server/env/dist/etc/modules/
          The C++ mods' <name>.conf.dist, plus a <name>.conf copy if none
          exists yet (edit that one; it's never overwritten). etc/ is a host
          bind mount, so the copies the image install makes are invisible to
          the running worldserver -- without this the modules silently run
          on their compiled-in defaults (BreakingNews.Enable = 0).

Usage:
    python tools/server/stage_third_party.py            # everything
    python tools/server/stage_third_party.py lua confs  # a subset
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
THIRD_PARTY = REPO_ROOT / "third-party"
SERVER = REPO_ROOT / "server"
LUA_DEST = SERVER / "env" / "dist" / "lua_scripts"
LUA_OVERRIDES = REPO_ROOT / "conf" / "lua-overrides"
DATA_DEST = SERVER / "env" / "dist" / "data"
MODULE_SQL_DEST = SERVER / "modules" / "nekocore" / "data" / "sql"
ETC_MODULES_DEST = SERVER / "env" / "dist" / "etc" / "modules"
CPP_MODS_WITH_CONF = ["Breaking-News-Rewrite", "mod-global-chat"]

PRESTIGE = THIRD_PARTY / "Prestige-and-Draft-Mode"
EXCHANGE = THIRD_PARTY / "Acore_ExchangeNpc"


# --- Lua ---------------------------------------------------------------------

def stage_lua() -> None:
    _require(PRESTIGE, EXCHANGE)
    LUA_DEST.mkdir(parents=True, exist_ok=True)
    managed = {"prestige": []}

    src_dir = PRESTIGE / "Lua Files"
    managed["prestige"].append((src_dir / "prestige_and_spell_choice_config.lua",
                                "00_prestige_and_spell_choice_config.lua"))
    for f in sorted((src_dir / "Prestige & Draft Mode").glob("*.lua")):
        managed["prestige"].append((f, f.name))

    stale = LUA_DEST / "delves"
    if stale.exists():
        shutil.rmtree(stale)  # from before Delves was dropped
    for sub, files in managed.items():
        dest = LUA_DEST / sub
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()
        for src, name in files:
            text = src.read_text(encoding="utf-8", errors="replace")
            # Prestige's scripts dofile() their config by a path relative to the
            # worldserver's cwd, which is /azerothcore in the container, not
            # ScriptPath -- it can never resolve here. CONFIG is already a global
            # by the time these run (00_ prefix above), so the line is dropped.
            text = text.replace('dofile("lua_scripts/prestige_and_spell_choice_config.lua")',
                                "-- dofile() of the config removed by nekocore staging: "
                                "00_prestige_and_spell_choice_config.lua in this folder loads first")
            (dest / name).write_text(text, encoding="utf-8")
        print(f"lua: {sub}/ <- {len(files)} files")
    shutil.copyfile(EXCHANGE / "ExchangeNpc.lua", LUA_DEST / "ExchangeNpc.lua")
    print("lua: ExchangeNpc.lua")

    if LUA_OVERRIDES.is_dir():
        for f in sorted(p for p in LUA_OVERRIDES.rglob("*.lua") if p.is_file()):
            rel = f.relative_to(LUA_OVERRIDES)
            (LUA_DEST / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, LUA_DEST / rel)
            print(f"lua: override {rel}")


# --- SQL ---------------------------------------------------------------------

def _sql_name(mod: str, order: str, original: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", Path(original).stem).strip("_")
    return f"tp_{mod}_{order}_{stem}.sql"


def sql_plan() -> list[tuple[Path, str, str]]:
    """(source file, db dir name, staged filename) for every third-party SQL file."""
    plan: list[tuple[Path, str, str]] = []
    pw = PRESTIGE / "Sql & Serverside Files" / "SQL" / "Acore_world"
    pc = PRESTIGE / "Sql & Serverside Files" / "SQL" / "Acore_characters"
    plan.append((pc / "prestige.sql", "db-characters", _sql_name("prestige", "10", "prestige.sql")))
    for order, name in [("10", "prestige_draft_specific_tables.sql"),
                        ("20", "Professions_Allow_Patch.sql"),
                        ("30", "chromie_spawn.sql"),
                        ("31", "playercreateinfo_additions.sql"),
                        ("32", "playercreateinfo_action_additions.sql"),
                        ("33", "playercreateinfo_items_additions.sql")]:
        plan.append((pw / name, "db-world", _sql_name("prestige", order, name)))

    plan.append((EXCHANGE / "database" / "world" / "ExchangeNpc_Up.sql", "db-world",
                 _sql_name("exchangenpc", "10", "ExchangeNpc_Up.sql")))
    return plan


def stage_sql(module_sql_dir: Path = MODULE_SQL_DEST) -> None:
    _require(PRESTIGE, EXCHANGE)
    rewritten = 0
    for src, db, name in sql_plan():
        if not src.exists():
            raise SystemExit(f"missing {src}")
        dest = module_sql_dir / db / "base" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8", errors="replace")
        new = modernize_sql(text)
        rewritten += new != text
        dest.write_text(new, encoding="utf-8")
    n = len(sql_plan())
    print(f"sql: {n} third-party files -> {module_sql_dir} ({rewritten} rewritten for current schema)")


# --- SQL schema modernization ------------------------------------------------

_CREATURE_DROP = {"id2", "id3"}
_CREATURE_RENAME = {"id1": "id"}
_TEMPLATE_DROP = {"modelid1", "modelid2", "modelid3", "modelid4", "scale", "trainer_type",
                  "trainer_spell", "trainer_class", "trainer_race", "mechanic_immune_mask",
                  "spell_school_immune_mask"}
_INSERT_RE = re.compile(
    r"INSERT(?:\s+IGNORE)?\s+INTO\s+`?(?:acore_world\.)?`?(creature|creature_template)`?\s*\(([^)]*)\)\s*VALUES\s*",
    re.I)


def _parse_tuples(text: str, start: int) -> tuple[list[list[str]], int]:
    """Parses `(a, 'b', ...), (...);` starting at `start`; returns the rows as
    raw element strings and the index just past the terminating ';'."""
    rows: list[list[str]] = []
    i, n = start, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if text.startswith("--", i):  # comment line between tuples
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if i >= n or text[i] == ";":
            return rows, i + 1
        if text[i] != "(":
            raise ValueError(f"expected '(' at {i}: {text[i:i + 40]!r}")
        i += 1
        row: list[str] = []
        cur: list[str] = []
        while True:
            c = text[i]
            if c == "'":
                cur.append(c)
                i += 1
                while True:
                    c = text[i]
                    cur.append(c)
                    i += 1
                    if c == "\\":
                        cur.append(text[i])
                        i += 1
                    elif c == "'":
                        if text[i] == "'":
                            cur.append("'")
                            i += 1
                        else:
                            break
            elif c == ",":
                row.append("".join(cur).strip())
                cur = []
                i += 1
            elif c == ")":
                row.append("".join(cur).strip())
                i += 1
                break
            else:
                cur.append(c)
                i += 1
        rows.append(row)
    return rows, i


_WHERE_ID1_RE = re.compile(r"(DELETE\s+FROM\s+`?creature`?\s+WHERE\s+)`?id1`?", re.I)


def modernize_sql(text: str) -> str:
    text = _WHERE_ID1_RE.sub(r"\1`id`", text)
    out: list[str] = []
    pos = 0
    for m in _INSERT_RE.finditer(text):
        if m.start() < pos:
            continue
        table = m.group(1).lower()
        cols = [c.strip().strip("`") for c in m.group(2).split(",")]
        drop = _CREATURE_DROP if table == "creature" else _TEMPLATE_DROP
        renames = _CREATURE_RENAME if table == "creature" else {}
        if not (set(cols) & drop) and not (set(cols) & renames.keys()):
            continue
        rows, end = _parse_tuples(text, m.end())
        keep = [i for i, c in enumerate(cols) if c not in drop]
        new_cols = [renames.get(cols[i], cols[i]) for i in keep]
        verb = "INSERT IGNORE" if text[m.start():m.start() + 13].upper() == "INSERT IGNORE" else "INSERT"
        stmt = f"{verb} INTO `{table}` (" + ", ".join(f"`{c}`" for c in new_cols) + ") VALUES\n"
        stmt += ",\n".join("(" + ", ".join(r[i] for i in keep) + ")" for r in rows) + ";"
        if table == "creature_template" and "modelid1" in cols:
            # models moved to creature_template_model; carry modelid1 (+scale) over
            e, m1 = cols.index("entry"), cols.index("modelid1")
            sc = cols.index("scale") if "scale" in cols else None
            models = [(r[e], r[m1], r[sc] if sc is not None else "1")
                      for r in rows if r[m1].strip() not in ("0", "")]
            if models:
                ids = ", ".join(x[0] for x in models)
                stmt += (f"\nDELETE FROM `creature_template_model` WHERE `CreatureID` IN ({ids});\n"
                         "INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, "
                         "`DisplayScale`, `Probability`, `VerifiedBuild`) VALUES\n"
                         + ",\n".join(f"({e_}, 0, {m_}, {s_}, 1, 0)" for e_, m_, s_ in models) + ";")
        out.append(text[pos:m.start()])
        out.append(stmt)
        pos = end
    out.append(text[pos:])
    return "".join(out)



# --- Conf --------------------------------------------------------------------

def stage_confs() -> None:
    ETC_MODULES_DEST.mkdir(parents=True, exist_ok=True)
    for mod in CPP_MODS_WITH_CONF:
        conf_dir = SERVER / "modules" / mod / "conf"
        _require(conf_dir)
        # Breaking News reads its HTML by a path relative to the worldserver's
        # cwd (/azerothcore in the container) by default; ship the sample next
        # to the conf in the host-mounted etc/modules instead (never
        # overwritten) and point HtmlPath there in breakingnews.conf.
        # Our own text lives in conf/breakingnews/Updates.html (tracked); it
        # is only placed if etc/modules has none yet, so live edits survive.
        ours = REPO_ROOT / "conf" / "breakingnews" / "Updates.html"
        sample = SERVER / "modules" / mod / "Updates.html"
        src = ours if ours.exists() else sample
        if src.exists() and not (ETC_MODULES_DEST / "Updates.html").exists():
            shutil.copyfile(src, ETC_MODULES_DEST / "Updates.html")
            print("conf: Updates.html placed in etc/modules (HtmlPath in breakingnews.conf points there)")
        for dist in sorted(conf_dir.glob("*.conf.dist")):
            shutil.copyfile(dist, ETC_MODULES_DEST / dist.name)
            live = ETC_MODULES_DEST / dist.name[:-len(".dist")]
            if not live.exists():
                shutil.copyfile(dist, live)
                print(f"conf: {live.name} created from .dist (edit this one)")
            else:
                print(f"conf: {live.name} kept, {dist.name} refreshed")


# -----------------------------------------------------------------------------

def _require(*paths: Path) -> None:
    missing = [p for p in paths if not p.is_dir()]
    if missing:
        raise SystemExit("missing " + ", ".join(map(str, missing)) + " -- run tools/third_party/fetch.py")


STEPS = {"lua": stage_lua, "sql": stage_sql, "confs": stage_confs}


def main(argv: list[str]) -> int:
    names = argv or list(STEPS)
    unknown = [n for n in names if n not in STEPS]
    if unknown:
        raise SystemExit(f"unknown step(s) {unknown}; known: {', '.join(STEPS)}")
    for n in names:
        STEPS[n]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

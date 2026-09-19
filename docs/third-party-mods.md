# Third-party mods

Five catalogue mods added 2026-09-19 (a sixth, Delves, was installed and then dropped -- see below), on top of the module roster the README
already covers. What each one is, where its pieces land, and the full
command sequence to bring them up on a rebuilt box.

| Mod | Kind | Server side | Client side |
|---|---|---|---|
| [Breaking-News-Rewrite](https://github.com/imagionationeditor/Breaking-News-Rewrite) | C++ | `server/modules/`, `etc/modules/breakingnews.conf` | none (Warden payload, needs `Warden.Enabled = 1`) |
| [mod-uac](https://github.com/berubejd/mod-uac) | C++ + SQL | `server/modules/`, SQL auto-applied, `PlayerStart.CustomSpells = 1` | CharBaseInfo / SkillRaceClassInfo / CharStartOutfit rows, merged into `patch-Z.mpq` |
| [mod-global-chat](https://github.com/azerothcore/mod-global-chat) | C++ | `server/modules/`, `etc/modules/GlobalChat.conf` | none |
| [Prestige-and-Draft-Mode](https://github.com/Youpeoples/Prestige-and-Draft-Mode) | Lua + SQL + DBC | `lua_scripts/prestige/`, 7 SQL files, CharBaseInfo / CharTitles / SkillRaceClassInfo rows | `PrestigeSystem` addon (Draft Mode only); DBC rows in `patch-Z.mpq` |
| [Acore_ExchangeNpc](https://github.com/55Honey/Acore_ExchangeNpc) | Lua + SQL | `lua_scripts/ExchangeNpc.lua`, 1 SQL file | none |

Dropped after install: **Delves** (araxiaonline). It worked -- custom maps,
DBCs, boss scripts, teleporter -- but it's level 82-85 content and the realm
is capped at 60; a teleporter that drops level-20s into an 85 elite zone is
worse than not having it. Everything needed to bring it back is in git
history before the "Drop Delves" commit (fetch pin, CSV->DBC layers via
`Merger.layer_csv`, map staging with the mmap v19->v20 header bump, client
asset packing, `Instance.IgnoreRaid = 1`, the `/dt` vs Details! alias fix).

Skipped on purpose: **mod-worgoblin**. Unmaintained, needs a
signature-patched `Wow.exe` on every client, and its 30 whole-file DBC
replacements (Spell, SkillLine\*, TalentTab, ...) would wipe out the era
talents and mod-individual-progression's optional DBCs. Decided with the
user before starting.

## Why there's a DBC merge step at all

Three of the five edit server DBCs, and two edit the *same* files --
CharBaseInfo (mod-uac + Prestige) and SkillRaceClassInfo (mod-uac + Prestige +
individual-progression). Each ships "stock plus my rows"
as a whole file, so installing them as their READMEs say means the last one
copied wins. `tools/dbc/layer_merge.py` diffs each mod's copy (or a WDBX CSV
row list) against the stock file and layers only the rows, and
`tools/build_patch/build_mod_dbcs.py` is the recipe that produces
`data/generated/dbc/*.dbc` (4 files). Those are bind-mounted over the
server's `data/dbc` (docker-compose.override.yml) and packed into the
client's `patch-Z.mpq` -- one source, both sides.

Two deliberate deviations from upstream, both visible in
`build_mod_dbcs.py`'s summary output as "kept-base-for N":

- Prestige's `SkillRaceClassInfo.dbc` also rewrites every stock row's
  race/class mask to -1. Only its 41 *added* rows are taken (they already
  carry -1/-1 masks + the class-skill flag, which is what Draft Mode needs);
  the wholesale rewrite would undo mod-uac's per-race rows.
- Prestige's `CharTitles.dbc` renames stock title 177 ("Wrathful
  Gladiator") to a vulgar joke. Not taken.

## Bringing it all up (fresh box or after changing a pin)

```
python tools/third_party/fetch.py                 # pinned clones -> third-party/ and server/modules/
                                                  #   + applies third-party-patches/<mod>/*.patch
python tools/build_patch/build_mod_dbcs.py        # -> data/generated/dbc/*.dbc
python tools/server/stage_third_party.py          # lua, sql, confs (see its docstring)
python tools/server/sync_module.py                # nekocore module + the staged tp_*.sql
docker compose -f server/docker-compose.yml build ac-worldserver     # from server/: docker compose build ac-worldserver
sh tools/server/apply_module_sql.sh server        # db-import: mod-uac's + the tp_*.sql files
docker compose up -d                              # from server/: picks up the new DBC mounts
python tools/install_patch/install_client.py --wotlk-root <client> --bundle-zip website/downloads/nekocore-patch.zip
```

`worldserver.conf` needs `PlayerStart.CustomSpells = 1` (mod-uac; without
it Night Elf / Draenei warlocks are created without an imp) and
`Warden.Enabled = 1` (Breaking News). Both are set on the live box; `etc/`
is a gitignored bind mount, so on a rebuilt box set them again.

Config that lives inside the mods' own files is changed via
`third-party-patches/` (applied by `fetch.py`): Prestige's `MAX_LEVEL = 60`
(realm cap), ExchangeNpc's spawn points (moved from Shattrath/Tanaris --
unreachable for a Vanilla-era character -- to the capitals). Whole-file
replacements can also go in `conf/lua-overrides/<same relative path>`,
copied over `lua_scripts/` last by `stage_third_party.py lua`.

**Service NPCs.** `data/sql/db-world/base/service_npcs.sql` spawns the
Transmogrifier, Dungeon Dan and the XP Guide (their modules ship templates
only) in a row next to Gabriella in Stormwind's Trade District and
Orgrimmar's Valley of Strength; ExchangeNpc.lua spawns its two NPCs into the
same rows. Chromie (Prestige) is at the Orgrimmar and Ironforge gates via
that mod's own SQL.

## Things to know

- **ALE vs Eluna.** Both Lua mods target Eluna; our engine is mod-ale,
  which upstream describes as "not compatible". Statically cross-checked
  every API name the scripts call against ALE's registered methods -- all
  present. Verified live by `.reload eluna` /
  worldserver log showing zero Lua errors on load.
- **Breaking-News-Rewrite doesn't compile against current AzerothCore.**
  `CharacterDatabase.PQuery("... %u")` became `Query("... {}")`,
  `ServerScript::CanPacketSend` takes `WorldPacket const&`, and
  `fmt::format` with a runtime format string needs `fmt::runtime()`. Also
  fixed in the same patch: generated stats lacked the `<html><body>` wrapper
  SimpleHTML needs (tags showed literally), the Top Guild query aborted the
  worldserver when mod-guild-points isn't installed (now checks the column
  first), and a `'` in the news text broke the Lua payload (now escaped).
  `third-party-patches/Breaking-News-Rewrite/0001-*.patch`, applied by
  `fetch.py`.
- **Breaking News content is HTML-driven here.** `BreakingNews.HtmlPath`
  points at `etc/modules/Updates.html` (host-mounted; the default
  `./Updates.html` is relative to the container's cwd and never resolves),
  `Cache = 0` so edits apply on the next login. When the file exists the
  conf's `News.Line*` and the live stats are NOT used -- it's one or the
  other in this module. Our text is tracked at `conf/breakingnews/
  Updates.html`; staging places it only if etc/modules has none.
- **Prestige's `Professions_Allow_Patch.sql` is 18 MB** of `INSERT IGNORE`
  into its own `dbc_spells` table -- the first db-import after enabling it
  takes noticeably longer. That's expected.
- **mod-uac starter weapons for Horde paladins.** Orc/Undead/Tauren/Troll
  paladins get Blood Elf's starter set incl. a 2H sword, but only Blood
  Elves get the Two-Handed Swords skill at creation, so the sword sat in the
  backpack. Same shape of problem, different cause, for **warlocks of every
  race**: individual-progression's pre-3.3 `player_starting_weapon_skills.sql`
  drops Staves from warlocks while every warlock outfit gives a Bent Staff.
  Both fixed in our `data/sql/db-world/base/starting_weapon_skill_fixes.sql`
  (sorts after both mods' files, which DELETE whole skills before inserting).
  If a combo shows up unarmed, compare `playercreateinfo_skills` with the
  outfit's weapon type -- it's always a one-row fix there.
- **mod-uac's own `patch-z.mpq` and Prestige's `patch-P.mpq` are not used.**
  Their contents are exactly the DBCs we merge; shipping them as well would
  reintroduce the last-one-wins problem they were merged to avoid.

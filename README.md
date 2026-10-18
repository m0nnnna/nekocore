# nekocore

Client and server work for the NekoCore realm, running on
[AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) (a 3.3.5a,
build 12340 server) plus
[mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression).

**Running a realm:** releases, `nekocore update`, backups and the build
are in [docs/releases.md](docs/releases.md). The notes below are the
development log; paths like `C:\nekocore\server` are from the old Windows setup.

**This repo holds only what we add.** It is not a fork of AzerothCore and does
not vendor the engine or the progression module -- both are read from the
live checkout at `C:\nekocore\server` (their own separate repos; see that tree's
`modules/` for the progression module). This repo is linked into
`C:\nekocore\server\modules\nekocore` via a real NTFS junction (see "Live and
confirmed working, on a second, separate AzerothCore checkout" below for why
a plain symlink doesn't work here), so a build picks it up without anything
being copied.

First project: per-character **era talents** -- a character genuinely in the
Vanilla (1.12.1) era plays with the real 1.12.1 talent trees for their class,
not a WotLK tree with a few old talents mixed in. Full authenticity, not a
blend, and per-character (two characters on the same realm can be in
different eras at once) -- see "Why per-character authenticity needs a
custom client UI" below for why that specific combination rules out simpler
approaches.

**Scope note (changed from this repo's original framing):** earlier commits
here describe this as server-only work, with client-side work deliberately
kept in `open-wow-client` (a separate from-scratch WoW client
reimplementation). That split made sense for the *additive* approach those
early commits pursued -- but that approach turned out not to be able to
reach real per-character authenticity at all (see below), and the
replacement approach needs a custom retail-client UI specifically. Rather
than split "the real implementation" across two repos, client and server
work for this feature both live here now.

## Why the first approach (additive, merged into WotLK's existing tabs) doesn't work

The early commits in this repo's history describe and build an *additive*
approach: inject Classic-only talents into WotLK's existing 3 tabs per
class, renumbered (`classic_id + 10_000`) to avoid id collisions, skipping
any talent whose spell doesn't exist in WotLK's own `Spell.dbc`. That
approach was live-tested successfully against `open-wow-client` (this
repo's original client counterpart) -- but two problems showed up only once
it was tested against the **real retail 3.3.5a client's own stock talent
UI**, which is the whole point of this repo now targeting that client
directly rather than a custom one:

1. **One shared `Talent.dbc`, no way to tell characters apart.** The file is
   loaded once by the client and used for every character who opens the
   talent frame. There's no branch available to Blizzard's stock UI for
   "this specific character is in the Vanilla era, show them different
   data." Reusing WotLK's existing tabs can, at best, sprinkle a few old
   talents into an otherwise-WotLK tree for *everyone* -- never full
   per-character authenticity, no matter how well the injection itself is
   done.
2. **A tab's rows must stay a contiguous, `(tier, column)`-sorted block in
   the file, or the retail client fails to render that entire tab.**
   Live-confirmed this session, the hard way: appending new rows at the end
   of the file (what the original tool did) broke whichever tab they
   belonged to -- not just the new talents, the *entire* tab, stock rows
   included. Isolated across several rounds of live testing against a
   patched retail client with `mpyq`/independent-reader-verified MPQ
   patches: not about talent id magnitude (ruled out with a
   deliberately-small test id), not about a tab's total row *count* (ruled
   out with a same-count swap test), specifically about file order. Fixed
   for the additive tool (`merge_talents.py`, now superseded -- see below)
   by inserting new rows at the correct sorted position within their tab's
   block instead of appending; the ordering rule itself carries forward
   into the new tool.

Problem 2 is fixable (and was, see `tools/build_patch/build_era_tree.py`'s
doc comment for the ordering invariant it maintains). Problem 1 isn't fixable
within the additive shape at all -- it's why this repo now builds each era's
tree under **brand-new, dedicated tab ids** instead, with a custom client UI
deciding which tab-set to show based on the viewing character's own era.

## The new approach: dedicated tabs per era + a custom talent UI

- **No new tabs reused from WotLK.** Each class's era tree gets its own
  fresh `TalentTab.dbc` ids (`9000 + class_id*10 + tree_index`, comfortably
  above WotLK's own max of 411) and the full authentic Classic layout is
  copied in verbatim -- real tier/column positions, no collision-avoidance
  relocation needed since nothing else lives in that tab id.
  `tools/build_patch/build_era_tree.py`.
- Talent ids still use `classic_id + 10_000` (same safe-offset finding as
  before, confirmed independently by the additive approach's own testing --
  large offsets like 900,000 break AzerothCore's `DBCStorage::LookupEntry`,
  a flat array sized to `max_id + 1` at load).
- Still skips (transitively) any talent whose spell doesn't exist in WotLK's
  `Spell.dbc` -- `Player::LearnTalent` silently no-ops otherwise. Since this
  approach isn't fighting WotLK for grid space, MORE of a class's era
  talents make it through than the additive approach could fit: Druid went
  from 8 (additive, collision-limited) to 33 (dedicated tabs, spell-existence-limited)
  for Vanilla.
  - **2026-09-21:** that ceiling is mostly gone. WotLK squashed many 5-rank
    Classic talents to 3 ranks (rank 1-3 spell ids kept, 4-5 deleted) and
    dropping the whole talent for that left the Vanilla Paladin Protection
    tab with an empty tier 0 -- an *unspendable* tab, since the 5-point
    gate for tier 1 could never be met (19 other era tabs had the same
    class of hole higher up). Talents are now kept with the leading ranks
    that exist, and `tools/build_patch/port_era_spells.py` ports the rank
    spells WotLK deleted from the 2.4.3 client (225 of them; the 60
    Vanilla-only ones already gone by TBC are reported, not ported) into
    `data/generated/Spell.dbc` -- the file the realm bind-mounts AND the
    client MPQ carries, so they stay in lockstep. `install_client.py
    --build` runs the port before the tree build. Every era tab is now
    reachable end to end: 784 -> 1003 era talents.
- **A custom Lua UI** (not built yet) replaces Blizzard's stock talent
  frame, so *we* control which tab-set displays based on the character's
  actual era (read from `mod-individual-progression`, which already tracks
  progression per character). The underlying DBC-driven tier-gating/prereq
  engine (`GetTalentInfo`, `CMSG_LEARN_TALENT`, AzerothCore's native
  validation) still does the real work -- the custom UI only needs to
  decide *which* tab ids to query/display, not reimplement talent-learning
  itself.
- Still needed, not built yet: a light server-side check so a character
  can't spend points in a tab that doesn't match their current era (the one
  piece likely needing an AzerothCore hook -- check what's available before
  assuming a core patch is required).

## Live state right now

The local realm's `Talent.dbc`/`TalentTab.dbc` are not stock.
`docker-compose.override.yml` bind-mounts `C:/nekocore/data/generated/Talent.dbc`
and `TalentTab.dbc` over the worldserver's copies. `build_era_tree.py`'s
`--class` flag is repeatable -- **all 9 classes with Vanilla-era talent
trees existing** (everything except Death Knight, which didn't exist pre-
WotLK) are built in one run now: 319 new talents across 27 new dedicated
tabs (ids 9020-9112, `9000 + class_id*10 + tree_index`). A plain `restart`
is enough to pick up new DBC *content*; only a *path* change (e.g. adding a
file that wasn't mounted before) needs `up -d` to re-create the container.

The matching client patch (same two files, packaged via
`tools/mpq/mpq_writer.py` -- a from-scratch MPQ v0 writer, since neither
this repo's tooling nor `open-wow-client`'s can *write* an archive, only
read one) is deployed to the local retail 3.3.5a test client as
`Data\patch-Z.mpq` and `Data\enUS\patch-enUS-4.MPQ` (this client already has
third-party lettered patches from another launcher, `patch-J/U/V.mpq`,
whose exact load-order mechanism isn't confirmed -- both locations are
covered defensively until that's pinned down).

**Confirmed dead end (live-tested):** the stock client's talent frame does
NOT handle a class having more than 3 matching tabs gracefully -- on this
specific client (a third-party-modified `Blizzard_TalentUI`/
`TalentFrameBase.lua`, confirmed by extracting and reading its actual
source: neither file is stock size) it shows a bogus "Activate These
Talents" button and blanks every tab, not just the new ones. Root cause not
fully chased down (the code checks `GetNumTalentGroups() > 1`, which
diagnostic tooling showed returns 1, so something else in this specific
patched build is misfiring) -- not worth fully diagnosing since the whole
point is replacing that code path, not fixing it. The underlying data API
(`GetNumTalentTabs`, `GetTalentTabInfo`, `GetTalentInfo`) all correctly see
and describe the new tabs regardless -- confirmed via a diagnostic addon
(`/ntd`, `client-patch/Interface/AddOns/NekoTalentDebug`) before writing any
UI code, so the custom frame's calls weren't guesswork.

**Custom UI: first working slice built and live-validated.**
`client-patch/Interface/AddOns/NekoTalentUI` -- a standalone frame (`/neko`),
not a stock-frame replacement yet, showing a character's 3 Vanilla-era tabs
(`ERA_TAB_START = 4` -- "stock is always tabs 1-3, era blocks stack after in
groups of 3" -- works unmodified for every class now, not just Druid:
`GetNumTalentTabs`/`GetTalentInfo` are already scoped to the *viewing
character's own class*, so tab index 4 is that class's era-Balance-
equivalent regardless of which class it is). Calls the exact same API the stock frame does
(`GetTalentInfo`/`GetTalentTabInfo`/`LearnTalent`) for the new tab indices,
so no talent-learning logic was reimplemented -- confirmed live: icons
render in correct grid positions (tier/column, remembering the API's tier/
column are 1-indexed, unlike Talent.dbc's own 0-indexed fields), tooltips
work, and clicking a talent actually spends a point through the real
server round-trip (rank number and points-spent counter updated correctly).

AddOns load from loose files on disk, not from inside MPQ archives (only
DBC/model/texture-type data does) -- `NekoTalentDebug` and `NekoTalentUI`
are deployed as real folders under the test client's
`Interface\AddOns\`, not packaged into the `.mpq` patch.

**`/neko` now replaces the stock talent window outright, not just a
slash-command extra.** `NekoTalentUI` rebinds the default `N` keybind
(`SetBindingClick` pointed at a hidden button, `SaveBindings(1)` so it's
account-wide and persists) to call the addon's own `Toggle()` instead of the
stock (broken, per above) talent frame -- live-confirmed working. Visuals
were also cleaned up to read as an intentional WotLK-style panel rather than
a debug scaffold: right-sized/centered frame (no more dead space showing the
3D world behind it), talent icons get real slot art with state-dependent
coloring (gold border+text when maxed, greyed/desaturated when a prereq
isn't met), a spec icon and live "talent points available" readout, and
Escape-to-close (`UISpecialFrames`).

**Era-lock enforcement (`src/EraTalentGate.cpp`): written, not yet built.**
Without this, nothing server-side stops a character from spending points in
an era's tabs regardless of their actual `mod-individual-progression`
state -- the custom UI only controls what's easy to reach, not what's
actually possible (a macro/addon could still send `CMSG_LEARN_TALENT`
directly for any talent id in the client's `Talent.dbc`).

Hook point: `ServerScript::CanPacketReceive`, called by AzerothCore core
*before* the real opcode handler runs (confirmed by reading the actual call
sites in `WorldSession.cpp`, not assumed) -- exactly what this repo's
original README predicted before it was verified: "AzerothCore supports
this without patching core source." No core patch needed. The packet object
passed to this hook is documented as a COPY of the original, so peeking at
it here doesn't disturb what the real handler reads afterward.

Logic: if the talent's `TalentTab` falls in the reserved Vanilla-era range
(9000-9999, matching `build_era_tree.py`'s `new_tab_id()` allocation) and
the player hasn't reached `PROGRESSION_PRE_TBC` yet per
`mod-individual-progression`'s own per-character tracking, the packet is
dropped with a chat message; everything else passes through untouched.

**Live and confirmed working, on a second, separate AzerothCore checkout.**

The original checkout at `C:\azerothcore-wotlk` turned out to carry
non-standard patches (its `Player.cpp` etc. attributed "xinef:" in comments)
that query `creature.id1/id2/id3` -- columns that don't exist in standard
AzerothCore schema (confirmed directly: real schema uses plain `id`). That
checkout's C++ and its own SQL files disagree with each other, and it
predates this feature's needs by 9 months (2025-12-07) regardless. Rather
than patch a fork mismatch blind, stood up a second, completely fresh
checkout at `C:\nekocore\server` -- clean clone of upstream `azerothcore-wotlk`
(2026-09-15), clean clone of `mod-individual-progression` (2026-08-30,
`AREA_SILVERMOON_CITY` fix re-applied -- see `IndividualProgression.cpp`,
genuinely missing from the module's own enum, not core-version-dependent),
this repo re-linked in via a real NTFS junction (`mklink /J`, not `ln -s` --
Git Bash's symlink silently became a one-time directory *copy* on this
system instead of a live link, which cost a wasted build cycle before being
caught). Initially ran on offset ports/container names alongside the old
stack for testing; explicitly did NOT migrate any database data (fresh
`acore_world` from the current base dump).

**Cutover complete: this is now the live stack, on standard ports.**
`C:\azerothcore-wotlk`'s containers are stopped and removed (`docker compose
down`, confirmed zero characters online first), its stale locally-built
images cleaned up. `C:\nekocore\server` now runs as `ac-database`/`ac-authserver`/
`ac-worldserver` on the standard ports (3306/3724/8085/7878) -- same ports
and same LAN address (`<DEV-LAN-IP>`) external DNS/routing already pointed
at, so no outside reconfiguration needed. One thing the fresh install got
wrong that needed a manual fix: `realmlist.address` defaulted to
`127.0.0.1` (only reachable from the host itself) instead of the LAN
address real clients need -- corrected directly in `acore_auth.realmlist`.

Two things this uncovered, both fixed:
- `ServerScript::CanPacketReceive`'s signature changed to
  `WorldPacket const&` at some point after this repo's original reference
  -- `EraTalentGate.cpp` now takes a local mutable copy before reading it
  (`operator>>` mutates read position, can't be called on a const ref).
- `ac-db-import` is **also** built from local source (own Dockerfile
  target, same as `ac-worldserver`) -- using the prebuilt Docker Hub image
  for it (the default) means it has no idea this module's SQL
  (`data/sql/world/base/*.sql`, including the `custom_quest_xp` table
  `IndividualProgression.cpp` loads on startup) even exists. Needs
  `docker compose build ac-db-import` too, not just the worldserver.

## Bug found in live GM testing: new tabs excluded Blood Elf/Draenei

`build_era_tree.py` originally copied the CLASSIC tab's own `RaceMask` onto
each new tab row. That mask has zero bits for any race added after 1.12.1
(Blood Elf, Draenei simply didn't exist yet), so a Blood Elf Rogue saw only
the 3 stock tabs -- `GetNumTalentTabs()` correctly (from the game's
perspective) excluded a tab whose race mask didn't include their race.
Druid and Priest testers didn't hit it purely because their characters
happened to be on races that already existed in Classic (Druid especially:
restricted to Night Elf/Tauren by the class itself, both pre-existing).
Traced with `NekoTalentDebug` extended to probe tab indices 1-9 directly
(not just trust `GetNumTalentTabs()`'s count) -- confirmed tabs 4+ were
fully invisible to the client's talent API for the affected character, not
just miscounted. Fixed: use WotLK's own stock tab RaceMask (all races) for
every new tab instead -- race eligibility for the class is already enforced
at character creation, the talent tab itself shouldn't re-restrict by race.
Rebuilt and redeployed for all 9 classes with the fix.

Confirmed end to end: `docker compose build ac-worldserver && docker compose build ac-db-import`,
fresh `acore_world` import (module SQL included this time), `docker compose up -d ac-worldserver`
-- **`WORLD: World Initialized In 0 Minutes 17 Seconds`**, stable, no crash loop.

## Layout

```
tools/
  dbc/               WDBC read/write, per-build schemas (Talent/TalentTab/
                      SpellIcon/Spell for 1.12.1, 2.4.3, 3.3.5a), MPQ source
                      resolution (patch-priority aware), a StringBlockBuilder
                      for interning new strings across a build's string block
  mpq/               mpq_writer.py -- minimal MPQ v0 archive writer
  extract_era_data/  pulls a class's full talent tree + spell effect data
  build_patch/
    build_era_tree.py  current tool: builds one class's full era tree under
                        dedicated new tab ids
  install_patch/
    install_client.py  builds (optional), packages, and deploys everything
                        in one command against a real client install -- see
                        "Distributing this" below
data/
  generated/         build_era_tree.py's output (gitignored -- derived from
                      Blizzard's data, not ours to commit)
  vanilla/, tbc/      mapping CSVs we authored (kept) + extracted talent/
                      spell JSON (gitignored)
  sql/               database changes, once there are any
client-patch/         Interface/AddOns/* (real addon source, committed) +
                      the packaged MPQ patch (gitignored, see below)
src/                 EraTalentGate.cpp/nekocore_loader.cpp -- the live
                      AzerothCore module (junctioned into
                      C:\nekocore\server\modules\nekocore). Also still holds the
                      ORIGINAL additive-approach Rust tools
                      (build_talent_merge.rs, dbc.rs), kept for history only,
                      superseded by tools/build_patch/build_era_tree.py.
docs/                notes that don't belong in commit messages
website/             the public site + its Docker image (runs as the
                      neko-website service in the server stack, port 8088)
server/              the live AzerothCore checkout (moved from
                      D:\AzerothCore on 2026-09-18). GITIGNORED -- it is its
                      own git repo with its own history; everything of ours
                      reaches it through tools/server/sync_module.py,
                      core-patches/, and server/docker-compose.override.yml.
                      Run all `docker compose ...` commands from here.
                      COMPOSE_PROJECT_NAME=azerothcore in server/.env keeps
                      the pre-move volume/container names, so the database
                      volume is still azerothcore_ac-database.
```

## Building an era tree

```
python tools/build_patch/build_era_tree.py \
  --source-build 1.12.1 --source-root "D:\Games\World of Warcraft 1.12.1" \
  --wotlk-root "D:\Games\World of Warcraft 3.3.5a" \
  --class druid --class warrior --class mage \
  --out-dbc-dir data/generated \
  --out-mapping-dir data/vanilla
```

Both `--source-root` and `--wotlk-root` must point at your own
legitimately-owned client installs -- this repo doesn't ship or fetch any
Blizzard game data. `--class` is repeatable in one run (required to add
classes without losing ones already built -- see the tool's own doc comment
for why).

## Distributing this: repo scope, and patching a stock client

**What's safe to commit, and what never is.** The addon Lua/`.toc` files
under `client-patch/Interface/AddOns/` are entirely our own code -- no
Blizzard data in them -- so they're committed normally, same as any other
source file in this repo. The generated `Talent.dbc`/`TalentTab.dbc` and the
MPQ that packages them are a different story: even though the *new* rows are
ours, the file as a whole is Blizzard's own binary format wrapped around
Blizzard's own stock rows plus ours -- derived data, not something we're
free to redistribute. `.gitignore` blocks `*.dbc`/`*.mpq` for exactly this
reason (the same rule `open-wow-client` follows). So: **addons ship as
committed source in this repo; DBCs/MPQs are never committed, only ever
built locally** by each person against their own legitimately-owned client
files.

That means "provide a repo of client + server" already has a clean answer
with no extra packaging step needed:
- **Server** = this repo's `src/` synced into a real AzerothCore checkout
  (`C:\nekocore\server\modules\nekocore\src`, via `tools/server/sync_module.py`
  -- see "Docker couldn't see the module at all" below for why this is a
  copy, not a live link) + the module's own C++ (`src/EraTalentGate.cpp`,
  `src/EraProgressionSync.cpp`, `src/nekocore_loader.cpp`) built into the
  worldserver image.
- **Client** = this repo's `client-patch/Interface/AddOns/*` (committed,
  plain files -- can be copied straight out of a checkout, no release/zip
  step required) plus a locally-built DBC patch MPQ (never committed, see
  above).

**Patching a stock client end to end** is now one command, replacing what
had been done by hand all session
(`tools/install_patch/install_client.py`):

```
# Full rebuild, both eras (pass whichever era roots you want represented --
# omitting one drops that era from this run's output, same as
# build_era_tree.py itself)
python tools/install_patch/install_client.py \
  --wotlk-root "D:\Games\World of Warcraft 3.3.5a" \
  --vanilla-root "D:\Games\World of Warcraft 1.12.1" \
  --tbc-root "D:\Games\World of Warcraft 2.4.3" \
  --build

# Redeploy already-built data/generated/*.dbc + addons, no rebuild
python tools/install_patch/install_client.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a"

# Fast path while iterating on Lua only -- skips the DBC/MPQ step entirely
python tools/install_patch/install_client.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a" --addons-only
```

It writes the built DBCs into an MPQ (`DBFilesClient\Talent.dbc`/
`TalentTab.dbc`, via `tools/mpq/mpq_writer.py`) staged at
`client-patch/patch-nekocore-talents.mpq` (gitignored), copies that to the
client's `Data\patch-Z.mpq`, and copies every addon folder under
`client-patch/Interface/AddOns/` into the client's own `Interface\AddOns\`.
Live-tested end to end against the real test client (identical rebuild
output confirmed byte-for-byte against what had been hand-deployed all
session) -- the only failure mode hit was the client having `patch-Z.mpq`
open while running, which the script now reports clearly instead of a raw
traceback.

## TBC era added; N now auto-detects which era to show

`build_era_tree.py` is now era-aware, not Vanilla-only. Each era gets its
own disjoint id range so both can be built into the same output DBCs at
once (see the tool's own doc comment for the full table): Vanilla stays at
tab ids `9000 + class_id*10 + n` / talent ids `classic_id + 10_000` (both
unchanged, wire-compatible with everything built earlier); TBC is new, at
tab ids `8000 + class_id*10 + n` / talent ids `classic_id + 20_000`. Eras
are always processed in a fixed order (Vanilla before TBC) regardless of
which `--*-root` flags a run passes, so a class's tab INDEX (what the
client's own `GetNumTalentTabs`/`GetTalentTabInfo` report, what
`NekoTalentUI` keys off) is stable: 1-3 stock WotLK, 4-6 Vanilla, 7-9 TBC.
Ran for real against all 9 eligible classes with both eras: 87 tab rows (33
stock + 27 Vanilla + 27 TBC), 1676 talent rows (892 stock + 784 new) --
verified the tab ordering directly against the generated DBC before
trusting the client-side assumption above.

`EraTalentGate.cpp` now gates the TBC range too, not just Vanilla: a TBC
talent is only learnable while `hasPassedProgression(PROGRESSION_PRE_TBC)`
AND `isBeforeProgression(PROGRESSION_TBC_TIER_5)` -- i.e. actually inside
the TBC window, not before or after it. `PROGRESSION_TBC_TIER_5` is the
module's own boundary for "WotLK Naxx/EoE/OS" (first WotLK content), taken
directly from its enum comments.

**New: automatic talent reset on era transition
(`src/EraProgressionSync.cpp`).** Without this, a character crossing an
era boundary would keep whatever points they'd sunk into the era they just
left (which the gate above locks them out of re-spending, but doesn't
refund) and have nothing free to spend in the era they just unlocked. No
1:1 remapping of old points onto the new tree is attempted -- not
generally possible (different trees, different counts/prereqs per era),
and not what a real expansion launch did either: a full free respec, same
as this. Detecting the crossing: mod-individual-progression tracks
progression entirely via hidden REWARDED QUESTS (id `66000 + state`, read
directly from `IndividualProgression.cpp`'s
`GetPlayerProgressionFromQuests`/`UpdateProgressionState` -- there's no
separate "progression changed" signal the module fires for other code to
hook). So rather than forking that module, this hooks the standard
`PlayerScript::OnPlayerCompleteQuest` (confirmed fired from
`Player::RewardQuest` by reading the actual call site in
`PlayerQuest.cpp`, not assumed) and checks for exactly the two quest ids
that correspond to `PROGRESSION_PRE_TBC` (66008) and
`PROGRESSION_TBC_TIER_5` (66013) -- every other progression-quest reward is
ignored. On a match: `player->resetTalents(true)` (free, no gold cost --
this is a forced transition, not the player's own choice to respec) plus a
chat message telling them to press N.

`NekoTalentUI.lua` no longer hardcodes which era to show. `DetectEra()`
reads the SAME two quest ids via plain client Lua
(`IsQuestFlaggedCompleted`, no server round-trip needed -- the client
already has this state from normal quest-log sync) and `SetEra()` repoints
the frame at that block's 3 tabs, refreshing the tab labels and title.
Falls back to tabs 1-3 (native WotLK) once a character is past both
boundaries.

## Bug found (this cost most of a session): Docker couldn't see the module at all

**Everything server-side this project has done -- `EraTalentGate.cpp`
included -- had never actually been compiled into any worldserver build,
this entire project, until just now.** Not a caching problem, not a
subtle one: the module's C++ was invisible to Docker from the start.

How this was missed for so long: the client-visible parts of the
Vanilla-tabs work (the RaceMask fix, tab counts in `/ntd`, talent
point-spends actually landing) are ALL driven by `Talent.dbc`/
`TalentTab.dbc`, delivered via a direct `docker-compose.override.yml`
volume bind mount -- pure data, no compilation involved. Every one of
those checks genuinely passed. The one thing that was never actually
exercised was `EraTalentGate.cpp`'s own job: blocking `CMSG_LEARN_TALENT`
packets server-side. It looked done because everything *observable*
worked; the actual enforcement code was simply never in the binary.

Root cause: `C:\nekocore\server\modules\nekocore` was an NTFS junction
(`mklink /J`) pointing at `C:\nekocore`, set up earlier in the session
specifically to fix an EARLIER, DIFFERENT bug (Git Bash's `ln -s`
silently becoming a one-time directory *copy* instead of a live link).
The junction genuinely works at the Windows filesystem level -- `dir`,
`ls`, everything on the host sees real, current content through it. But
inside the Docker build container, `modules/nekocore` showed up as:
```
lrwxrwxrwx 1 root root 11 ... nekocore -> C:/nekocore
```
A symlink whose target is the literal string `C:/nekocore` -- meaningless
inside a Linux container, so every build silently compiled as if the
module didn't exist: no error, no warning, `file(GLOB ...)` just found an
empty/dangling path and moved on. Confirmed directly (not inferred): after
a genuine `--no-cache` rebuild, `grep -a -c nekocore` against the built
`worldserver` binary returned **zero** -- not even the bare word
"nekocore" appeared anywhere, while `grep -a -c IndividualProgression`
(a module that actually works) returned 4. Rebuilding the `build` stage
specifically and `ls`-ing inside it confirmed the dangling symlink
directly.

**Fix: no more links for anything Docker needs to build from.**
`tools/server/sync_module.py` copies this repo's `src/` into
`C:\nekocore\server\modules\nekocore\src` as real files. Run it before every
`docker compose build ac-worldserver` -- there's no build hook that does
this automatically yet, so it's a manual step for now. Slower to iterate
than a live link would have been, but a live link demonstrably doesn't
work through Docker Desktop's build-context handling on this machine, for
either symlinks or junctions -- a copy is the only mechanism confirmed to
actually work.

**Also hit, unrelated to the above:** Docker Desktop's backend crashed
outright mid-build twice (`failed to receive status: rpc error: code =
Unavailable`, then the `dockerDesktopLinuxEngine` pipe disappearing
entirely) -- caused by a second, separate agent session building against
the same Docker Desktop instance at the same time. Not a code issue;
resolved by the user restarting Docker Desktop. Worth remembering if
builds fail with a connection error rather than a compiler error: check
`docker info` actually responds before assuming the build itself is
broken.

## Nine more modules imported and compiling

At the user's request, imported the rest of the module roster this realm
needs before deploying for real: `DungeonRespawn`, `mod-assistant`,
`mod-dungeonmaster`, `mod-autobalance`, `mod-solo-lfg`, `mod-transmog`
(all public, cloned fresh from GitHub -- see each module's own repo for
credits/license) plus `mod-live-reload` and `mod-xp-changer` (hand-written,
no public repo -- recovered from the old, decommissioned
`C:\azerothcore-wotlk` checkout, where they existed but had never actually
been migrated to the live `C:\nekocore\server` server despite being assumed
already-present). All ten modules (these eight plus
`mod-individual-progression` and `nekocore`) now compile and link into the
same worldserver binary, confirmed live: `WORLD: World Initialized In 0
Minutes 15 Seconds`, container stable.

None of these compiled cleanly on first try against this specific
(newer-than-most-modules-expect) AzerothCore checkout. Fixed, in order
hit:
- **`DungeonRespawn`**: three `PlayerScript` hooks were declared `override`
  against names that no longer exist -- `OnBeforeTeleport`, `OnMapChanged`,
  `OnLogin`, `OnLogout` were all renamed (to `OnPlayerBeforeTeleport`,
  `OnPlayerMapChanged`, `OnPlayerLogin`, `OnPlayerLogout`) at some point
  after this module's 2023 archival. `override` makes a genuine rename a
  compile error, not silent breakage -- caught immediately.
- **`mod-solo-lfg`**: same rename pattern, but WITHOUT `override` on the
  two `OnLogin` hooks -- meaning this module's core functionality (toggle
  solo LFG on login) would have compiled fine and then silently never
  fired, forever. Caught only by cross-checking every new module against
  the same rename list after finding it in `DungeonRespawn`. Renamed both
  to `OnPlayerLogin` with `override` added.
- **`mod-solo-lfg`, deeper issue**: also needs `LFGMgr::IsSoloLFG()`/
  `ToggleSoloLFG()`, which don't exist in upstream `azerothcore-wotlk` at
  all -- this module was written against a fork with that core-level
  feature already built in. Its own `lfg-solo.patch` adds them (small,
  ~4 hunks across `LFGMgr.cpp`/`.h`/`LFGQueue.cpp`), but didn't apply
  cleanly (`git apply` failed -- line numbers drifted from whatever
  revision it was cut against). Applied by hand instead, same net effect.
  **This is a real modification to `C:\nekocore\server\src` itself**, not just
  a module -- flagged to the user before applying (approved). Now owned
  going forward, not left as a silent local diff: `mod-solo-lfg` itself is
  forked to [`m0nnnna/mod-solo-lfg`](https://github.com/m0nnnna/mod-solo-lfg)
  (the local checkout's `origin`; `upstream` still points at
  `milestorme/mod-solo-lfg`) with the `OnPlayerLogin` fix pushed there, and
  the `LFGMgr` core patch is committed locally in `C:\nekocore\server`'s own
  git history (not pushed anywhere -- it's core source, forking the whole
  core wasn't asked for, just tracked so a fresh checkout of this exact
  revision doesn't lose it).
- **`mod-live-reload`**: two renamed `ObjectMgr`/`SpellMgr` methods --
  `LoadTrainerSpell` -> `LoadTrainers`, `LoadSpellProcEvents` -> merged
  into `LoadSpellProcs` (this module was calling both back to back; now
  calls the merged one once).
- **Our own `EraProgressionSync.cpp`**: `#include "Quest.h"` -- wrong
  header name for this checkout, actual class lives in `QuestDef.h`. Not
  a third-party issue, just a wrong guess at the header name that only
  surfaced once nekocore was actually visible to the build (see above).
- **SQL schema drift, `mod-dungeonmaster` and `mod-xp-changer`**: both
  ship a `creature_template` INSERT listing columns this schema doesn't
  have anymore -- `scale` (moved entirely to
  `creature_template_model.DisplayScale`, which both files already also
  set correctly) and, for `mod-dungeonmaster` specifically,
  `trainer_type`/`trainer_spell`/`trainer_class`/`trainer_race` (trainer
  config moved off `creature_template` entirely) and
  `mechanic_immune_mask`/`spell_school_immune_mask` (replaced by a single
  `CreatureImmunitiesId` FK). Fixed by dropping the obsolete columns from
  both the column list and the values tuple (verified column-count ==
  value-count programmatically before rerunning, not just by eye).
- **SQL not being picked up at all, same two modules**: both ship their
  SQL under `sql/world/base/`, `sql/characters/base/` -- an older
  module-SQL convention this checkout's updater doesn't scan. It only
  scans `data/sql/db-<dbname>/...` (confirmed by comparing against
  `DungeonRespawn`/`mod-transmog`, which use that convention and were
  picked up immediately). Fixed by copying (not moving) each file into
  the `data/sql/db-<dbname>/base/` path alongside the originals.

`ac-db-import` needed its own rebuild-from-local-source pass too, same
gotcha as `mod-individual-progression`'s `custom_quest_xp` table earlier
in this project (the prebuilt Docker Hub image has no idea any module SQL
exists) -- `docker compose build ac-db-import` before every
`docker compose up ac-db-import`, not just for the worldserver.

An unrelated `ac-client-data-init` failure (`Permission denied` deleting
existing `vmaps/*.vmo` files) blocked a plain `docker compose up -d
ac-worldserver` -- pre-existing, nothing to do with any module here (map/
vmap data, not compiled code). Worked around with `--no-deps` to start
just the worldserver directly; not investigated further since it's outside
this session's scope, but worth knowing about before the next full `up`.

## Ops tooling for the move to a Linux (Alpine) box

Two small scripts, both plain `/bin/sh` (Alpine's `ash`, not bash -- no
bashisms) so they need nothing beyond Docker on the target box, same as
everything else here:

- **`tools/server/apply_module_sql.sh [azerothcore-dir]`** -- wraps the
  exact `docker compose build ac-db-import && docker compose up
  --exit-code-from ac-db-import ac-db-import` flow used throughout this
  project, so it's one call instead of two, and so a failed import
  actually exits non-zero (plain `docker compose up` always exits 0
  regardless of the service's own exit code -- `--exit-code-from` is
  required, not optional, learned by having a failed import look
  identical to a successful one at the shell level).
- **`tools/server/backup_db.sh <db-name> [azerothcore-dir] [backup-dir]
  [keep-count]`** -- dumps one database via `docker exec ac-database
  mysqldump` (runs inside the container, needs nothing installed on the
  host), gzips it, prunes down to `keep-count` most recent. Meant for
  cron: `acore_world` daily, `acore_auth`/`acore_characters` hourly (see
  the script's own header comment for the actual crontab lines). Reads
  `DOCKER_DB_ROOT_PASSWORD` out of `.env` rather than hardcoding it, so
  the same script works against whatever password the target box's
  compose stack actually uses. Live-tested against all three databases on
  the current dev box, including retention pruning (deliberately dropped
  keep-count to 2, confirmed the oldest backup actually got removed).

## Mana Burn wasn't scaled by mod-autobalance -- now it is

`src/AutoBalanceManaBurnFix.cpp`. mod-autobalance's damage-scaling hooks
fire on a spell's FINAL computed damage total (see
`ABUnitScript.cpp::_Modify_Damage_Healing`) -- fine for ordinary damage
spells, but Mana Burn (`SPELL_EFFECT_POWER_BURN`,
`Spell::EffectPowerBurn` in core) drains a FLAT, unscaled amount of the
target's mana straight from the spell's own Spell.dbc base value, and
only the RESULTING 1:1 HP damage from that drain flows into the pipeline
AutoBalance hooks into -- the mana lost itself never passes through
anything AutoBalance-aware. A boss scaled down for a smaller group still
drains the exact same chunk of mana set for a full raid, even though the
HP damage number that results gets correctly reduced.

Found the affected spells in two passes, not guessed. First pass: grepped
`src/server/scripts` for every "Mana Burn"-named ability this core's own
boss scripts cast (5 ids). Second pass: the user had already researched
this exact problem and had a much bigger list sitting in two local files
(`mana-burn-update-spell_dbc.sql` / `manaburn-update2-spell_dbc.sql`, 76
ids combined -- their own prior attempt at a fix, see below). Every id
from the combined list was verified directly against `Spell.dbc` before
being trusted, not carried over on faith: confirmed 76/76 genuinely have
a `SPELL_EFFECT_POWER_BURN` effect, and recorded which effect SLOT each
one uses (65 at effect 0, 9 at effect 2, 1 at effect 1 -- NOT all effect
0 like the first pass's 5-spell sample happened to be). One id, 8129 (the
player Priest talent -- the one id `EffectPowerBurn` itself special-cases
as a percentage of max mana rather than a flat amount), is deliberately
excluded: players aren't AutoBalance-scaled, it already has its own core
SpellScript (`spell_pri_mana_burn`), and `spell_script_names` is one
`ScriptName` per spell id so a second script there would conflict with
that existing one anyway. Final list: 75 spells.

The user's own prior attempt at this (those two local SQL files) worked
by directly overwriting each spell's row in the `spell_dbc` table --
AzerothCore does support server-side per-spell overrides this way
(`LOAD_DBC(sSpellStore, "Spell.dbc", "spell_dbc")` in `DBCStores.cpp`,
confirmed by reading it), but that's a static, one-time value change --
doesn't respond to encounter size the way a dynamic per-cast multiplier
does, which is exactly why a real fix needed to scale instead. Checked
whether those files had ever actually been applied to this database
before building the new fix: `spell_dbc` has 4517 rows total but zero for
any of these 76 ids, confirmed directly -- never applied, nothing to
revert.

Fix is a `SpellScript` on `OnEffectLaunchTarget` (fires just before the
core's own effect handler runs, confirmed via a real existing core example
doing the same kind of thing --
`pet_dk.cpp::spell_pet_dk_gargoyle_strike`, not assumed to work) that
multiplies the effect's base value by the CASTER's `ScaledDamageMultiplier`
-- read directly out of mod-autobalance's own `AutoBalanceCreatureInfo`
CustomData, the exact same field its own damage-scaling logic uses. No
change to mod-autobalance itself needed: its `src/` is on the same shared
include path every static module builds against (confirmed against
`modules/CMakeLists.txt`'s `CollectIncludeDirectories`, not assumed), so
`#include "ABCreatureInfo.h"` from a different module just works. Defaults
safely to a 1.0 no-op for any caster AutoBalance hasn't touched -- so this
is a live, per-cast multiplier read fresh every time, not a value baked
into any table.

Three near-identical `SpellScript` classes, one per effect slot
(`_e0`/`_e1`/`_e2`), not one class hooking all three slots on every spell:
the spell-script loader validates each registered hook against the
target spell's actual effect data at startup and logs a warning for any
mismatch (harmless -- the matching hook still fires fine -- but hooking
all 3 slots on all 75 spells produced ~140 spurious "did not match dbc
effect data" warnings on every boot, caught by actually reading the
startup log rather than assuming a clean build meant a clean boot). Each
spell registered under whichever ONE class matches its own real effect
slot instead. Registered via `RegisterSpellScriptWithArgs` (not the plain
`RegisterSpellScript` macro, which always uses the class's own name and
can't be reused across multiple spell ids) under 75 different
`ScriptName`s -- bound to their spell ids via
`data/sql/db-world/base/mana_burn_scaling.sql`, nekocore's first SQL file
(`tools/server/sync_module.py` now syncs `data/sql/` the same way it
already synced `src/`, for the same reason -- see "Docker couldn't see
the module at all" above). Confirmed live: binary contains all 75 symbols,
server boots clean with zero `spell_script_names`/"not assigned"/"did not
match dbc effect data" warnings for any of the 75 entries, and all 75 rows
are actually in `acore_world.spell_script_names`.

## Live-toggleable raid lock, and every module now has a real config file

`src/RaidLock.cpp` -- for "no one can charge through a broken game" while
fights are being tuned. Checked first whether mod-individual-progression's
own `IndividualProgression.ProgressionLimit` already covered this (it
seemed like the obvious fit and the user guessed it might already exist)
-- it doesn't: that config only gates ADVANCING to a new progression
stage, not entry into a specific instance, and Molten Core specifically
has no progression gate on it at all in that module (checked
`instance_molten_core.cpp` directly -- it's open from
`PROGRESSION_START`, being the very first raid). So this is new,
deliberately generic (any map id, not hardcoded to MC) since the same
need will come up for every raid as balancing work moves on to the next
one.

Hook: `PlayerScript::OnPlayerBeforeTeleport`, confirmed at its actual core
call site (`Player::TeleportTo` in `Player.cpp`: `if
(!sScriptMgr->OnPlayerBeforeTeleport(...)) return false;`) -- returning
false aborts the teleport before anything happens, for every way a player
can land on a map (portal, hearthstone, GM teleport, group summon all
funnel through `TeleportTo`), not just walking through one specific
entrance. GM accounts always pass through
(`WorldSession::IsGMAccount()`, the same check core itself uses) so
testing/tuning a locked raid stays possible for whoever's doing the work.

Config: `Nekocore.LockedMaps`, a comma-separated list of map ids
(`conf/nekocore.conf.dist` -- nekocore's first conf file,
`tools/server/sync_module.py` now syncs `conf/` too, same reasoning as
`data/sql/`). Currently set to `409` (Molten Core). Live-reloadable:
`WorldScript::OnBeforeConfigLoad` re-parses it on `.reload config`, no
restart needed -- same hook mod-individual-progression's own config
loading uses, confirmed it fires on both startup and reload, not
startup-only.

**Also found and fixed while wiring this up: every module on this server
was silently running on baked-in `.conf.dist` defaults.** None of the 9
modules (this one included) had an actual `.conf` file -- only the
`.conf.dist` templates existed under `env/dist/etc/modules/`, confirmed
directly (`ls` showed `*.conf.dist` and nothing else), and the worldserver
boot log had been quietly logging `Config::LoadFile: Failed open file
'.../individualProgression.conf'` / `Not found modules config files` this
whole project without anyone noticing, since a missing module conf just
silently falls back to hardcoded defaults rather than erroring. Fixed by
copying every `<name>.conf.dist` to `<name>.conf` in
`env/dist/etc/modules/` (bind-mounted from `C:\nekocore\server\env\dist\etc`,
confirmed persistent across container rebuilds, not baked into the
image). After a restart, boot log now shows `Using modules configuration:`
listing all 8 real `.conf` files loaded, zero "Failed open file" warnings.

## Fixed a real pathfinding bug that looked like log spam

Flagged as "small picky note" but wasn't cosmetic: `MMapMgr::LoadTile`
(core, `MMapMgr.cpp`) hard-rejects any `.mmtile` whose generator version
doesn't match what this binary expects (`return false`, tile never loads)
-- so the constant `MMAP:loadMap: ... was built with generator v19,
expected v20` spam meant creature pathfinding was genuinely missing, not
just noisy, across every affected tile.

Root cause: `ac-client-data-init` (the container that installs Blizzard
map/vmap/dbc data) had been silently failing this entire project --
`env/dist/data` on disk was owned by root, but that container runs as
`acore` (uid 1000), so it couldn't overwrite anything and quietly gave up
partway (the "Permission denied" errors flagged as "pre-existing,
unrelated" back when the raid-lock work first hit them -- turned out to
be very related). Fixed the ownership (`chown -R 1000:1000` on the data
dir), reran it, confirmed `data-version` went from `v19` to `v20.0`.

That got the data package current, but 352 tiles across 5 maps (000
Eastern Kingdoms, 001 Kalimdor, 369, 530 and 571 Outland/Northrend) still
carried old-generator mmaps even in the fresh v20.0 package -- confirmed
the "v20.0" data-package label and the mmap file's own internal
"generator vX" number are two unrelated versioning schemes that just
happen to collide in this warning text. Built `mmaps_generator` (and its
sibling extractor tools) from this exact checkout's own source via the
Dockerfile's existing `tools` stage (`docker build --target tools`,
reuses the cached compile from the worldserver build) so the regenerated
tiles are guaranteed to match what THIS binary's `MMAP_VERSION` expects.
Single-tile mode (`--tile X,Y`) silently produced nothing for reasons not
fully run down; full-map mode (`mmaps_generator <mapId>`, no `--tile`)
worked cleanly once existing tiles for that map were deleted first (the
tool skips tiles that already exist, confirmed by testing -- its own doc
comment already said as much, just easy to miss). One parser quirk hit
along the way: the map-id argument only accepts the literal string `"0"`
for map zero, not `"000"` -- passing `"000"` fails with "invalid
parameters" (a strict `strcmp` in the tool's own arg parser, not a
generic numeric check).

All 5 maps regenerated (2,236 tiles total). Confirmed on two consecutive
clean restarts: `docker logs --since 30s` shows zero "generator v"
warnings (checking only the most recent boot matters here -- `docker
logs` without `--since` shows the FULL accumulated history since
container creation, which kept showing stale counts from before the fix
and briefly looked like nothing had changed).

## mod-individual-progression's 22 optional SQL files, enabled

Asked about because they looked missing at a glance -- they weren't:
`mod-individual-progression/optional/sql/world/` has all 22 `zz_optional_*`
files, matching upstream exactly (checkout confirmed at zero commits behind
`origin/master`, and byte-identical file listing to the old, decommissioned
`C:\azerothcore-wotlk` checkout -- nothing lost in the migration). What was
actually true: they sit outside `data/sql/world/base/`, the directory this
project's whole SQL pipeline (`ac-db-import`, `tools/server/
apply_module_sql.sh`) actually scans, so they were never applied to the
database despite being present on disk -- opt-in by design, but easy to
mistake for "missing" from a directory listing alone.

All 22 enabled at the user's request: copied (not moved -- the `optional/`
originals stay in place, matching upstream's own layout and docs) into
`data/sql/world/base/` alongside the module's existing base SQL, so they're
tracked and reproducible through the exact same pipeline as everything
else here, not a one-off manual `mysql <` run that Alpine migration would
lose. Applied cleanly, no schema drift this time (unlike the earlier
`mod-dungeonmaster`/`mod-xp-changer` SQL, which needed fixing first) --
confirmed one representative change directly (`item_template` ammo rows:
59 now at the restored 200 stack size). Full list of what's now live:
ammo/item stack sizes, AQ quest turn-in reduction, AV landmines, harder
low-level creature stats (Vmangos values), spell-training level gates
tied to expansion, Vanilla/TBC content phasing, heirlooms removed
entirely, era crafting cooldowns/specialization requirements restored,
potion CD back to 2 min, Rogue poisons restored as a craftable skill,
small-group tuning (pairs with `mod-autobalance`, already installed),
buff scrolls stackable again, TBC heroic key rep nerfed to Honored, TBC
PvP prices, previously-unobtainable cosmetic items added back in,
pre-model-update creature models, era regen values, pre-WotLK ship
routes, and the 3.0.2 TBC-raid HP nerf.

**Four of these need a client-side DBC patch to be fully meaningful**
(`spell_damage_and_healing`, `tbc_pvp_prices`, `vanilla_transports`,
`restore_rogue_poisons` -- the module's own `optional/patch-explanations.txt`
covers exactly which DBCs: `SkillLine`/`SkillLineAbility`/
`SkillRaceClassInfo`/`SpellItemEnchantment`/`Spell.dbc`). The module ships
its own `patch-V.mpq`/`patch-S.mpq` for this, but those filenames collide
with patches already on the test client from another source (same
`patch-V`/`patch-S` naming noted earlier re: `patch-J`/`patch-U`/`patch-Z`)
-- deliberately not touched yet. **Explicitly deferred, not forgotten:**
the plan is to fold the needed DBC changes into this repo's own
`install_client.py`/MPQ pipeline instead of relying on the module's
separate patch files, so a client patched through our own tooling gets
these automatically -- scoped as its own follow-on piece of work, not
done in this pass.

## That follow-on piece: done

`install_client.py --progression-module-root <path> [--progression-variant V|S]`.
Extracts straight from mod-individual-progression's own `optional/*.7z`
archives (`dbc.7z` for the 4 server-only DBCs, `patch-V.7z`/`patch-S.7z`
for the chosen `Spell.dbc` mana-cost variant -- default `V`, era-authentic
lower costs, matching this whole project's theme) into
`client-patch/progression-optional/` (gitignored, same `*.dbc` rule as
everything else derived from Blizzard data). No separate copy of this data
maintained in this repo -- the module's own archives stay the source of
truth, re-extracted each time the flag is passed.

Confirmed before wiring anything in, not assumed: `patch-V`'s `Spell.dbc`
removes zero spell ids relative to stock, and all 1,295 spell ids our own
era talents reference are present in it -- deploying it can't silently
break any talent we've already built.

Two different destinations, matching the two pieces:
- The 4 server-only DBCs (`SkillLine`/`SkillLineAbility`/
  `SkillRaceClassInfo`/`SpellItemEnchantment`) + `Spell.dbc` all get a
  straight `docker-compose.override.yml` bind mount into
  `env/dist/data/dbc/`, same pattern as `Talent.dbc`/`TalentTab.dbc`
  already used. (That file is gitignored by the AzerothCore checkout
  itself -- standard docker-compose convention for local overrides, not
  something we're choosing to skip committing.)
- `Spell.dbc` ALSO goes into our own client MPQ (`package_mpq()`, now 3
  files instead of 2) -- deliberately NOT the module's own
  `patch-V.mpq`/`patch-S.mpq`, which collide with unrelated same-named
  files already on the test client (confirmed by hash: different size,
  different content, different origin -- not this module's file at all).
  The other 4 DBCs don't need a client copy; the client never validates
  spell/skill data against its own copies of those the way it does
  talents.

Live-tested end to end: extraction ran cleanly (needs `7z` on PATH, same
tool the module's own docs already assume you have to open its `.7z`
files by hand), packaged MPQ reads back all 3 files correctly, worldserver
recreated (new mount paths, not just changed content -- needed `up -d`,
not a plain `restart`, same distinction learned earlier this project) and
booted clean with the new DBCs actually loaded -- confirmed the in-
container `Spell.dbc` is exactly the staged 53,466,210-byte patched file,
not silently falling back to stock.

## mod-individual-progression is now our own fork too

Same reasoning as `mod-solo-lfg` earlier: forked to
[`m0nnnna/mod-individual-progression`](https://github.com/m0nnnna/mod-individual-progression)
so the `optional/` DBC archives (`dbc.7z`, `patch-V.7z`, `patch-S.7z`) this
project's client-patch pipeline now depends on are a static reference we
control, not something that can move or disappear if upstream
(`ZhengPeiRu21/mod-individual-progression`, still tracked as `upstream` on
the local checkout for pulling future fixes) changes something. `origin`
on `C:\nekocore\server\modules\mod-individual-progression` now points at our
fork -- `install_client.py --progression-module-root` reads from that
local checkout path either way, so this needed no tooling change, just the
remote repointed.

Folded in while forking, since they were sitting right there uncommitted:
- **All 22 `zz_optional_*.sql` files, actually tracked now.** They'd been
  living under `optional/sql/world/` (never scanned by `ac-db-import`) --
  moved into `data/sql/world/base/` earlier this project to get them
  applied to THIS database, but that directory has its own
  `zz_optional*` `.gitignore` rule (upstream's own -- exists specifically
  to keep them out of the auto-applied path). Removed that rule in our
  fork; we want the opposite of what it was for.
- **The `AREA_SILVERMOON_CITY` fix**, already live this whole project but
  never actually committed anywhere until now: that constant is
  referenced in `checkIPPhasing()`/`isEnabledPreTBCArea()` but was never
  defined anywhere in the module or in core's `AreaDefines.h` -- replaced
  with the literal area id (3487), confirmed against the real 3.3.5a
  client's `AreaTable.dbc`.

Not a fresh checkout for the fork -- same local tree, same uncommitted
work already running live, just committed and pushed instead of staying
as local-only changes nothing else could see. Confirmed on GitHub after
pushing: `master`'s HEAD is our commit, and all three `.7z` archives came
through intact.

**Whichever box this project ends up running on** (the Alpine move this
session has been building toward) should clone `mod-individual-
progression` from `m0nnnna`'s fork, not `ZhengPeiRu21`'s -- gets the
optional SQL files, the area-id fix, and the archives this repo's own
tooling depends on, all in one clone, no manual re-application of any of
this needed.

## The right-click camera snap bug -- fixed, a genuinely different kind of patch

`tools/install_patch/patch_camera_bug.py`. A real, well-known 3.3.5a
client bug: right-click camera rotation can snap the camera to looking
straight up or down, no user input involved, just wrong. This is the
first client patch in this repo that isn't DBC/Lua/addon/MPQ -- it's a
bug in `Wow.exe` itself, so the only fix is 4 small same-length binary
patches to the executable's own code, at fixed file offsets. Source: a
community-documented patch on Warmane's forums (a long-running, well-
established 3.3.5a server) -- the same category of fix as
[brndd/vanilla-tweaks](https://github.com/brndd/vanilla-tweaks)'
equivalent for the 1.12.1 client (confirmed that project exists and does
the same kind of thing there, though naturally different byte offsets --
different client build entirely).

Treated this with more caution than anything else built this project,
since a wrong byte in an executable patch doesn't just misbehave, it can
corrupt or crash the client outright:
- Pulled the hex directly from the forum's raw HTML rather than trusting
  an AI-summarized paraphrase of it -- verified the same bytes came back
  two independent ways before trusting them at all.
- **Verified every one of the 4 offsets against this project's own actual
  `Wow.exe` BEFORE writing anything** -- confirmed all 4 matched the
  patch's expected "before" bytes exactly, which is real evidence this
  patch targets the same client build we're running, not just a hope.
- The tool itself repeats that same check every time it runs and refuses
  to touch the file at all -- not a partial patch -- if any offset
  doesn't match either the expected original or already-applied bytes,
  since that would mean a different exe build and applying it blind could
  corrupt arbitrary code.
- Always writes a `.bak` copy of the untouched exe before changing
  anything, never overwritten by a later run.
- Hand-transcribing hex by hand turned out to be exactly as error-prone
  as expected -- caught two separate length-mismatch typos via the
  module's own startup assertion before anything was ever written, fixed
  by generating the corrected bytes programmatically (`'CC' * 25` style)
  instead of re-typing a hand-counted literal a third time.
- This specific patch (raw external machine code, and the tool that
  writes it into an executable) tripped Claude Code's own safety
  classifier on every touch -- editing the file, even just importing it
  to check lengths. Approved per-action by the user rather than routed
  around; once a fix needed re-verifying, the user ran the verification/
  apply commands themselves rather than continuing to approve individual
  tool calls.

Applied to the live test client: backup hash confirmed to exactly match
the pre-patch original, patched file confirmed same size (all patches are
same-length, no file-size change expected or found), dry-run afterward
correctly reports all 4 offsets as "already patched." Actual in-game
camera behavior needs a live client session to confirm, which is on the
user to verify next.

Usage:
```
python tools/install_patch/patch_camera_bug.py --wotlk-root "D:\...\3.3.5a" --dry-run   # check only
python tools/install_patch/patch_camera_bug.py --wotlk-root "D:\...\3.3.5a"             # apply
```

## Eluna scripting -- mod-ale, and a genuinely confusing debugging session

Asked to "add the eluna scripting system." First fork in the road: real
upstream Eluna (the ecosystem most people mean by that name) isn't a
`modules/`-droppable thing at all for AzerothCore -- confirmed
[`ElunaLuaEngine/ElunaAzerothcore`](https://github.com/ElunaLuaEngine/ElunaAzerothcore)
is a full standalone fork of the entire core (its own `acore.json` literally
names itself `"azerothcore-wotlk"`, Eluna's hooks woven through
`src/server/game/` directly), not a module -- merging that into our
already-customized checkout would be a real, large C++ merge job, not a
clone-and-compile. Went with
[`azerothcore/mod-ale`](https://github.com/azerothcore/mod-ale) instead:
this core already has first-class, zero-config support for it
(`modules/CMakeLists.txt`'s `ConfigureALEModule`, triggered automatically
by any module directory literally named `mod-ale`) -- a normal module-
sized task. Its own README is upfront that it's diverged from standard
Eluna's API and isn't script-compatible with it; noted, accepted, matches
what the user chose once that tradeoff was clear.

**It compiled and linked clean, but stayed completely, suspiciously
silent** -- zero `[ALE]` output anywhere, in `docker logs` or any log
file, despite `ALE.Enabled = true` and correct config. Chased this
methodically rather than guessing:
- Ruled out a startup-ordering theory (config loads before scripts
  register) that looked compelling from log-line text alone -- reading
  the actual call sites (`Main.cpp`, `World.cpp`, `ScriptMgr.cpp`) showed
  it was backwards: `ScriptMgr::Initialize()` (which constructs every
  module's scripts) runs before `World::LoadConfigSettings()` (which
  dispatches `OnBeforeConfigLoad` to them), not after.
- Added temporary `LOG_ERROR` diagnostics (always-visible regardless of
  any level filtering) at each step of `ALE_WorldScript`'s constructor and
  `OnBeforeConfigLoad` -- confirmed the constructor runs, the hook fires
  with `reload=false` exactly once as expected, `ALEConfig::Initialize()`
  and `ALE::Initialize()` both run to completion without throwing. The
  module was working correctly the entire time.
- The actual gap: `mod_ale.conf` ships its own `Logger.ALE=4,ALELog
  ALEConsole` plus the two appender definitions it references -- but
  `sLog` bootstraps its Logger/Appender tables from config BEFORE module
  `.conf` files get merged into `sConfigMgr`, so those definitions never
  reach the actual logging system. Not a functional bug in the module at
  all, a config-loading-order gap between core and every module that ships
  its own custom logger category this way.
- Fix: the identical three lines (`Appender.ALEConsole`, `Appender.ALELog`,
  `Logger.ALE`), added directly to core's own `worldserver.conf` (which
  IS read early enough -- same file `Logger.root`/`Logger.server` already
  work from). Confirmed immediately: `[ALE]: Searching scripts from
  ...` and `[ALE]: Executed N Lua scripts in ...` both appeared, in both
  the console and `ALE.log`, right after. **`worldserver.conf` is
  gitignored by the AzerothCore checkout itself** (`env/dist/*`, same as
  every other live-config file this project has touched) -- these three
  lines need to be re-added by hand on any fresh deploy, they don't ship
  with anything reproducible yet.
- One more real gap found in the same pass: mod-ale's own relative default
  (`ALE.ScriptPath = "lua_scripts"`) resolves against the worldserver
  process's actual working directory, confirmed via `/proc/1/cwd` to be
  `/azerothcore` -- the container's own ephemeral filesystem, not anything
  host-persistent. Fixed by pointing `ALE.ScriptPath` at an absolute path
  (`/azerothcore/env/dist/lua_scripts`) and adding a matching
  `docker-compose.override.yml` bind mount to
  `C:\nekocore\server\env\dist\lua_scripts` -- scripts now survive a rebuild
  instead of vanishing with the old container.

All temporary diagnostics removed before finishing -- `git diff --stat`
against `modules/mod-ale`'s own upstream confirms zero local
modifications, this needed no code changes at all, purely a config gap.

**Confirmed working end to end**, not just "compiles": a throwaway test
script (`env/dist/lua_scripts/test_nekocore_ale.lua`, a
`RegisterPlayerEvent(3, ...)` login broadcast) produced `[ALE]: Executed 1
Lua scripts in 3 ms (1 compiled, 0 cached, 0 pre-compiled)` on boot --
genuine proof the engine parses, compiles, and registers scripts from the
now-correct persistent path, not just that the binary links. **User
confirmed the broadcast actually fired on real login** -- full stack
verified end to end, not just the boot log. Throwaway test script removed
after confirmation.

**What still needs doing for a real deploy, not done in this pass:** the
three `worldserver.conf` logger lines and the `ALE.ScriptPath` config
change both live in files this project's own `.gitignore` (correctly)
keeps out of git, same as every other environment-specific setting
touched this session -- there's no tooling yet that reapplies them
automatically on a fresh box the way `sync_module.py`/
`apply_module_sql.sh` do for nekocore's own module content. Worth a small
setup script if/when the Alpine move actually happens, not built
speculatively here.

## World elites and world bosses were never actually scaled at all

Raised by the user: mod-autobalance "works perfectly if you are in an
instance but out in the world this can cause a problem for solo and small
groups." Confirmed directly, not assumed, by reading mod-autobalance's own
source (`modules/mod-autobalance/src/ABUtils.cpp`): `ShouldMapBeEnabled()`
returns false for any map where `!map->IsDungeon()`, and independently,
`ABUnitScript::_Modify_Damage_Healing` (the hook that actually scales
damage/healing numbers) bails unless BOTH source and target are on a
dungeon map. So a world elite or world boss on an open continent has
always been at its raw, unscaled `creature_template` stats -- not a config
gap, baked into the module's own logic. Setting a multiplier on
`AutoBalanceCreatureInfo` (the way `AutoBalanceManaBurnFix.cpp` already
does for mana burn) would NOT have made AutoBalance's own hook fire for
these creatures -- its dungeon check returns before it would ever read the
multiplier. So this needed a real standalone scaler, not a thin wrapper
around AutoBalance.

`src/WorldEliteScaling.cpp`. Scoped to the two levers that actually matter
for "can a solo player or small group fight this thing": the creature's
max health (time-to-kill) and the damage/healing it deals to players
(survivability). Armor and CC-duration scaling are left on the table for a
follow-on if needed, not built here.

- **Which creatures:** rank ELITE, RAREELITE, or WORLDBOSS
  (`SharedDefines.h`'s `CreatureEliteType`) on a `MAP_COMMON` map
  (`MapEntry::IsWorldMap()`, confirmed against `DBCStructure.h` directly --
  the real open continents, not instances, battlegrounds, or arenas).
  Plain `CREATURE_ELITE_RARE` (rare but not elite) is deliberately
  excluded -- those are already normal-difficulty and meant to be
  soloable, matching how the user described the problem.
- **When:** `UnitScript::OnUnitEnterCombat`, which for a `Creature` only
  fires from `Creature::AtEngage` -- the actual out-of-combat -> combat
  transition (confirmed at its one call site in `Creature.cpp`), not
  re-fired on every subsequent hit of the same fight. So "capture the
  group as the fight starts," which is what the user asked for, falls out
  of this hook for free -- no dedup/cooldown tracking needed.
- **Who counts:** a spatial snapshot (everyone within
  `Nekocore.WorldEliteScaling.Radius` of the creature at the moment it
  engages), not a threat-table read -- per the user's own callout, a
  healer or caster standing at their normal range who hasn't landed a hit
  yet still needs to count. That's also why the default radius (100
  yards) is generous rather than melee-sized.
- **The math:** players-present / per-rank baseline (configurable per
  rank -- default 3 for Elite, 5 for RareElite, 15 for WorldBoss), clamped
  to `[MinMultiplier, MaxMultiplier]` (default 0.4-1.5) so a mispull with
  zero nearby players doesn't scale to near-nothing and a crowd doesn't
  scale it past a sane ceiling. Applied to max health (preserving current
  health %, in case of a mid-fight re-engage) and, via the same
  `AutoBalanceCreatureInfo.ScaledDamageMultiplier` field AutoBalance's own
  struct uses, to melee/spell/periodic damage the creature deals to
  players -- mirrors `AutoBalanceManaBurnFix.cpp`'s existing mana-burn
  scaling, which has no dungeon gate and so already benefits from this
  automatically. Health baseline is captured once (`initialMaxHealth`, the
  same field AutoBalance's struct already has) so re-engaging the same
  creature later always scales from its true unmodified template health,
  never a previously-scaled value.
- **Config:** `Nekocore.WorldEliteScaling.*` in `conf/nekocore.conf.dist`,
  live-reloadable the same way `Nekocore.LockedMaps` is.

Confirmed live, not just "compiles": `sync_module.py` run,
`docker compose build ac-worldserver` succeeded with zero warnings for the
new file, and (since only `.conf.dist` existed for this module's actual
runtime config -- same "silently running on baked-in defaults" gotcha hit
earlier this project) `env/dist/etc/modules/nekocore.conf` needed the new
keys copied in by hand before a restart showed zero
`Nekocore.WorldEliteScaling.*` "Missing property" warnings. `WORLD: World
Initialized In 0 Minutes 20 Seconds` afterward, stable. Actually engaging a
world elite in-game to confirm the scaling fires as expected is on the
user to verify next.

## "The right XP rate per era" -- turned out to mostly already exist, minus one real gap

Asked what this realm's XP rate actually was, given the goal of leveling
genuinely feeling like each era. Traced the full pipeline before touching
anything:

- Core `Rate.XP.Kill/Quest/Explore/Pet` are all stock `1` in
  `worldserver.conf` -- no global era-based rate multiplier exists at that
  layer.
- `mod-individual-progression`'s `QuestXPFix` (already enabled) reverses a
  real, documented Blizzard change: quest XP for Vanilla/TBC quests was
  boosted as a catch-up mechanic in patches 2.3.0 and 3.0.2. Its
  `custom_quest_xp` table (5,666 rows, one per quest) holds the actual
  pre-boost XP value per quest, applied at runtime via a per-quest ratio
  against whatever the engine would otherwise give -- this is real,
  already-verified "era math," just not a single scalar.
- The base creature-KILL XP formula (grinding on mobs, not quests) was
  never given an equivalent historical catch-up boost -- only quest reward
  VALUES were. So there's no parallel "authentic kill-XP multiplier"
  hiding anywhere to restore; confirmed by reading the actual
  `IndividualProgressionPlayer.cpp` hooks, not assumed.
- `npc_xp_changer` (`mod-xp-changer`) sits on top of all of that as a
  purely personal, per-player 0.2x-2.0x preference slider with zero era
  awareness -- "1.0x Normal" always meant the same flat rate no matter
  what content the player was actually in.

Given the user explicitly did NOT want an invented "Vanilla is 0.6x, TBC
is 0.8x" number fabricated with no source (this project's own standard --
same reasoning as verifying all 76 mana-burn spell ids against Spell.dbc
rather than trusting the list on faith), the gap that's real and worth
closing is narrower than "build a whole new rate system": `npc_xp_changer`
itself needed to become era-aware.

`modules/mod-xp-changer/src/XPChanger.cpp` edited in place (a hand-written,
no-public-repo module recovered from the old checkout -- nothing to fork,
same category as `mod-live-reload`). "1.0x Normal" now means "your current
era's own baseline" instead of a flat rate, and the personal slider
multiplies on top of that baseline instead of on top of a bare 1.0. Era is
read via the exact same `hasPassedProgression`/`isBeforeProgression`
against `PROGRESSION_PRE_TBC`/`PROGRESSION_TBC_TIER_5` that
`EraTalentGate.cpp`/`EraProgressionSync.cpp` already use, so a character's
"era" here always agrees with what those already decided for talents. The
gossip hello message now shows the detected era, its baseline, the
player's personal choice, and the combined effective rate, so the NPC
itself surfaces what's actually happening instead of a flat unexplained
number.

The three baseline numbers themselves
(`Nekocore.EraXPRate.Vanilla/TBC/WotLK` in `conf/nekocore.conf.dist`, read
cross-module by the mod-xp-changer file the same way
`AutoBalanceManaBurnFix.cpp` already reads `ABCreatureInfo.h` from a
different module) are deliberately NOT pre-tuned to any researched
constant -- they default to `1.0` each (a no-op, identical to today's
behavior) and are meant as a live tuning dial (`.reload config`, no
restart) for whoever runs this realm to set based on how leveling actually
feels to play, not something invented here without evidence.

Confirmed live: synced, `docker compose build ac-worldserver` succeeded
(a compile failure anywhere would have failed the whole image), restarted,
zero `Nekocore.EraXPRate.*`/`Nekocore.WorldEliteScaling.*` "Missing
property" warnings, `WORLD: World Initialized In 0 Minutes 20 Seconds`,
stable. Actually visiting `npc_xp_changer` in-game to confirm the era
label and combined rate display correctly is on the user to verify next.

## Six catalogue mods added, with a DBC merge step so they can coexist

Credits and licenses for every third-party project this realm runs are in
`THIRD-PARTY.md` -- the features below are theirs, only the integration is
ours.

At the user's request, added Breaking-News-Rewrite, mod-uac (any race /
any class), mod-global-chat, Prestige-and-Draft-Mode, Araxia's Delves and
Acore_ExchangeNpc. mod-worgoblin was on the list too and was **skipped**
(user's call after being shown the trade-off): unmaintained, needs a
signature-patched `Wow.exe` on every client, and its 30 whole-file DBC
replacements would have wiped out both the era-talent DBCs and
mod-individual-progression's optional set. Full details, install order and
caveats: `docs/third-party-mods.md`.

The non-obvious part was that five of the six ship server DBCs and several
edit the *same* file (CharBaseInfo: mod-uac + Prestige; SkillRaceClassInfo:
mod-uac + Prestige + progression) as whole-file "stock plus my rows"
copies. Installing them as documented means the last copy wins. So:
`tools/dbc/layer_merge.py` (schema-less, row-level merge -- string/float
columns inferred from the stock file and cross-checked against
AzerothCore's DBCfmt.h; also parses the WDBX CSV row lists Delves ships)
and `tools/build_patch/build_mod_dbcs.py` (the recipe: 13 merged files
into `data/generated/dbc/`, bind-mounted server-side and packed into the
client's `patch-Z.mpq`). Doing it row-by-row also caught two things a
file copy would have shipped silently: Prestige rewrites every stock
SkillRaceClassInfo mask to -1 (only its added rows are taken), and its
CharTitles.dbc renames "Wrathful Gladiator" to an obscenity (not taken).

Everything third-party is reproducible rather than hand-copied:
`tools/third_party/fetch.py` (pinned commits into gitignored `third-party/`
and `server/modules/`, then `third-party-patches/<mod>/*.patch`),
`tools/server/stage_third_party.py` (Lua, SQL, maps, module confs), and
`sync_module.py` now stages the Lua-only mods' SQL inside our own module
tree because AzerothCore's updater only scans compiled modules.

What broke on the way, all fixed and captured as patches or staging
rewrites so a rebuild doesn't hit them again:
- Breaking-News-Rewrite doesn't compile against current AzerothCore
  (`PQuery` gone, `CanPacketSend` takes `WorldPacket const&`, `Field::
  GetString()` gone, `sWorld->GetPlayerCount()` moved to
  `sWorldSessionMgr`, runtime `fmt::format` needs `fmt::runtime`). Its
  README also claims the Top Guild section hides itself when
  mod-guild-points is absent; it doesn't -- the unknown column aborts the
  worldserver at startup. Default flipped to off in the patch.
- Every `creature` INSERT in Delves and Prestige uses the pre-2025
  `id1/id2/id3` columns, and two `creature_template` INSERTs still carry
  `modelid1-4`/`scale`/`trainer_*`/immune masks. `stage_third_party.py`
  rewrites those statements (and emits `creature_template_model` rows from
  `modelid1`) rather than patching 16 files by hand.
- Prestige's `dofile("lua_scripts/...config.lua")` is relative to the
  worldserver's cwd (`/azerothcore` in the container) and can never
  resolve; the config is loaded first by ALE's sorted load order instead.
  Its characters SQL also had a stray `;` mid-`ALTER TABLE`.
- Delves' mmaps are generator v19; the core wants v20 (same tile format --
  header rewritten on copy, see the doc for the reasoning).

Also found while bringing it up: `server/.env`'s new DB root password had
not been applied inside MySQL, so the healthcheck failed and nothing
depending on `ac-database` would start (and, one step later, the aborted
worldserver left the realm flagged VERSION_MISMATCH, which the authserver
now ORs with OFFLINE into the excluded `flag = 3`, crash-looping it).
`ALTER USER` done; `docs/deploy.md` step 8 already describes this.

Confirmed live: worldserver builds with all 14 modules, db-import applies
the 16 mod-uac + 31 third-party SQL files cleanly (`Applied 22 queries`),
`[ALE]: Executed 35 Lua scripts` with zero errors, `World Initialized In
0 Minutes 12 Seconds`, realm registered, 688 delve creatures / 100
race-class pairs / 5174 draft spells in the DB, merged `Map.dbc` visible in
the container, `patch-Z.mpq` (366 MB, 334 files) + the four addons
deployed to the test client and zipped to
`website/downloads/nekocore-patch.zip`. Not yet verified in-game: character
creation with a new combo, a delve teleport, Chromie, the exchange NPC, the
character-select news panel.

## Challenge runs: old dungeons brought back to your level, harder every clear

The gap: on a mod-individual-progression realm a character sits at their
era's cap for a long time, and every dungeon under that cap is dead
content. mod-autobalance can already scale a dungeon up to the party's
level -- but `AutoBalance.LevelScaling` is one switch for the whole realm,
and on this realm it was deliberately `0`, because a character levelling
through Wailing Caverns at 20 has to find it at its real level. What was
wanted was the opt-in version: tell an NPC "challenge run", go do Wailing
Caverns at 60, and have it get harder every time you clear it.

New in this repo: `src/ChallengeRun.cpp` (state, the Keeper NPC, clear/wipe
detection), `src/ChallengeScaling.cpp` (the part that makes an instance
harder), `data/sql/db-characters/base/nekocore_challenge.sql` (three
tables), `data/sql/db-world/base/challenge_keeper.sql` (the NPC),
`website/www/challenges.php` + `inc/challenges.php`, and a
`Nekocore.Challenge.*` block in `conf/nekocore.conf.dist`.

**How it plays.** The **Challenge Keeper** (entry 9000101) stands beside
Dungeon Dan in Stormwind and Orgrimmar, and also in front of every dungeon
and raid entrance (`tools/build_patch/build_keeper_spawns.py` generates
`challenge_keeper_spawns.sql` from the entrance triggers). Dan himself is in
every capital. The Keeper lists the dungeons your
character may challenge, each with the tier it is at *for you* and what
that works out to. Picking one arms it; walking into the instance starts
it. Killing the dungeon's final boss is +1 tier for everyone in the run;
everyone being dead at once is -1 (`Nekocore.Challenge.WipePenalty`);
leaving without either costs nothing. Tier N is `+15% health` and `+10%
damage` per step by default -- health climbing faster than damage on
purpose, so a tier is a longer fight before it is a lethal one. There is no
ceiling unless you set one; the wall is wherever a group actually stops.

Arming deliberately does **not** teleport. Dungeon Dan is in every capital
and already has every dungeon entrance; a second copy of his coordinate
table would be a second thing to keep right.

**The bracket comes from the era, and it is the access gate.** 60 Vanilla /
70 TBC / 80 WotLK, read the same way `EraTalentGate.cpp` and `NekoLog.cpp`
read it (`GetPlayerProgressionFromQuests`, whose value is what
mod-individual-progression's own `isBeforeProgression` /
`hasPassedProgression` compare against). You have to be at that cap to arm
or to enter one, and entering a flagged instance under-level bounces you to
your hearth. That rule is free to enforce because the progression module
already stops XP at each era's cap (`IndividualProgressionPlayer.cpp`'s
`OnPlayerGiveXP`), so "at the cap" and "in that era" are the same
characters.

**Which dungeons: no hardcoded map list.** Built at startup from the
client's own `LFGDungeon.dbc` (normal difficulty, type dungeon), kept only
where `MapEntry::IsNonRaidDungeon()` and where `instance_encounters` has at
least one row for the map. That second filter does double duty: it is how a
clear gets detected, and it is a free way to drop the unused and
development maps that sit in `Map.dbc` and `LFGDungeon.dbc` with nothing
behind them. A map with several LFG rows (Blackrock Spire's two) is listed
once. A dungeon's expansion has to be at or below your era, so a Vanilla
character is never even offered a TBC dungeon.

**Detecting a clear, data-driven.** Primary signal is
`instance_encounters.lastEncounterDungeon` -- AzerothCore's own record of
which encounter finishes a dungeon, the one that hands out LFG completion.
Where a map has no row with it set, the fallback is "every encounter the
instance script knows about is DONE", and that needs a second hook:
`OnUnitDeath` runs *before* the instance script sets the last boss to DONE
(`Unit::Kill` order), so `GlobalScript::OnBeforeSetBossState` is where that
state change is actually visible. Startup logs how many dungeons are in
that second group, so it is a number you can look at rather than a guess.

### How it scales an instance without forking mod-autobalance

Three levers, three different mechanisms, because AutoBalance exposes them
in three different places -- all of this read out of its source, not
assumed:

- **Level.** Every level-scaling branch in AutoBalance sits behind the one
  global `LevelScaling` (`ABAllCreatureScript.cpp`'s
  `ModifyCreatureAttributes`, `ABUtils.cpp`'s `UpdateMapDataIfNeeded`), so
  there is no way to scale one instance while it is off. What *is* per-map
  is the skip range: both gates decide "don't scale" from
  `mapABInfo->levelScalingSkipHigherLevels` / `...SkipLowerLevels`, runtime
  fields on the map's own `AutoBalanceMapInfo`, where **0 means never
  skip**. So `AutoBalance.LevelScaling` goes to 1 to arm the machinery, and
  this module zeroes those fields on challenge instances only -- from
  `ABModuleScript::OnBeforeModifyAttributes`, which AutoBalance calls per
  creature four lines above the gate. Nothing can get between them, so no
  config reload or map update can undo it mid-run.
- **Health.** `ABModuleScript::OnBeforeUpdateStats`, whose `scaledHealth`
  is the value AutoBalance is about to hand `SetMaxHealth`. Multiplying it
  *there* means the tier bonus composes with AutoBalance's own party-size
  and level scaling rather than replacing it, and it survives every
  recalculation because it happens inside the recalculation.
- **Damage.** Not that same hook: the `damageMultiplier` reference it hands
  you is a dead end. By the time it is passed, AutoBalance has already
  stored `creatureABInfo->DamageMultiplier` and computed the
  `scaledDamageMultiplier` it will actually use, and it never reads the
  parameter again. So damage rides the three `Modify*Damage*` UnitScript
  hooks, the same way `WorldEliteScaling.cpp` does it.

The other direction matters just as much: with
`Nekocore.Challenge.SuppressLevelScalingOutsideChallenges` on (default),
that same hook pushes the skip ranges *wide* on every non-challenge
dungeon, so "normal dungeons are never level scaled" is a property of this
module and not of a conf file. Two specific reasons that had to be true
here -- `AutoBalance.conf` lives in the gitignored server checkout, so a
rebuilt box comes back with upstream defaults; and one of those defaults is
`LevelScaling.DynamicLevel.PerInstance = "229 -1 -1 1, 230 0 0"`, whose
`0 0` is a per-instance skip override that would have forced level scaling
on in Blackrock Depths for everyone the moment the global was armed.
`AutoBalance.LevelScaling = 1` itself is now owned by
`tools/server/stage_third_party.py settings` (idempotent, rewrites the live
conf) so it survives a rebuild, and `ChallengeScaling.cpp` logs a startup
ERROR if it ever comes back 0 rather than silently giving you "harder
health, same level 18 mobs".

Not scaled, on purpose: armor, CC duration, creature healing, and the
"world" damage multiplier AutoBalance computes for damage whose source is
not an enemy creature (traps, environment) -- that last one is worked out
in `UpdateMapDataIfNeeded` before this module has any say, so a challenge
instance's traps hit for their unscaled amount.

### Recorded like a log, listed separately from one

Challenge runs go through NekoLog's existing tables, which is what lets
`log.php` render a challenge's full combat detail with no duplicated code
-- and they are joined to it by `nekocore_challenge_run.log_run_id`. That
link is deliberately in *that* direction: a column on `nekolog_run` would
have needed an `ALTER` on a table that already exists live, and MySQL 8 has
no `ADD COLUMN IF NOT EXISTS`, so the module's own idempotent base SQL
could not express it. `NekoLog.h` exposes one function
(`NekoLog::RunIdFor`); nothing in `NekoLog.cpp` knows challenge runs exist.

Everything user-facing is separate, though: a new **Challenges** page with
a ladder (highest tier actually *cleared*, which a wipe can never take
away) and the run list, and every ordinary log/ranking query now excludes
challenge runs via `nl_not_challenge()` -- a challenge kill in a boss's DPS
ranking would be comparing two different games. A challenge's log page says
so at the top, with the tier, the bonus it was fought at, and each
participant's tier before and after.

### One real bug found next door while doing this

`WorldEliteScaling.cpp`'s `ScaleOutgoingAmount` had no map check, and it
reads its multiplier out of `AutoBalanceCreatureInfo` -- mod-autobalance's
*own* struct on the creature (same `CustomData` key on purpose). So inside
a dungeon it was reading a multiplier AutoBalance had set for itself and
already applied in its own `ABUnitScript`, and applying it a second time:
every creature-to-player hit in every instance was being scaled by
AutoBalance's factor **squared**. Fixed by the `IsWorldMap()` check that
the enter-combat side of the same class always had.

## Player bug reports, 2026-10-04 (Vanilla paladin, soft launch)

A batch from the first soft-launch players, nearly all one Vanilla paladin.
Most traced back to the era spell copies keeping some WotLK detail the core
keys on:

- **Holy Light / Flash of Light healed nothing.** Their 1.12 rows heal
  through SCRIPT_EFFECT, which the 1.12 core turned into the heal by hand.
  `build_clone` now takes WotLK's plain HEAL in that slot.
- **Seal of Righteousness.** Rank 1 ran WotLK's 3.0 script and ranks 2-8 had
  none, so nothing hit. `spell_era_pal_seal_of_righteousness` is the 1.12
  formula (vmangos). The two Vanilla "Rank 1" spells also split the rank
  chain in two; `resolve_rank_claim` orders them by the era's own
  SkillLineAbility link.
- **Seal of the Crusader** was ported with its 1.12 family bits, which are
  not a WotLK seal's, so the core never treated it as a seal: no
  replacing other seals, no Judgement aura state. Ported seals now get a
  WotLK seal bit (`as_wotlk_seal`), and the era's damage cut that offsets
  its attack speed is back (`EraSpellFixups.cpp`).
- **Judgement of the Crusader** r1 (21183) is a different spell in WotLK,
  and seals name their judgement only as a number, so it was never copied.
  `era_side_spells` now copies every judgement a seal names. Vanilla
  Judgement of Command (a dummy naming its damage) is cast by hand.
- **Tooltips** now use the era's own name and text (Blessing, not Hand, of
  Protection; no Avenging Wrath), with `$12345s1` tokens pointed at the era
  copies (`remap_era_text_refs`).
- **Forbearance**: Vanilla bubbles apply the era's 1-minute copy
  (`spell_era_pal_immunities`); Vanilla Lay on Hands runs no WotLK script.
  Bandages lose WotLK's pacify prevention, so bubble-bandaging works again.
- **Duplicate auras on the stance bar**: the core finds paladin auras by the
  WotLK raid-aura effect; Vanilla's are party auras, so ranks never
  replaced each other. Fixed for era copies at startup.
- **Weapon proficiency**: an era copy of One-Handed Swords taught no skill,
  because era SkillLineAbility rows must be AcquireMethod 0. The skill is
  now learned from the WotLK row on learn and at login.
- **Spell coefficients**: Vanilla copies get 1.12-rule coefficients and no
  attack power scaling instead of WotLK's `spell_bonus_data`
  (`vanilla_coefficients`), plus core patch 0004 for 1.12's level penalty.
- **Hogger, and every solo world elite: no loot.** World elite scaling cut
  max health without lowering the core's "players must deal half its
  health" requirement. `WorldEliteScaling.cpp` now resets it.
- **Class quests repeated at other races' givers**: mod-uac opens every
  race's paladin chain to the faction. `zzz_nekocore_class_quest_exclusivity.sql`
  makes the Human, Dwarf and Draenei chains exclusive.

Not changed: Light Leather and Copper Ore stacking to 10 is
mod-individual-progression's 1.12 stack size (`zz_optional_item_stack_sizes.sql`),
and the Blood Elf creation error is the documented TBC race lock.

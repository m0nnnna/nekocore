# nekocore

Client and server work for the NekoCore realm, running on
[AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) (a 3.3.5a,
build 12340 server) plus
[mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression).

**This repo holds only what we add.** It is not a fork of AzerothCore and does
not vendor the engine or the progression module -- both are read from the
live checkout at `D:\AzerothCore` (their own separate repos; see that tree's
`modules/` for the progression module). This repo is linked into
`D:\AzerothCore\modules\nekocore` via a real NTFS junction (see "Live and
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
checkout at `D:\AzerothCore` -- clean clone of upstream `azerothcore-wotlk`
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
images cleaned up. `D:\AzerothCore` now runs as `ac-database`/`ac-authserver`/
`ac-worldserver` on the standard ports (3306/3724/8085/7878) -- same ports
and same LAN address (`192.168.0.10`) external DNS/routing already pointed
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
                      D:\AzerothCore\modules\nekocore). Also still holds the
                      ORIGINAL additive-approach Rust tools
                      (build_talent_merge.rs, dbc.rs), kept for history only,
                      superseded by tools/build_patch/build_era_tree.py.
docs/                notes that don't belong in commit messages
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
- **Server** = this repo junctioned into a real AzerothCore checkout
  (`D:\AzerothCore\modules\nekocore`) + the module's own C++
  (`src/EraTalentGate.cpp`, `src/nekocore_loader.cpp`) built into the
  worldserver image.
- **Client** = this repo's `client-patch/Interface/AddOns/*` (committed,
  plain files -- can be copied straight out of a checkout, no release/zip
  step required) plus a locally-built DBC patch MPQ (never committed, see
  above).

**Patching a stock client end to end** is now one command, replacing what
had been done by hand all session
(`tools/install_patch/install_client.py`):

```
# Full: rebuild all 9 classes' era data, package the MPQ, deploy MPQ + addons
python tools/install_patch/install_client.py \
  --wotlk-root "D:\Games\World of Warcraft 3.3.5a" \
  --source-root "D:\Games\World of Warcraft 1.12.1" \
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

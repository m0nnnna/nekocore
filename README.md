# nekocore

Server-side custom work for the NekoCore realm, running on
[AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) (a 3.3.5a,
build 12340 server) plus
[mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression).

**This repo holds only what we add.** It is not a fork of AzerothCore and does
not vendor the engine or the progression module -- both are read from the
existing checkout at `C:\azerothcore-wotlk` (their own separate repos; see
that tree's `modules/` for the progression module). This repo is dropped into
`azerothcore-wotlk\modules\nekocore` the same way, so a build picks it up
without anything being copied.

First project: teaching this realm's talent system about Classic (1.12.1)
talents, to pair with the client-side work on the `nekocore` branch of
`open-wow-client` (a from-scratch WoW 3.3.5a client reimplementation,
client-only -- this repo is where the corresponding server-only work lives,
kept out of that project's own tree on purpose since it documents a
clean-room client, not a custom server).

## Why this needs a server module at all

`mod-individual-progression` tracks which era of content a player has reached
(`ProgressionState`, level thresholds) but has no talent-specific code --
confirmed by reading its source. Classic talent trees differ substantially
from WotLK's for some classes (measured, not assumed --
`open-wow-client`'s `tools/wow-cli/examples/classic_talent_diff.rs`: Druid's
kit is 45% removed-or-changed by WotLK, Warlock close behind at 44%), and the
running server's `sTalentStore` only knows WotLK's `Talent.dbc` rows.
Confirmed directly: sending `CMSG_LEARN_TALENT` for a genuine Classic-only
talent id (761, a Druid Balance talent absent from WotLK's table) is silently
ignored -- no points spent, nothing learned -- while the identical request for
an id present in both tables (796) works and persists normally.

## The plan, as far as it's been thought through

1. ~~Renumber, don't merge as-is.~~ **Built and live-confirmed** --
   `open-wow-client`'s `tools/wow-cli/examples/build_talent_merge.rs`. Stock
   WotLK rows untouched; every Classic talent not already identical to a
   WotLK one gets a new row under its *existing* tab id (all 27 Classic tab
   ids are a strict subset of WotLK's 33 -- same tree, same id, confirmed --
   so no new tabs are needed and the engine's own tier-point-gating and
   prerequisite checks apply to injected rows without modification).

   Two real problems, found by testing on the live realm rather than by
   review:
   - **The id offset matters, not just its uniqueness.** `900,000 + classic_id`
     seemed safe (nowhere near WotLK's own ids) but broke silently: a point
     was spent and nothing was learned. `DBCStorage::LookupEntry` is a flat
     array indexed by raw id, sized to `max_id + 1` at load
     (`DBCFileLoader::AutoProduceData`) -- a 900,762-slot array for 913 real
     rows broke something downstream. `10,000 +` works cleanly.
   - **A talent's spell has to exist here too.** `Player::LearnTalent` never
     checks `addTalent`'s return value, so a talent whose rank spell is not a
     real id in this build's `Spell.dbc` still costs the player a point in
     total silence -- an AzerothCore bug, not something fixable from this
     side. 13 of Druid's 21 originally-planned additions hit this (the
     *ability*, not just the talent slot, was cut between 1.12.1 and WotLK --
     Improved Nature's Grasp among them). The tool now checks every rank's
     spell against the real `Spell.dbc` first and skips (transitively, if
     something depends on a skipped talent) anything that would trigger it.
     Druid's safe set: **8 of 47**. The other 13 need `Spell.dbc` work too,
     not attempted yet.

   Live-confirmed on `Classicdruid`: id 761 (Nature's Grasp) -> 10761
   learned, persisted across a reconnect, and correctly refused a tier-1
   pick (10781) until 5 points were spent in the tab -- the engine's own
   native rule, unmodified, doing exactly what it should to injected data.

2. ~~Find where this server's DBC pack actually lives.~~ **Found and
   confirmed.** Not a host path at all -- a named Docker volume,
   `azerothcore-wotlk_ac-client-data`, populated once by the
   `ac-client-data-init` service (image `acore/ac-wotlk-client-data`, a
   prebuilt data package AzerothCore ships so a server needs no real client
   install) and mounted read-only into the worldserver at
   `/azerothcore/env/dist/data/` (`docker-compose.yml`'s `AC_DATA_DIR`).
   `docker run --rm -v azerothcore-wotlk_ac-client-data:/data alpine ls
   /data/dbc` lists 247 files. **`Talent.dbc` and `TalentTab.dbc` inside it
   are byte-for-byte identical** to the reference 3.3.5a client install
   (`cmp`, not just matching sizes) -- confirmed, not assumed, since a private
   server's data package is exactly the kind of thing that could have drifted
   from a stock client without anyone noticing. This is why merging in
   Classic rows can be worked out entirely offline, against the reference
   install already on disk, with no live risk until the result is actually
   mounted in.

   The mount mechanism for the merged file: Docker supports bind-mounting a
   single file over one that already exists inside a named volume, so
   `docker-compose.override.yml` (the same mechanism `azerothcore-wotlk`'s
   own override already uses for SOAP) can mount a merged `Talent.dbc` at
   `/azerothcore/env/dist/data/dbc/Talent.dbc` without disturbing the other
   246 files the named volume still serves.
3. **Gate by era, not by opt-in.** Hook `ProgressionState`
   (`IP_LEVEL_VANILLA = 60`, etc.) so a Classic talent is only learnable
   pre-Dark-Portal, via a packet hook ahead of the core `CMSG_LEARN_TALENT`
   handler (AzerothCore supports this without patching core source --
   confirm the exact hook point against its source before relying on it).
4. **Point economy.** Classic granted a talent point every level 10-60, not
   WotLK's curve -- likely tracked the same way the progression module already
   tracks its own `PlayerSettings`, rather than fighting core's leveling code.

None of this is built yet. This repo exists so it has somewhere to live when
it is.

## Live state right now

**The local realm's `Talent.dbc` is not stock.** `C:\azerothcore-wotlk\docker-compose.override.yml`
bind-mounts `C:/nekocore/data/generated/Talent-druid.dbc` (Druid's 8 safe
additions, `ID_OFFSET = 10_000`) over `/azerothcore/env/dist/data/dbc/Talent.dbc`
inside the worldserver container. `docker compose restart ac-worldserver`
picks up a regenerated file; removing that `volumes:` entry and restarting
goes back to the named volume's own stock copy. `Classicdruid` (`OWC34`) has
796 and 10761 learned and saved.

`data/generated/` (gitignored -- the `.dbc` is derived from Blizzard data,
not ours to commit) holds the current build; `data/generated/druid-mapping.csv`
(committed) is the classic-id -> server-id table the eventual module needs at
runtime -- an unlisted classic id means "not yet safe to merge", not "bug".

## Client-side state, for reference

Confirmed working end to end on the client (`nekocore` branch,
`open-wow-client`): `Talent.dbc`/`TalentTab.dbc` transcribed and verified
against the real 1.12.1 install, `CMSG_LEARN_TALENT`/`SMSG_TALENTS_INFO`
confirmed live, a talent window drawing a real 1.12.1 tree with real names and
icons (via a Classic `Spell.dbc`/`SpellIcon.dbc` schema, transcribed
separately from this build's own since the two are different tables). What it
sends is only ever as good as what the server understands -- which, right
now, is only what WotLK already shipped.

## Building a merged `Talent.dbc`

`cargo build --release` (a plain Rust binary crate, no dependencies -- see
`src/dbc.rs`'s own doc comment for why it vendors a minimal WDBC reader/writer
rather than depending on `open-wow-client`'s `dbc` crate). Produces
`target/release/build-talent-merge.exe`.

It needs four already-extracted flat `.dbc` files as input -- it has no MPQ
reader of its own. Pull them out with `open-wow-client`'s `wow-cli`, or copy
`wotlk-Talent.dbc`/`wotlk-Spell.dbc` straight out of the server's own data
volume if there's any doubt they've drifted from stock (see
`build_talent_merge.rs`'s own doc comment for both commands). Then:

```
build-talent-merge <classic Talent.dbc> <classic TalentTab.dbc> <wotlk Talent.dbc> <wotlk Spell.dbc> <class_mask> <out Talent.dbc> <out mapping.csv>
```

`class_mask` is the bit for one class (1=Warrior, 2=Paladin, 4=Hunter,
8=Rogue, 16=Priest, 64=Shaman, 128=Mage, 256=Warlock, 1024=Druid -- 32 and
512 are Death Knight and unused respectively, both out of scope for a
Classic merge since neither existed in 1.12.1).

**Verified byte-identical to `open-wow-client`'s own copy of this tool**,
whose output is the one actually mounted and live-tested (see above) -- this
one was built to not need that repo checked out, not to be a second,
independently-trusted implementation.

## Layout

```
data/inputs/     -- extracted flat DBCs, gitignored (Blizzard's data)
data/generated/  -- this tool's output; the .dbc is gitignored, the
                    mapping .csv is not (it's ours, and the module will need
                    it at runtime)
data/sql/        -- database changes, once there are any
src/             -- this repo's own tools, and the eventual C++ module
docs/            -- notes that don't belong in commit messages
```

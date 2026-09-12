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

1. **Renumber, don't merge as-is.** Some Classic talent ids collide with real,
   different WotLK talents (id != removed, just changed) -- learning through
   one of those would silently teach the wrong thing. Classic ids need moving
   into a range `sTalentStore` doesn't already use before they mean anything
   server-side.
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

## Client-side state, for reference

Confirmed working end to end on the client (`nekocore` branch,
`open-wow-client`): `Talent.dbc`/`TalentTab.dbc` transcribed and verified
against the real 1.12.1 install, `CMSG_LEARN_TALENT`/`SMSG_TALENTS_INFO`
confirmed live, a talent window drawing a real 1.12.1 tree with real names and
icons (via a Classic `Spell.dbc`/`SpellIcon.dbc` schema, transcribed
separately from this build's own since the two are different tables). What it
sends is only ever as good as what the server understands -- which, right
now, is only what WotLK already shipped.

## Layout

```
data/sql/    -- database changes, once there are any
src/         -- the module's C++, once there is any
docs/        -- notes that don't belong in commit messages
```

Nothing under those exists yet either. This file is the plan until code
replaces parts of it.

# Bug: spending a talent point lands it in the wrong era's tab

**Status: open, unsolved.** Two other real bugs in the same feature were found
and fixed along the way (see "Already fixed" below) — this doc is about the
one that's still broken.

**Read the safety warning before touching any of this live.**

## Safety warning: OrderIndex must stay 0, 1, or 2. Ever. For any tab.

One fix attempt at this exact bug set a talent tab's `OrderIndex` field to a
value >= 3 (specifically 3-8, one non-overlapping block per era) and it
**crashed `ac-worldserver` with a SIGSEGV** on load.

Root cause: `D:\AzerothCore\src\server\game\DataStores\DBCStores.cpp` has

```cpp
static uint32 sTalentTabPages[MAX_CLASSES][3];   // line ~173
...
sTalentTabPages[cls][talentTabInfo->tabpage] = talentTabId;   // line ~524
```

with **no bounds check**. `OrderIndex` (the Python schema's field name, see
`tools/dbc/schemas.py`) *is* that `tabpage` field — confirmed by aligning
field offsets between the Python schema and the C++ `TalentTabEntry` struct
in `DBCStructure.h` (`ClassMask` lands on the same slot — offset 20 — in
both, which anchors the rest of the layout). Any `OrderIndex >= 3` is an
out-of-bounds write into whatever memory follows that static array.

There's also a second, independent max-3 assumption in
`Player.cpp` (~line 15706, 15728: `if (tab->tabpage < 3) specPoints[tab->tabpage] += ...`)
which at least has a bounds check, but confirms the engine assumes at most 3
talent tabs per class as a hard, load-bearing invariant, not a tunable limit.

**Do not attempt to fix this bug by giving OrderIndex/tabpage a value outside
{0, 1, 2} for any TalentTab.dbc row, under any circumstances, without first
finding and neutralizing every fixed-size array indexed by it.** If you do,
verify by checking `docker logs ac-worldserver` for a clean
`WORLD: World Initialized` line (not a restart loop / exit code 139) before
considering it safe, and always check
`SELECT COUNT(*) FROM acore_characters.characters WHERE online=1` before
restarting the container at all.

## Feature context: what "era talents" is and how it's built

`tools/build_patch/build_era_tree.py` gives each class **9 dedicated talent
tabs** instead of the stock 3: tabs 1-3 are WotLK's own (untouched), 4-6 are a
full authentic Vanilla (1.12.1) tree built under brand-new
`TalentTab.dbc`/`Talent.dbc` ids, and 7-9 are the same for TBC (2.4.3). This
is a from-scratch tree per era, not talents merged into WotLK's existing
tabs — see that file's own module-level docstring for the full reasoning
(an earlier additive approach was tried and abandoned; the docstring there
explains why).

- New tab ids: `ERA_CONFIG[era]["tab_base"] + class_id*10 + tree_index`
  (`tree_index` = 0,1,2, that era's position among the class's 3 trees).
  Currently Vanilla's `tab_base` is 8000, TBC's is 9000 (see "Ruled out"
  below for why these specific numbers, and why swapping them didn't fix
  anything).
- New talent ids: `classic_id + ERA_CONFIG[era]["id_offset"]` (Vanilla
  +10,000, TBC +20,000) — these don't collide with anything and aren't
  implicated in this bug.
- `client-patch/Interface/AddOns/NekoTalentUI/NekoTalentUI.lua` is a
  from-scratch Lua talent frame (the stock Blizzard one can't handle more
  than 3 same-class tabs — see that file's own doc comment) that:
  - Detects the character's era via `IsQuestFlaggedCompleted` on two hidden
    progression quest ids that `mod-individual-progression` tracks
    (`DetectEra()`), and shows whichever 3-tab block (1-3, 4-6, or 7-9)
    matches.
  - Calls the **stock** `LearnTalent(tabIndex, talentIndex)` Lua API against
    whatever tab index the client itself reports via `GetTalentTabInfo`/
    `GetNumTalentTabs` — it does not reimplement talent-learning, only the
    display, so the actual `CMSG_LEARN_TALENT`/`CMSG_LEARN_PREVIEW_TALENTS`
    → server round trip is exactly what the stock frame would have sent.
- `client-patch/Interface/AddOns/NekoTalentDebug/NekoTalentDebug.lua`
  (`/ntd`) is a diagnostic-only addon that dumps `GetTalentTabInfo`/
  `GetTalentInfo` for tab indices 1-9 directly to chat. **This is the tool
  that found and will verify this bug** — use it before and after every
  fix attempt.

## The bug, live-confirmed

Reproduced identically on two different classes (Rogue, Warlock), fresh
level-20 characters, confirmed via `.ip get <name>` to be at
**Progression Level 0** (nowhere near the TBC threshold of 8) — i.e.
genuinely, unambiguously still in the Vanilla era, not a stale/cached state.

Steps:
1. Open `NekoTalentUI` (`/neko` or the `N` keybind). Title bar correctly
   reads "Era Talents (Vanilla)".
2. Click a tier-1 talent in the displayed grid (e.g. the first Assassination
   talent for a Rogue).
3. Run `/ntd`.

Expected: the tab NekoTalentUI displayed (client tab index 4, 5, or 6 —
Vanilla) shows the new rank/pointsSpent.

Actual: **the corresponding TBC tab (index 7, 8, or 9 — same tree position,
i.e. 4↔7, 5↔8, 6↔9) shows the point instead.** The Vanilla tab that was
actually displayed and clicked stays at 0. A full swap of the Vanilla (4-6)
and TBC (7-9) blocks, every time, on both classes tested.

Also independently confirmed via the database:
`character_talent` for the test character has real, persisted rows for the
TBC-tab talent's spell id, and `.ip get` on the same character confirms
Progression Level 0 at the time — so this is not the server legitimately
allowing a TBC-progressed character to use TBC tabs. The server received a
request for a specific talent id, and that talent id belongs to the TBC tab,
even though the client displayed and the player clicked in the Vanilla tab.

**This means the bug is in the client's own tabIndex → talentId resolution**
(inside `LearnTalent`'s C-side implementation, not in Lua, not visible to
us) — not in `EraTalentGate.cpp`'s server-side validation, which by this
point correctly receives the (wrong) talent id and correctly allows it
(since the character isn't blocked from Vanilla tabs, and the wrong tab
that got the point IS one it's blocked from *if the check ran* — see
"Already fixed" #3 for why it wasn't blocked at the time this was found).

## Already fixed (not this bug, but found while chasing it)

1. **`NekoTalentUI.lua` talent buttons never called `RegisterForClicks`.**
   A plain `CreateFrame("Button", ...)` never fires `OnClick` for any mouse
   button until you call `RegisterForClicks`. Clicking a talent did
   *nothing* — no error, no server call. Fixed: commit `a976a64`.
2. **`UpdateTalents()` was called synchronously right after `LearnTalent()`**,
   reading pre-response data almost every time (the real change only lands
   after the `CMSG_LEARN_TALENT`/`CMSG_LEARN_PREVIEW_TALENTS` round trip).
   Fixed by listening for `CHARACTER_POINTS_CHANGED` (the same event the
   stock talent frame uses) and refreshing then too. Commit `b27a4fc`.
3. **`EraTalentGate.cpp` (the server-side era-lock `ServerScript`) only
   checked the `CMSG_LEARN_TALENT` opcode.** WotLK's actual talent-learn
   flow — confirmed via `HandleLearnPreviewTalents` in
   `D:\AzerothCore\src\server\game\Handlers\SkillHandler.cpp` — sends
   `CMSG_LEARN_PREVIEW_TALENTS` instead (a count-prefixed array of
   `(talentId, rank)` pairs), which was never inspected, so the entire era
   gate was dead code the whole time it's been running. Fixed to check both
   opcodes, rejecting the whole batch if any entry fails era gating.
   Commit `b2d5aa5`. **This fix is real and correct** — it's just not
   sufficient to prevent the wrong-tab bug, because the client sends the
   wrong talent id in the first place; the gate can only allow-or-deny
   whatever id it's given.

## Ruled out for the wrong-tab bug

1. **Tab id numeric ordering.** Vanilla's `tab_base` was originally 9000,
   TBC's 8000 — numerically backwards from write order (stock, then
   Vanilla, then TBC). Hypothesis: `LearnTalent`'s internal resolution
   walks tabs in ID-ascending order while `GetTalentTabInfo` reports them in
   file/write order, so the numerically-inverted TBC block was being hit
   first. **Tested live: swapped `tab_base` (Vanilla→8000, TBC→9000, with
   matching `EraTalentGate.cpp` constants), rebuilt and redeployed both
   client and server. Zero change in behavior** — same exact swap still
   happened. Ruled out. (Commit `aa327f3` made this change; it's still in
   place since it's harmless, just not the fix.)

2. **`OrderIndex` collision (correct diagnosis, unsafe fix).** Every era's 3
   tabs reuse `OrderIndex` 0, 1, 2 (`tree_index`, unmodified) — i.e. every
   era's Assassination-equivalent tab has `OrderIndex=0`, identically,
   across stock/Vanilla/TBC. Verified directly by reading the generated
   `TalentTab.dbc` with `tools/dbc/wdbc.py`. Hypothesis: `LearnTalent`'s
   internal resolution groups or sorts by `OrderIndex`, so same-`OrderIndex`
   tabs across eras collide, while `GetTalentTabInfo`/`GetNumTalentTabs`
   don't key off it the same way (hence display and learn disagreeing).
   **This diagnosis is likely correct as a mechanism** — but the fix
   (spreading each era into its own `OrderIndex` block: stock 0-2, Vanilla
   3-5, TBC 6-8) crashes the server. See the safety warning at the top.
   Reverted in commit `4ba1685`.

## Not yet tried

1. **`CategoryEnumID`.** Currently hardcoded to `0` for every custom tab
   row (`tools/build_patch/build_era_tree.py`, `new_tab_row["CategoryEnumID"] = 0`)
   — the same collision shape `OrderIndex` had. Unknown whether
   `LearnTalent`'s resolution reads this field, and unknown whether the
   engine has another fixed-size array indexed by it the way `tabpage` was.
   **Before testing this live: grep the actual field name this maps to in
   `D:\AzerothCore\src\server\shared\DataStores\DBCStructure.h`'s
   `TalentTabEntry` struct (or whatever WotLK-specific variant exists — the
   struct found during this investigation, ending at a `tabpage` field, may
   be the older Vanilla/TBC-era layout; `tools/dbc/schemas.py`'s own
   docstring notes WotLK's actual DBC format adds `CategoryMask`/
   `CategoryEnumID` on top of that layout, so there may be a separate,
   longer WotLK struct definition this investigation didn't locate — find
   it before assuming byte-offset alignment holds the same way it did for
   `OrderIndex`/`tabpage`), then grep every use of that field across
   `DBCStores.cpp`, `Player.cpp`, `Pet.cpp`, and
   `src/server/scripts/Commands/cs_learn.cpp` (the same four files
   `tabpage` turned up in) for any fixed-size array or assumed range before
   writing a non-default value anywhere.**

2. **Different architecture: only 3 live tabs per class, swapped per era,
   instead of 9 simultaneous tabs.** If the engine's per-class tab
   bookkeeping is fundamentally capped at 3 (which the `sTalentTabPages`
   crash strongly suggests), the entire "9 dedicated tabs, always all
   present" design may not be viable to fully fix within this engine's
   constraints. An alternative would swap which 3 tabs are the "live" ones
   for a class based on the character's era rather than exposing all 9 at
   once — a materially bigger redesign (DBC content would need to be
   effectively different per character, which a single static
   client-loaded file can't do directly; would need a different mechanism
   entirely, possibly server-driven). Not investigated at all yet — flagging
   as a fallback if (1) also turns out to be a dead end.

3. Consider researching whether other WotLK-era private-server projects have
   solved ">3 talent tabs per class" before — this is a sufficiently unusual
   thing to want (real Blizzard content never needed it) that it may be a
   known, documented limitation/workaround in that community.

## Key files

Repo root is `C:\nekocore` unless noted.

- `tools/build_patch/build_era_tree.py` — generates the custom DBCs.
  `ERA_CONFIG` dict (tab_base/id_offset per era), `new_tab_id()`, and the
  `new_tab_row["OrderIndex"] = tree_index` line are all directly relevant.
- `src/EraTalentGate.cpp` — server-side era-lock `ServerScript`.
  `VANILLA_TAB_ID_MIN/MAX`, `TBC_TAB_ID_MIN/MAX`, `IsTalentAllowed()`.
- `client-patch/Interface/AddOns/NekoTalentUI/NekoTalentUI.lua` —
  custom talent frame. `DetectEra()`, `SetEra()`, `ActualTabIndex()`,
  the per-talent button `OnClick`.
- `client-patch/Interface/AddOns/NekoTalentDebug/NekoTalentDebug.lua` —
  the `/ntd` diagnostic tool. Use it, don't guess.
- `tools/dbc/wdbc.py`, `tools/dbc/schemas.py` — Python DBC read/write +
  field layouts. Useful for inspecting `data/generated/*.dbc` directly
  without needing a live client (e.g. checking `OrderIndex`/tab ids for a
  given class without opening the game).
- `D:\AzerothCore\src\server\game\DataStores\DBCStores.cpp` — `sTalentTabPages`
  declaration (~line 173) and the unsafe write (~line 524).
- `D:\AzerothCore\src\server\shared\DataStores\DBCStructure.h` — `TalentTabEntry`
  struct (~line 1939) — **re-verify this is the right struct for a 3.3.5a
  build before trusting its field layout for anything new**, see "Not yet
  tried" #1.
- `D:\AzerothCore\src\server\game\Entities\Player\Player.cpp` — other
  `tabpage < 3` assumptions (~lines 15706, 15728).

## Environment / how to rebuild and test

Local AzerothCore Docker stack at `D:\AzerothCore` (`docker-compose.yml` +
`docker-compose.override.yml`; services `ac-worldserver`, `ac-authserver`,
`ac-database`). Test client at `D:\Games\World of Warcraft 3.3.5a`; reference
source clients for DBC extraction at `D:\Games\World of Warcraft 1.12.1` and
`D:\Games\World of Warcraft 2.4.3` (only their `Data\*.MPQ` files matter, see
`tools/dbc/mpq_source.py` — no need for a full game-playable install).

Regenerate + deploy the client patch (also redeploys both addons):

```
python tools\install_patch\install_client.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a" --vanilla-root "D:\Games\World of Warcraft 1.12.1" --tbc-root "D:\Games\World of Warcraft 2.4.3" --build
```

Sync module source into the AzerothCore checkout (**do this before every
`ac-worldserver` rebuild** — `D:\AzerothCore\modules\nekocore` is a real
copy, not a junction; Docker Desktop's build-context computation on this
machine turns an NTFS junction there into a dangling symlink inside the
Linux build container, silently compiling the module out entirely):

```
python tools\server\sync_module.py
```

Rebuild + restart the server (from `D:\AzerothCore`) — **always check for
online players first**, and confirm `World Initialized` (not a restart loop)
after:

```
docker compose build ac-worldserver
```
```sql
SELECT COUNT(*) FROM acore_characters.characters WHERE online = 1;  -- must be 0
```
```
docker compose -f docker-compose.yml -f docker-compose.override.yml --project-directory . up -d --force-recreate ac-worldserver
```

A full client logout/login (not `/reload`) is required after any `--build`
run, since the MPQ itself changes.

`.ip get <charname>` (GM command from `mod-individual-progression`) gives
the character's live, authoritative progression level — more reliable than
querying `character_queststatus_rewarded` directly, which can lag behind
in-memory state until the next save.

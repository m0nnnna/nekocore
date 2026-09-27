"""
Builds full, authentic era talent trees under BRAND NEW TalentTab.dbc/
Talent.dbc ids -- not merged into WotLK's existing 3 tabs. Supports two
source eras now, each under its own dedicated id range so they can coexist
in the same output DBCs without collision:

    era     source build   tab ids               talent ids
    Vanilla 1.12.1         9000 + class_id*10+n   classic_id + 10_000
    TBC     2.4.3          8000 + class_id*10+n   classic_id + 20_000

(n = 0,1,2, the tree's position among that class's 3 tabs.) Both ranges sit
comfortably above WotLK's own max ids (tab 411, talent ~2300) and don't
overlap each other, so a class can have all three eras' full trees loaded
at once: 3 stock WotLK tabs, then 3 Vanilla tabs, then 3 TBC tabs -- always
in that fixed order (see ERA_ORDER below), so a class's tab INDEX (as the
client's own GetNumTalentTabs/GetTalentTabInfo report it, which is which
NekoTalentUI keys off) is stable regardless of which --*-root flags a given
run passes: tabs 1-3 stock, 4-6 Vanilla (if built), 7-9 TBC (if built).

This supersedes the earlier additive approach (merge_talents.py in this
repo's git history / wow-client-patch): reusing WotLK's existing tabs can,
at best, sprinkle a few old talents into an otherwise-WotLK tree, because
Talent.dbc is one static file shared by every character -- there's no way
for the stock client to show a DIFFERENT tree to a Vanilla-era character
than a WotLK-era one from the SAME tab id. Full per-character authentic
recreation needs each era's tree to live at its OWN tab ids, which
NekoTalentUI then chooses whether to display based on the character's
actual era (from mod-individual-progression's rewarded-quest state).

Because each era gets dedicated tab ids, this tool does NOT need the
collision-avoidance/relocation logic merge_talents.py needed (no existing
WotLK row can occupy a cell in a tab id WotLK never shipped) -- the
authentic classic (tier, column) layout is copied verbatim, and since it's
real Blizzard-authored data, prerequisite-before-dependent tier ordering is
already correct by construction.

Still applies, same as before (see merge_talents.py's doc comment for why):
  - A talent's rank spells must already exist in WotLK's Spell.dbc --
    Player::LearnTalent silently no-ops on an unknown spell id. Porting the
    missing spells into Spell.dbc is real, separate follow-on work.
    A talent is kept with the LEADING ranks that do exist (WotLK squashed
    a lot of 5-rank Classic talents down to 3 ranks, keeping the rank 1-3
    spell ids and deleting ranks 4-5 -- e.g. Paladin's Improved Devotion
    Aura / Redoubt). Dropping the whole talent for that used to leave the
    Vanilla Protection Paladin tab with an EMPTY tier 0, which makes the
    entire tab unspendable (the 5-point gate for tier 1 can never be met),
    not merely incomplete. A dependent talent's PrereqRank is clamped to
    the truncated prerequisite's new max rank. Only a talent whose rank 1
    (or a middle rank) is missing is dropped, transitively.
  - Talent.dbc rows for one tab must be one contiguous, (tier,column)-sorted
    block in the file, or the retail client's talent frame fails to render
    that tab at all -- live-confirmed this session. Since we're
    constructing each new tab's block from scratch (not inserting into an
    existing one), this tool builds it pre-sorted and inserts it as a whole
    block in one place.

New TalentTab.dbc rows use the SOURCE era's own name/icon/racemask (WotLK's
own all-races mask, not the source era's -- see the live Blood Elf/Draenei
bug this fixed)/background -- full authenticity, not a reskinned WotLK tab.

Usage (repeat --class to do several in one run; pass whichever of
--vanilla-root/--tbc-root you want represented -- REQUIRED every run to keep
what you want without losing it: this tool reads everything fresh from the
client(s) each run and writes a COMPLETE REPLACEMENT output, it does NOT
read back its own prior output and add to it. Want both eras in the file?
Pass both roots every time, same as you'd repeat every --class every time):
    python build_era_tree.py \\
        --wotlk-root "D:\\...\\3.3.5a" \\
        --vanilla-root "D:\\...\\1.12.1" --tbc-root "D:\\...\\2.4.3" \\
        --class druid --class warrior --class mage \\
        --out-dbc-dir out/ --out-mapping-dir out/
"""
from __future__ import annotations

import argparse
import json
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dbc"))
from wdbc import (  # noqa: E402
    LOCALE_COUNT,
    DbcFile,
    StringBlockBuilder,
    new_loc_string,
    new_string_field,
    read_dbc,
    write_dbc,
)
from schemas import BUILD_SCHEMAS  # noqa: E402
import mpq_source  # noqa: E402

N_RANKS_COMPARED = 5
RANK_FIELDS = [f"SpellRank_{i}" for i in range(N_RANKS_COMPARED)]

SPELL_ATTR0_PASSIVE = 0x40
SPELL_EFFECT_LEARN_SPELL = 36

CLASSES = {
    "warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5,
    "shaman": 7, "mage": 8, "warlock": 9, "druid": 11,
}
CLASS_MASKS = {slug: 1 << (cid - 1) for slug, cid in CLASSES.items()}

# Fixed processing order -- controls tab INDEX stability (see module doc
# comment). "root_arg" is the argparse dest holding that era's client root.
#
# OrderIndex/"tabpage" MUST stay in [0,2] -- DO NOT widen this per era.
# Tried giving each era a non-overlapping OrderIndex block (Vanilla 3-5,
# TBC 6-8) to fix a real wrong-tab-targeting bug (see below); it crashed
# ac-worldserver on load (SIGSEGV). Root cause: DBCStores.cpp has
# `static uint32 sTalentTabPages[MAX_CLASSES][3]` and does
# `sTalentTabPages[cls][talentTabInfo->tabpage] = talentTabId` with NO
# bounds check -- any tabpage >= 3 is an out-of-bounds write into adjacent
# memory. This is a hard engine ceiling, not a tunable value. Reverted to
# tree_index (0,1,2, colliding across eras) to restore stability.
#
# The bug that was trying to fix (a point spent in a Vanilla tab showing up
# in the same-position TBC tab) turned out to be unrelated to OrderIndex or
# tab ids at all: the eras share SPELL ids, and the core reports learned
# talents back to the client by spell -> last-loaded talent id, i.e. the
# TBC twin. Fixed server-side in src/EraTalentInfoRemap.cpp; see
# docs/era-talent-wrong-tab-bug.md. Tab ids/OrderIndex here are fine as-is.
ERA_ORDER = ["1.12.1", "2.4.3"]
ERA_CONFIG = {
    "1.12.1": {"label": "Vanilla", "tab_base": 8000, "id_offset": 10_000, "root_arg": "vanilla_root"},
    "2.4.3":  {"label": "TBC",     "tab_base": 9000, "id_offset": 20_000, "root_arg": "tbc_root"},
}


def load(build: str, filename: str, root: Path, tmp_dir: Path):
    schema = BUILD_SCHEMAS[build][filename]
    archive, data = mpq_source.resolve(root, filename)
    print(f"  {build} {filename}: resolved from {archive}", file=sys.stderr)
    path = tmp_dir / f"{build}-{filename}"
    path.write_bytes(data)
    return read_dbc(path, schema, LOCALE_COUNT[build])


def ranks_of(row: dict) -> tuple[int, ...]:
    return tuple(row[f] for f in RANK_FIELDS)


def new_tab_id(era: str, class_id: int, tree_index: int) -> int:
    return ERA_CONFIG[era]["tab_base"] + class_id * 10 + tree_index


def build_one_class(
    class_slug: str,
    *,
    era: str,
    src_talents,
    src_tabs,
    wotlk_spell_ids: set[int],
    active_talent_spells: set[int],
    wotlk_class_racemask: dict[str, int],
    tab_string_builder: StringBlockBuilder,
    locale_count: int,
    mapping: dict[int, int],
    era_spells: dict[int, int] | None = None,
):
    """Builds one class's new tab/talent rows for one era. `mapping`
    (classic talent id -> new id) and `tab_string_builder` are shared/
    mutated across classes WITHIN one era by the caller so a multi-class run
    produces one consistent output -- but must be a FRESH dict per era (raw
    classic ids from two different client builds aren't the same namespace;
    reusing one dict across eras would let a TBC id silently clobber a
    same-numbered Vanilla id's mapping entry)."""
    id_offset = ERA_CONFIG[era]["id_offset"]
    class_id = CLASSES[class_slug]
    class_mask = CLASS_MASKS[class_slug]

    class_tabs = sorted(
        (row for row in src_tabs.rows if row["ClassMask"] & class_mask),
        key=lambda r: r["OrderIndex"],
    )
    assert len(class_tabs) == 3, f"expected 3 tabs for {class_slug}, got {len(class_tabs)}"

    new_tab_rows: list[dict] = []
    new_talent_rows: list[dict] = []
    tab_id_map: dict[int, int] = {}  # classic tab id -> new tab id

    for tree_index, tab in enumerate(class_tabs):
        old_tab_id = tab["ID"]
        assigned_tab_id = new_tab_id(era, class_id, tree_index)
        tab_id_map[old_tab_id] = assigned_tab_id
        print(f"[{ERA_CONFIG[era]['label']}] tab '{tab['Name_lang']['enUS']}' ({old_tab_id}) -> new tab id {assigned_tab_id}")

        new_tab_row = {f.name: 0 for f in BUILD_SCHEMAS["3.3.5a"]["TalentTab.dbc"]}
        new_tab_row["ID"] = assigned_tab_id
        # Name_lang/BackgroundFile are string-block OFFSETS -- the classic
        # row's offsets point into ITS OWN build's string block (a
        # different file), so they're meaningless here. Re-intern the text
        # values into the output's (WotLK TalentTab.dbc's) string block.
        new_tab_row["Name_lang"] = new_loc_string(tab_string_builder, tab["Name_lang"]["enUS"], locale_count)
        new_tab_row["SpellIconID"] = tab["SpellIconID"]
        # NOT tab["RaceMask"] -- that's the SOURCE era's mask, which has
        # zero bits for any race added after that era (Blood Elf, Draenei
        # for Vanilla). Live bug: a Blood Elf Rogue saw 3 tabs instead of 6
        # because our new tabs excluded their race. Race eligibility for the
        # CLASS itself is already enforced at character creation -- the
        # tab itself shouldn't additionally restrict by race, so use
        # WotLK's own (all-races) mask for this class instead.
        new_tab_row["RaceMask"] = wotlk_class_racemask[class_slug]
        new_tab_row["ClassMask"] = class_mask
        new_tab_row["CategoryEnumID"] = 0
        new_tab_row["OrderIndex"] = tree_index  # MUST stay 0,1,2 -- see ERA_CONFIG comment above
        new_tab_row["BackgroundFile"] = new_string_field(tab_string_builder, tab["BackgroundFile"]["value"])
        new_tab_rows.append(new_tab_row)

        tab_talents = sorted(
            (row for row in src_talents.rows if row["TabID"] == old_tab_id),
            key=lambda r: (r["TierID"], r["ColumnIndex"]),
        )

        unsafe_ids: set[int] = set()
        included: list[dict] = []
        kept_ranks: dict[int, tuple[int, ...]] = {}  # classic id -> ranks actually emitted
        for row in tab_talents:
            rid = row["ID"]
            # Each rank at this era's own copy of the spell when one exists
            # (build_era_spells.py). Pointing at the shared id instead gave
            # an era character WotLK's spell -- and where WotLK reused the id
            # a different spell entirely: Vanilla Ice Block's talent taught
            # Cold Snap, Death Wish taught Sweeping Strikes.
            row_ranks = [(era_spells or {}).get(s, s) for s in ranks_of(row) if s != 0]
            # Longest leading run of ranks whose spells WotLK still has.
            present: list[int] = []
            for spell in row_ranks:
                if spell not in wotlk_spell_ids:
                    break
                present.append(spell)
            if not present:
                print(f"  {rid} SKIPPED: rank 1 spell {row_ranks[0]} does not exist in WotLK's Spell.dbc")
                unsafe_ids.add(rid)
                continue
            if len(present) < len(row_ranks):
                print(f"  {rid} TRUNCATED to {len(present)}/{len(row_ranks)} ranks: "
                      f"spell(s) {row_ranks[len(present):]} do not exist in WotLK's Spell.dbc")
            kept_ranks[rid] = tuple(present)
            included.append(row)
            mapping[rid] = rid + id_offset

        changed = True
        while changed:
            changed = False
            kept = []
            for row in included:
                rid = row["ID"]
                depends_on = row["PrereqTalent_0"]
                if depends_on and depends_on in unsafe_ids:
                    print(f"  {rid} SKIPPED: depends on {depends_on}, which was itself skipped")
                    unsafe_ids.add(rid)
                    mapping.pop(rid, None)
                    changed = True
                else:
                    kept.append(row)
            included = kept

        print(f"  tab total: {len(tab_talents)}, included: {len(included)}, skipped: {len(unsafe_ids)}")

        for row in included:
            rid = row["ID"]
            new_id = mapping[rid]
            new_row = {f.name: 0 for f in BUILD_SCHEMAS["3.3.5a"]["Talent.dbc"]}
            new_row["ID"] = new_id
            new_row["TabID"] = assigned_tab_id
            new_row["TierID"] = row["TierID"]
            new_row["ColumnIndex"] = row["ColumnIndex"]
            ranks = kept_ranks[rid]
            for i in range(9):
                new_row[f"SpellRank_{i}"] = ranks[i] if i < len(ranks) else 0
            # addToSpellBook. Player::LearnTalent only puts an active talent
            # spell into the spellbook when this is set; without it the spell
            # is never learned. The client still shows it, but the server
            # silently drops every cast (HandleCastSpellOpcode's
            # HasActiveSpell check) and the caster hangs in the cast
            # animation. Vanilla/TBC's own Talent.dbc leave it 0, so it is set
            # the way WotLK sets it on its own active talents.
            new_row["Flags"] = int(ranks[0] in active_talent_spells)
            depends_on = row["PrereqTalent_0"]
            if depends_on:
                translated = mapping.get(depends_on)
                if translated is None:
                    raise RuntimeError(f"talent {rid} depends on {depends_on}, not included")
                new_row["PrereqTalent_0"] = translated
                # PrereqRank is 0-indexed in Talent.dbc (rank 5 of 5 -> 4).
                # If the prerequisite lost ranks above, the original value
                # may now be unreachable -- clamp to its new top rank.
                prereq_max = len(kept_ranks[depends_on]) - 1
                new_row["PrereqRank_0"] = min(row["PrereqRank_0"], prereq_max)
                if new_row["PrereqRank_0"] != row["PrereqRank_0"]:
                    print(f"  {rid} prereq rank clamped {row['PrereqRank_0']} -> {prereq_max} "
                          f"(prerequisite {depends_on} was truncated)")
            new_talent_rows.append(new_row)
        # already sorted by (TierID, ColumnIndex) since tab_talents was

    return {
        "new_tab_rows": new_tab_rows,
        "new_talent_rows": new_talent_rows,
        "tab_id_map": tab_id_map,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path)
    ap.add_argument("--vanilla-root", type=Path, help="1.12.1 client root -- omit to leave Vanilla out of this run's output")
    ap.add_argument("--tbc-root", type=Path, help="2.4.3 client root -- omit to leave TBC out of this run's output")
    ap.add_argument(
        "--class", dest="classes", action="append", required=True, choices=sorted(CLASSES),
        help="repeatable -- all classes given in ONE run land in the same output file",
    )
    ap.add_argument("--spell-dbc", type=Path,
                    help="WotLK Spell.dbc to check rank spells against instead of the stock client's -- "
                         "pass port_era_spells.py's output so the talents it rescued are emitted")
    ap.add_argument("--era-spell-map", type=Path,
                    help="build_era_spells.py's era-spell-map.json: point each era's talent ranks at that era's "
                         "own spell copies. Pass --spell-dbc build_era_spells.py's Spell.dbc with it, so the "
                         "copies are found")
    ap.add_argument("--out-dbc-dir", required=True, type=Path)
    ap.add_argument("--out-mapping-dir", required=True, type=Path)
    args = ap.parse_args()

    era_roots = {"1.12.1": args.vanilla_root, "2.4.3": args.tbc_root}
    active_eras = [e for e in ERA_ORDER if era_roots[e]]
    if not active_eras:
        raise SystemExit("pass at least one of --vanilla-root / --tbc-root")

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        wotlk_talents = load("3.3.5a", "Talent.dbc", args.wotlk_root, tmp_dir)
        if args.spell_dbc:
            wotlk_spell = read_dbc(args.spell_dbc, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"], LOCALE_COUNT["3.3.5a"])
            print(f"  3.3.5a Spell.dbc: {args.spell_dbc} ({len(wotlk_spell.rows)} rows)", file=sys.stderr)
        else:
            wotlk_spell = load("3.3.5a", "Spell.dbc", args.wotlk_root, tmp_dir)
        wotlk_tabs = load("3.3.5a", "TalentTab.dbc", args.wotlk_root, tmp_dir)
        era_src = {
            era: (load(era, "Talent.dbc", era_roots[era], tmp_dir), load(era, "TalentTab.dbc", era_roots[era], tmp_dir))
            for era in active_eras
        }

    wotlk_spell_ids = {row["ID"] for row in wotlk_spell.rows}
    # Player::LearnTalent's own test for "goes in the spellbook": not
    # SPELL_ATTR0_PASSIVE and no SPELL_EFFECT_LEARN_SPELL.
    active_talent_spells = {
        row["ID"] for row in wotlk_spell.rows
        if not row["Attributes"] & SPELL_ATTR0_PASSIVE
        and SPELL_EFFECT_LEARN_SPELL not in (row["Effect_0"], row["Effect_1"], row["Effect_2"])
    }
    era_spell_maps: dict[str, dict[int, int]] = {}
    if args.era_spell_map:
        raw = json.loads(args.era_spell_map.read_text(encoding="utf-8"))["id_map"]
        era_spell_maps = {label: {int(k): v for k, v in m.items()} for label, m in raw.items()}
    wotlk_class_racemask = {
        slug: next(t["RaceMask"] for t in wotlk_tabs.rows if t["ClassMask"] & CLASS_MASKS[slug])
        for slug in CLASSES
    }
    tab_string_builder = StringBlockBuilder(wotlk_tabs.string_block)

    all_new_tab_rows: list[dict] = []
    all_new_talent_rows: list[dict] = []
    # class -> era -> build_one_class() result, for the mapping CSVs
    per_class: dict[str, dict[str, dict]] = {c: {} for c in args.classes}

    for era in active_eras:
        src_talents, src_tabs = era_src[era]
        mapping: dict[int, int] = {}  # classic id -> new id, fresh per era (see build_one_class's doc comment)
        for class_slug in args.classes:
            print(f"\n=== {ERA_CONFIG[era]['label']} / {class_slug} ===")
            result = build_one_class(
                class_slug, era=era,
                src_talents=src_talents, src_tabs=src_tabs,
                wotlk_spell_ids=wotlk_spell_ids,
                active_talent_spells=active_talent_spells,
                wotlk_class_racemask=wotlk_class_racemask,
                tab_string_builder=tab_string_builder, locale_count=wotlk_tabs.locale_count,
                mapping=mapping,
                era_spells=era_spell_maps.get(ERA_CONFIG[era]["label"]),
            )
            all_new_tab_rows += result["new_tab_rows"]
            all_new_talent_rows += result["new_talent_rows"]
            per_class[class_slug][era] = result

    args.out_dbc_dir.mkdir(parents=True, exist_ok=True)

    # TalentTab.dbc: stock rows untouched, all classes' new tab rows appended
    # (no ordering constraint discovered for TalentTab.dbc itself -- only
    # Talent.dbc's per-tab contiguity mattered). String block includes every
    # class's newly interned Name_lang/BackgroundFile text.
    merged_tabs = DbcFile(
        schema=wotlk_tabs.schema, locale_count=wotlk_tabs.locale_count,
        rows=list(wotlk_tabs.rows) + all_new_tab_rows, string_block=tab_string_builder.build(),
    )
    out_tabs_path = args.out_dbc_dir / "TalentTab.dbc"
    write_dbc(out_tabs_path, merged_tabs)
    print(f"\nwrote {out_tabs_path}: {len(merged_tabs.rows)} rows "
          f"({len(wotlk_tabs.rows)} stock + {len(all_new_tab_rows)} new)")

    # Talent.dbc: stock rows untouched, each class/era's new tab's rows
    # inserted as one whole contiguous block (order within each block
    # already correct; different blocks don't interact with each other).
    merged_talent_rows = list(wotlk_talents.rows) + all_new_talent_rows
    merged_talents = DbcFile(
        schema=wotlk_talents.schema, locale_count=wotlk_talents.locale_count,
        rows=merged_talent_rows, string_block=wotlk_talents.string_block,
    )
    out_talents_path = args.out_dbc_dir / "Talent.dbc"
    write_dbc(out_talents_path, merged_talents)
    print(f"wrote {out_talents_path}: {len(merged_talents.rows)} rows "
          f"({len(wotlk_talents.rows)} stock + {len(all_new_talent_rows)} new)")

    # Verify the same ordering invariant merge_talents.py checks.
    reread = read_dbc(out_talents_path, merged_talents.schema, merged_talents.locale_count)
    for tab in {r["TabID"] for r in all_new_talent_rows}:
        keys = [(r["TierID"], r["ColumnIndex"]) for r in reread.rows if r["TabID"] == tab]
        assert keys == sorted(keys), f"new tab {tab}'s rows are not sorted by (tier, column)"
        indices = [i for i, r in enumerate(reread.rows) if r["TabID"] == tab]
        assert indices == list(range(indices[0], indices[0] + len(indices))), f"new tab {tab} not contiguous"
    print("verified: every new tab is a contiguous, (tier,column)-sorted block")

    args.out_mapping_dir.mkdir(parents=True, exist_ok=True)
    for class_slug, by_era in per_class.items():
        out_mapping_path = args.out_mapping_dir / f"{class_slug}-mapping.csv"
        with open(out_mapping_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["era", "classic_talent_id", "server_talent_id", "classic_tab_id", "server_tab_id"])
            for era, result in by_era.items():
                tab_by_talent = {r["ID"]: r["TabID"] for r in result["new_talent_rows"]}
                reverse_tab_map = {v: k for k, v in result["tab_id_map"].items()}
                id_offset = ERA_CONFIG[era]["id_offset"]
                for row in result["new_talent_rows"]:
                    server_id = row["ID"]
                    classic_id = server_id - id_offset
                    server_tab = tab_by_talent[server_id]
                    classic_tab = reverse_tab_map[server_tab]
                    w.writerow([ERA_CONFIG[era]["label"], classic_id, server_id, classic_tab, server_tab])
        print(f"wrote {out_mapping_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

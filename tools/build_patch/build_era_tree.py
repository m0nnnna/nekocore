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
  - A talent is only included if every rank's spell id already exists in
    WotLK's Spell.dbc (skipped transitively otherwise) -- porting the
    missing spells into Spell.dbc is real, separate follow-on work.
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

CLASSES = {
    "warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5,
    "shaman": 7, "mage": 8, "warlock": 9, "druid": 11,
}
CLASS_MASKS = {slug: 1 << (cid - 1) for slug, cid in CLASSES.items()}

# Fixed processing order -- controls tab INDEX stability (see module doc
# comment). "root_arg" is the argparse dest holding that era's client root.
#
# tab_base ordering is NOT cosmetic: live-confirmed (NekoTalentDebug /ntd,
# two different classes) that LearnTalent()'s internal tabIndex resolution
# walks a class's TalentTab.dbc rows in ID-ASCENDING order, while
# GetTalentTabInfo()/GetNumTalentTabs() report them in the order this
# script actually WRITES them (stock, then Vanilla, then TBC). Vanilla's
# tab_base used to be 9000 and TBC's 8000 -- numerically backwards from
# write order -- so clicking what the UI displayed as the 4th tab
# (Vanilla, id 9090) actually sent the id-ascending 4th tab instead (TBC,
# id 8090): a full swap of the Vanilla and TBC blocks, reproduced exactly
# on both a Rogue and a Warlock. Keeping tab_base numerically increasing
# in the SAME order eras are written here (stock ids < 8000 < 9000) makes
# both resolutions agree. If a third era is ever added, its tab_base must
# sort above whichever era is written last, for the same reason.
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
    wotlk_class_racemask: dict[str, int],
    tab_string_builder: StringBlockBuilder,
    locale_count: int,
    mapping: dict[int, int],
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
        new_tab_row["OrderIndex"] = tree_index
        new_tab_row["BackgroundFile"] = new_string_field(tab_string_builder, tab["BackgroundFile"]["value"])
        new_tab_rows.append(new_tab_row)

        tab_talents = sorted(
            (row for row in src_talents.rows if row["TabID"] == old_tab_id),
            key=lambda r: (r["TierID"], r["ColumnIndex"]),
        )

        unsafe_ids: set[int] = set()
        included: list[dict] = []
        for row in tab_talents:
            rid = row["ID"]
            row_ranks = ranks_of(row)
            missing = [s for s in row_ranks if s != 0 and s not in wotlk_spell_ids]
            if missing:
                print(f"  {rid} SKIPPED: rank spell(s) {missing} do not exist in WotLK's Spell.dbc")
                unsafe_ids.add(rid)
                continue
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
            for f in [f"SpellRank_{i}" for i in range(9)]:
                new_row[f] = row[f]
            depends_on = row["PrereqTalent_0"]
            if depends_on:
                translated = mapping.get(depends_on)
                if translated is None:
                    raise RuntimeError(f"talent {rid} depends on {depends_on}, not included")
                new_row["PrereqTalent_0"] = translated
                new_row["PrereqRank_0"] = row["PrereqRank_0"]
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
        wotlk_spell = load("3.3.5a", "Spell.dbc", args.wotlk_root, tmp_dir)
        wotlk_tabs = load("3.3.5a", "TalentTab.dbc", args.wotlk_root, tmp_dir)
        era_src = {
            era: (load(era, "Talent.dbc", era_roots[era], tmp_dir), load(era, "TalentTab.dbc", era_roots[era], tmp_dir))
            for era in active_eras
        }

    wotlk_spell_ids = {row["ID"] for row in wotlk_spell.rows}
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
                wotlk_class_racemask=wotlk_class_racemask,
                tab_string_builder=tab_string_builder, locale_count=wotlk_tabs.locale_count,
                mapping=mapping,
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

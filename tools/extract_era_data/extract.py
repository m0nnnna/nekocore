"""
Phase 1 tool: extract per-class talent tree data -- tree shape (Talent.dbc/
TalentTab.dbc) AND full spell effect data (Spell.dbc) for every spell rank
referenced -- from a source client install (Vanilla 1.12.1 or TBC 2.4.3)
into intermediate JSON under data/<era>/<class>.json.

Usage:
    python extract.py --build 2.4.3 --client-root "D:\\Games\\World of Warcraft 2.4.3" \\
        --class warrior --out-root ../../data

Reads directly out of the client's MPQ archives via mpq_source.resolve(),
which picks the copy of each DBC the running client actually loads (patches
override base archives) -- no manual MPQ extraction step needed. The user
must point --client-root at their own legitimately-owned client install --
this repo does not ship or download any Blizzard game data.

--dbc-dir is also accepted as an alternative to --client-root, for an
already-extracted DBFilesClient folder.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dbc"))
from wdbc import LOCALE_COUNT, read_dbc  # noqa: E402
from schemas import (  # noqa: E402
    BUILD_SCHEMAS,
    PREREQ_RANK_FIELDS,
    PREREQ_TALENT_FIELDS,
    SPELL_RANK_FIELDS,
)
import mpq_source  # noqa: E402

N_EFFECTS = 3
EFFECT_SLOT_FIELDS = [
    "Effect", "EffectBasePoints", "EffectDieSides", "EffectRealPointsPerLevel",
    "EffectMechanic", "ImplicitTargetA", "ImplicitTargetB", "EffectRadiusIndex",
    "EffectAura", "EffectAuraPeriod", "EffectAmplitude", "EffectChainTargets",
    "EffectItemType", "EffectMiscValue", "EffectMiscValueB", "EffectTriggerSpell",
    "EffectPointsPerCombo",
]

# WoW classID -> (slug, display name, classMask bit). Death Knight (6) is
# WotLK-only and intentionally excluded from era extraction targets since
# Vanilla/TBC clients have no DK class data to extract.
CLASSES = {
    "warrior": (1, "Warrior"),
    "paladin": (2, "Paladin"),
    "hunter": (3, "Hunter"),
    "rogue": (4, "Rogue"),
    "priest": (5, "Priest"),
    "shaman": (7, "Shaman"),
    "mage": (8, "Mage"),
    "warlock": (9, "Warlock"),
    "druid": (11, "Druid"),
}

BUILD_TO_ERA_DIR = {
    "1.12.1": "vanilla",
    "2.4.3": "tbc",
}


def class_mask(class_id: int) -> int:
    return 1 << (class_id - 1)


def project_spell(row: dict, icon_by_id: dict[int, str]) -> dict:
    """Curated subset of a Spell.dbc row: enough to port the effect (what it
    actually does) plus enough metadata (cooldown, cost, range, proc info) to
    reconstruct behavior server-side. Raw Attributes* bitmasks are kept as
    hex strings since Phase 1's SpellScript porting work will need them, but
    aren't decoded here (attribute bit meanings are build-specific and this
    is a data-extraction tool, not a spell-semantics one)."""
    effects = []
    for i in range(N_EFFECTS):
        eff = {f: row[f"{f}_{i}"] for f in EFFECT_SLOT_FIELDS}
        if eff["Effect"] == 0:
            continue
        eff["slot"] = i
        effects.append(eff)

    attributes_hex = {
        name: f"{row[name]:#010x}"
        for name in row
        if name.startswith("Attributes") and isinstance(row[name], int)
    }

    return {
        "id": row["ID"],
        "name": row["Name_lang"]["enUS"],
        "icon": icon_by_id.get(row["SpellIconID"]),
        "school_mask": row["SchoolMask"],
        "dispel_type": row["DispelType"],
        "mechanic": row["Mechanic"],
        "attributes": attributes_hex,
        "casting_time_index": row["CastingTimeIndex"],
        "recovery_time_ms": row["RecoveryTime"],
        "category_recovery_time_ms": row["CategoryRecoveryTime"],
        "range_index": row["RangeIndex"],
        "duration_index": row["DurationIndex"],
        "power_type": row["PowerType"],
        "mana_cost": row["ManaCost"],
        "mana_cost_pct": row["ManaCostPct"],
        "proc_type_mask": row["ProcTypeMask"],
        "proc_chance": row["ProcChance"],
        "proc_charges": row["ProcCharges"],
        "stance_bar_order": row["StanceBarOrder"],
        "effects": effects,
    }


def load_dbc(build: str, filename: str, *, client_root: Path | None, dbc_dir: Path | None, tmp_dir: Path):
    schema = BUILD_SCHEMAS[build][filename]
    if client_root is not None:
        archive, data = mpq_source.resolve(client_root, filename)
        path = tmp_dir / filename
        path.write_bytes(data)
        print(f"  {filename}: resolved from {archive}", file=sys.stderr)
    else:
        path = dbc_dir / filename
    return read_dbc(path, schema, LOCALE_COUNT[build])


def extract_class(build: str, class_slug: str, *, client_root: Path | None, dbc_dir: Path | None) -> dict:
    class_id, class_name = CLASSES[class_slug]
    mask = class_mask(class_id)

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        talent_tab = load_dbc(build, "TalentTab.dbc", client_root=client_root, dbc_dir=dbc_dir, tmp_dir=tmp_dir)
        talent = load_dbc(build, "Talent.dbc", client_root=client_root, dbc_dir=dbc_dir, tmp_dir=tmp_dir)
        spell_icon = load_dbc(build, "SpellIcon.dbc", client_root=client_root, dbc_dir=dbc_dir, tmp_dir=tmp_dir)
        spell = None
        if "Spell.dbc" in BUILD_SCHEMAS[build]:
            spell = load_dbc(build, "Spell.dbc", client_root=client_root, dbc_dir=dbc_dir, tmp_dir=tmp_dir)

    icon_by_id = {row["ID"]: row["TextureFilename"]["value"] for row in spell_icon.rows}
    spell_by_id = {row["ID"]: row for row in spell.rows} if spell is not None else {}

    tabs = [row for row in talent_tab.rows if row["ClassMask"] & mask]
    tab_ids = {row["ID"] for row in tabs}
    referenced_spell_ids: set[int] = set()

    out_tabs = []
    for tab in sorted(tabs, key=lambda r: r["OrderIndex"]):
        tab_talents = [t for t in talent.rows if t["TabID"] == tab["ID"]]
        out_talents = []
        for t in sorted(tab_talents, key=lambda r: (r["TierID"], r["ColumnIndex"])):
            ranks = [t[f] for f in SPELL_RANK_FIELDS if t[f] != 0]
            prereq_talent = [t[f] for f in PREREQ_TALENT_FIELDS if t[f] != 0]
            prereq_rank = [t[f] for f in PREREQ_RANK_FIELDS if t[f] != 0]
            referenced_spell_ids.update(ranks)
            if t["RequiredSpellID"]:
                referenced_spell_ids.add(t["RequiredSpellID"])
            out_talents.append(
                {
                    "id": t["ID"],
                    "tier": t["TierID"],
                    "column": t["ColumnIndex"],
                    "spell_ranks": ranks,
                    "prereq_talent_ids": prereq_talent,
                    "prereq_ranks": prereq_rank,
                    "flags": t["Flags"],
                    "required_spell_id": t["RequiredSpellID"] or None,
                }
            )
        out_tabs.append(
            {
                "id": tab["ID"],
                "name": tab["Name_lang"]["enUS"],
                "order_index": tab["OrderIndex"],
                "icon": icon_by_id.get(tab["SpellIconID"]),
                "background_file": tab["BackgroundFile"]["value"],
                "talents": out_talents,
            }
        )

    spells_out = {}
    missing_spell_ids = []
    for spell_id in sorted(referenced_spell_ids):
        row = spell_by_id.get(spell_id)
        if row is None:
            missing_spell_ids.append(spell_id)
            continue
        spells_out[str(spell_id)] = project_spell(row, icon_by_id)
    if missing_spell_ids:
        print(
            f"  WARNING: {len(missing_spell_ids)} spell id(s) referenced by "
            f"{class_name} talents not found in Spell.dbc: {missing_spell_ids}",
            file=sys.stderr,
        )

    return {
        "build": build,
        "class_id": class_id,
        "class_name": class_name,
        "tabs": out_tabs,
        "spells": spells_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", required=True, choices=sorted(BUILD_TO_ERA_DIR))
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--client-root", type=Path, help="WoW install folder (contains Data/)")
    src.add_argument("--dbc-dir", type=Path, help="already-extracted DBFilesClient folder")
    ap.add_argument(
        "--class",
        dest="classes",
        action="append",
        choices=sorted(CLASSES),
        required=True,
        help="repeatable; class slug(s) to extract",
    )
    ap.add_argument("--out-root", default=Path(__file__).resolve().parent.parent.parent / "data", type=Path)
    args = ap.parse_args()

    era_dir = args.out_root / BUILD_TO_ERA_DIR[args.build]
    era_dir.mkdir(parents=True, exist_ok=True)

    for class_slug in args.classes:
        data = extract_class(args.build, class_slug, client_root=args.client_root, dbc_dir=args.dbc_dir)
        out_path = era_dir / f"{class_slug}.json"
        out_path.write_text(json.dumps(data, indent=2))
        n_talents = sum(len(t["talents"]) for t in data["tabs"])
        print(f"wrote {out_path} ({len(data['tabs'])} tabs, {n_talents} talents)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Ports the rank spells that era talents need but WotLK no longer has from the
TBC 2.4.3 client's Spell.dbc into a WotLK 3.3.5a Spell.dbc.

Why: build_era_tree.py can only emit a talent rank whose spell id exists in
the WotLK Spell.dbc the realm and client load -- Player::LearnTalent no-ops
on an unknown spell, and the client can't even show a tooltip for it. WotLK
deleted a lot of Classic/TBC talent spells outright (Humanoid Slaying,
Improved Wing Clip, Siphon Life's passive, most rank 4-5s of talents it
squashed to 3 ranks...). Without them some era tabs are structurally
unspendable: Vanilla Survival's tier 0 had 3 points available against the
5 needed to open tier 1.

Source: the 2.4.3 client. Almost every Vanilla talent survived into TBC with
the SAME spell ids (the cull happened in WotLK), so one TBC->WotLK field
mapping covers both eras' gaps. Spells that were already gone by 2.4.3
(a few dozen Vanilla-only ones) are reported and left out; porting those
needs a 1.12.1 Spell.dbc schema this repo doesn't have yet.

TBC -> WotLK layout (tools/dbc/schemas.py has both): same-named fields copy
across; ShapeshiftMask/ShapeshiftExclude widen to [2]; SpellClassMask widens
to [3]; the per-effect spellmod mask moves from EffectItemType[i] into
EffectSpellClassMask{A,B,C}[0] (WotLK's 96-bit family mask, first word) for
SPELL_AURA_ADD_FLAT/PCT_MODIFIER effects; CastUI/EffectBaseDice/
EffectDicePerLevel are dropped; every new WotLK-only field is 0. Strings
are re-interned into the output string block (source offsets are meaningless
against a different file).

Caveat, deliberately not hidden: WotLK reassigned some SpellFamilyFlags bits,
so a ported spellmod talent ("Improved <spell> by X%") may miss the spell it
should modify if that spell's family bit moved between 2.4.3 and 3.3.5a. The
port is byte-faithful to the TBC data; auditing masks against WotLK's
families is a follow-on per talent, not something this tool guesses at.

Output is sorted by ID (stock Spell.dbc is). Rows already present in the
base file are never touched -- this only adds.

Usage:
    python port_era_spells.py --wotlk-root "D:\\...\\3.3.5a" --tbc-root "D:\\...\\2.4.3" \\
        --vanilla-root "D:\\...\\1.12.1" \\
        --base-spell client-patch/progression-optional/Spell.dbc \\
        --out data/generated/Spell.dbc
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dbc"))
from wdbc import DbcFile, LOCALE_COUNT, StringBlockBuilder, new_loc_string, read_dbc, write_dbc  # noqa: E402
from schemas import BUILD_SCHEMAS  # noqa: E402
import mpq_source  # noqa: E402

SPELL_AURA_ADD_FLAT_MODIFIER = 107
SPELL_AURA_ADD_PCT_MODIFIER = 108
SPELLMOD_AURAS = {SPELL_AURA_ADD_FLAT_MODIFIER, SPELL_AURA_ADD_PCT_MODIFIER}
EFFECT_MASK_FIELDS = ["EffectSpellClassMaskA", "EffectSpellClassMaskB", "EffectSpellClassMaskC"]


def load_from_client(build: str, filename: str, root: Path, tmp_dir: Path):
    schema = BUILD_SCHEMAS[build][filename]
    archive, data = mpq_source.resolve(root, filename)
    print(f"  {build} {filename}: resolved from {archive}", file=sys.stderr)
    path = tmp_dir / f"{build}-{filename}"
    path.write_bytes(data)
    return read_dbc(path, schema, LOCALE_COUNT[build])


def talent_rank_spells(talents) -> set[int]:
    ids: set[int] = set()
    for row in talents.rows:
        for i in range(9):
            s = row[f"SpellRank_{i}"]
            if s:
                ids.add(s)
    return ids


def convert_row(src: dict, wotlk_schema, builder: StringBlockBuilder, locale_count: int) -> dict:
    out: dict = {}
    for f in wotlk_schema:
        if f.type == "loc_string":
            text = src[f.name]["enUS"] if f.name in src else ""
            out[f.name] = new_loc_string(builder, text, locale_count)
        elif f.name in src:
            out[f.name] = src[f.name]
        else:
            out[f.name] = 0.0 if f.type == "float32" else 0
    out["ShapeshiftMask_0"] = src["ShapeshiftMask"]
    out["ShapeshiftExclude_0"] = src["ShapeshiftExclude"]
    # SpellClassMask_0/_1 copied by name above; _2 stays 0.
    for i in range(3):
        if src[f"EffectAura_{i}"] in SPELLMOD_AURAS:
            out[f"{EFFECT_MASK_FIELDS[i]}_0"] = src[f"EffectItemType_{i}"]
            out[f"EffectItemType_{i}"] = 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="3.3.5a client (stock Spell.dbc fallback + Talent.dbc)")
    ap.add_argument("--tbc-root", required=True, type=Path, help="2.4.3 client -- the source of the ported rows")
    ap.add_argument("--vanilla-root", type=Path, help="1.12.1 client -- include Vanilla talents' missing spells too")
    ap.add_argument("--base-spell", type=Path,
                    help="WotLK Spell.dbc to build on (default: mod-individual-progression's staged copy if present, else the stock client's)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if args.base_spell and args.base_spell.exists():
            base = read_dbc(args.base_spell, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"], LOCALE_COUNT["3.3.5a"])
            print(f"  base Spell.dbc: {args.base_spell} ({len(base.rows)} rows)", file=sys.stderr)
        else:
            base = load_from_client("3.3.5a", "Spell.dbc", args.wotlk_root, tmp)
        tbc_spell = load_from_client("2.4.3", "Spell.dbc", args.tbc_root, tmp)
        needed: set[int] = talent_rank_spells(load_from_client("2.4.3", "Talent.dbc", args.tbc_root, tmp))
        if args.vanilla_root:
            needed |= talent_rank_spells(load_from_client("1.12.1", "Talent.dbc", args.vanilla_root, tmp))

    have = {r["ID"] for r in base.rows}
    tbc_by_id = {r["ID"]: r for r in tbc_spell.rows}
    missing = sorted(s for s in needed if s not in have)
    portable = [s for s in missing if s in tbc_by_id]
    unportable = [s for s in missing if s not in tbc_by_id]

    builder = StringBlockBuilder(base.string_block)
    wotlk_schema = BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"]
    new_rows = [convert_row(tbc_by_id[s], wotlk_schema, builder, base.locale_count) for s in portable]
    for r in new_rows:
        print(f"  + {r['ID']} {r['Name_lang']['enUS']}")

    rows = sorted(base.rows + new_rows, key=lambda r: r["ID"])
    out = DbcFile(schema=wotlk_schema, locale_count=base.locale_count, rows=rows, string_block=builder.build())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_dbc(args.out, out)

    print(f"\nwrote {args.out}: {len(rows)} rows ({len(base.rows)} base + {len(new_rows)} ported from 2.4.3)")
    if unportable:
        print(f"{len(unportable)} talent rank spells are missing from BOTH WotLK and 2.4.3 (Vanilla-only, not ported): "
              + ", ".join(map(str, unportable)))

    reread = read_dbc(args.out, wotlk_schema, out.locale_count)
    assert [r["ID"] for r in reread.rows] == [r["ID"] for r in rows]
    for s in portable:
        assert reread.rows[[r["ID"] for r in rows].index(s)]["Name_lang"]["enUS"] == tbc_by_id[s]["Name_lang"]["enUS"]
    print("verified: output re-reads with the ported rows' ids and names intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

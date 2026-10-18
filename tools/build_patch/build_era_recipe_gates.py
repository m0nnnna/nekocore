"""
Works out which profession recipe spells a Vanilla or TBC character must not
be able to learn, because their era's client did not have them.

Nothing stopped a Vanilla character buying 63746 "Enchant Boots - Lesser
Accuracy" (WotLK 3.1) from an enchanting trainer: the trainer lists are the
WotLK ones and profession spells have no era copy to swap to (EraSpellGate.cpp
only substitutes class spells). Recipe spell ids are stable across versions,
so the test is simply: is the id a row in the era client's Spell.dbc?

  * not in the 1.12.1 Spell.dbc -> not for Vanilla characters
  * not in the 2.4.3  Spell.dbc -> not for Vanilla or TBC characters

Candidates (the WotLK ids; era copies >= 300000 are never candidates):
  * every trainer_spell row of a profession trainer (trainer.Type = 2) with
    ReqSkillLine != 0 -- real recipes and ranks, not weapon skills;
  * riding (skill 762) rows of any trainer: riding is taught by Type 1 mount
    trainers, and Artisan/Master/Cold Weather Flying post-date their eras;
  * automatic profession grants: SkillLineAbility rows (stock 3.3.5a client)
    on a profession skill line with AcquireMethod 1 ("learned on skill gain"):
    Master Blacksmith, Toughness, Lifeblood... These bypass trainers entirely;
    EraSpellSync strips them at login.

Output: src/EraRecipeGates.generated.h, two sorted constexpr arrays and a
lookup, included by EraSpells.h.

Usage (venv with mpyq; run with -I):
    /tmp/nkvenv/bin/python -I tools/build_patch/build_era_recipe_gates.py \\
        --wotlk-root ".../World of Warcraft 3.3.5a" \\
        --vanilla-root ".../World of Warcraft 1.12.1" \\
        --tbc-root ".../World of Warcraft 2.4.3" --container nkdb
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dbc"))
from wdbc import LOCALE_COUNT, read_dbc  # noqa: E402
from schemas import BUILD_SCHEMAS  # noqa: E402
import mpq_source  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERA_COPY_MIN = 300_000
SKILL_RIDING = 762
ACQUIRE_ON_SKILL_GAIN = 1
# First Aid, Blacksmithing, Leatherworking, Alchemy, Herbalism, Cooking,
# Mining, Tailoring, Engineering, Enchanting, Fishing, Skinning,
# Jewelcrafting, Inscription (+ Poisons 40 is rogue-only, not a profession).
PROFESSION_SKILL_LINES = (129, 164, 165, 171, 182, 185, 186, 197, 202, 333, 356, 393, 755, 773)


def mysql(sql: str, container: str, password: str) -> list[list[str]]:
    cmd = ["docker", "exec", container, "mysql", f"-p{password}", "-B", "-N", "acore_world", "-e", sql]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"mysql failed: {out.stderr.strip()}")
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def load(build: str, filename: str, root: Path, tmp: Path):
    archive, data = mpq_source.resolve(root, filename)
    print(f"  {build} {filename}: resolved from {archive}", file=sys.stderr)
    path = tmp / f"{build}-{filename}"
    path.write_bytes(data)
    return read_dbc(path, BUILD_SCHEMAS[build][filename], LOCALE_COUNT[build])


def array(name: str, ids: list[int]) -> list[str]:
    lines = [f"    constexpr uint32 {name}[] = {{"]
    for i in range(0, len(ids), 10):
        lines.append("        " + ", ".join(str(x) for x in ids[i:i + 10]) + ",")
    lines.append("    };")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path)
    ap.add_argument("--vanilla-root", required=True, type=Path)
    ap.add_argument("--tbc-root", required=True, type=Path)
    ap.add_argument("--container", default="nkdb")
    ap.add_argument("--password", default="nk")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "src" / "EraRecipeGates.generated.h")
    args = ap.parse_args()

    candidates: dict[int, str] = {}
    for spell, why in mysql(
            "select distinct ts.SpellId, 'trainer' from trainer_spell ts join trainer t on t.Id = ts.TrainerId "
            f"where t.Type = 2 and ts.ReqSkillLine != 0 and ts.SpellId < {ERA_COPY_MIN} "
            f"union select distinct SpellId, 'riding' from trainer_spell where ReqSkillLine = {SKILL_RIDING} "
            f"and SpellId < {ERA_COPY_MIN};", args.container, args.password):
        candidates[int(spell)] = why

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        sla = load("3.3.5a", "SkillLineAbility.dbc", args.wotlk_root, tmp)
        for row in sla.rows:
            if row["SkillLine"] in PROFESSION_SKILL_LINES and row["AcquireMethod"] == ACQUIRE_ON_SKILL_GAIN \
                    and row["Spell"] < ERA_COPY_MIN:
                candidates.setdefault(row["Spell"], "auto-grant")
        vanilla = {r["ID"] for r in load("1.12.1", "Spell.dbc", args.vanilla_root, tmp).rows}
        tbc = {r["ID"] for r in load("2.4.3", "Spell.dbc", args.tbc_root, tmp).rows}

    # A spell TBC lacks is also missing from Vanilla in practice, but the rule
    # is stated per client, so the Vanilla list is the union.
    not_tbc = sorted(s for s in candidates if s not in tbc)
    not_vanilla = sorted(s for s in candidates if s not in vanilla or s in set(not_tbc))
    by_kind: dict[str, int] = {}
    for s in not_vanilla:
        by_kind[candidates[s]] = by_kind.get(candidates[s], 0) + 1
    print(f"candidates {len(candidates)}; Vanilla-gated {len(not_vanilla)} {by_kind}; TBC-gated {len(not_tbc)}",
          file=sys.stderr)

    out = [
        "/*",
        " * Profession recipes, ranks and perks missing from an era's client Spell.dbc.",
        " * GENERATED by tools/build_patch/build_era_recipe_gates.py -- do not edit.",
        " *",
        f" * {len(not_vanilla)} spells absent from 1.12.1 (hidden from / refused to Vanilla characters),",
        f" * {len(not_tbc)} absent from 2.4.3 (the same for TBC characters; a subset of the above).",
        " */",
        "#pragma once",
        "",
        "#include \"Define.h\"",
        "",
        "#include <algorithm>",
        "#include <iterator>",
        "",
        "namespace NekoEraSpells",
        "{",
        "    namespace RecipeGates",
        "    {",
    ]
    out += ["    " + l for l in array("NOT_IN_VANILLA", not_vanilla)]
    out.append("")
    out += ["    " + l for l in array("NOT_IN_TBC", not_tbc)]
    out += [
        "    }",
        "",
        "    /// Sorted-array lookup; true when the era's client had no such spell.",
        "    /// `eraIsVanilla` false means TBC.",
        "    inline bool IsRecipeMissingInEra(uint32 spellId, bool eraIsVanilla)",
        "    {",
        "        if (eraIsVanilla)",
        "            return std::binary_search(std::begin(RecipeGates::NOT_IN_VANILLA), std::end(RecipeGates::NOT_IN_VANILLA), spellId);",
        "        return std::binary_search(std::begin(RecipeGates::NOT_IN_TBC), std::end(RecipeGates::NOT_IN_TBC), spellId);",
        "    }",
        "}",
        "",
    ]
    args.out.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

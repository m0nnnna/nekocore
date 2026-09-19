"""
Builds the merged DBC set that the third-party mods need, one output file per
DBC that more than one party wants to edit, into data/generated/dbc/.

Every output = stock 3.3.5a file (the untouched copies under
server/env/dist/data/dbc -- the docker bind mounts overlay individual files
on top of that directory, they never rewrite it) + each mod's rows layered
on with tools/dbc/layer_merge.py. Who contributes what:

  CharBaseInfo        mod-uac (38 new race/class pairs), Prestige (5 pairs, all
                      but one already in uac's set)
  SkillRaceClassInfo  mod-individual-progression optional/ (1 row), mod-uac
                      (627 rows, per-race class skills for the new combos),
                      Prestige (41 rows: every class skill line opened to every
                      race/class so drafted spells can be used)
  CharStartOutfit     mod-uac (74 starter-gear rows for the new combos)
  CharTitles          Prestige (12 prestige-rank titles)
  Map, MapDifficulty, AreaTable, WorldSafelocs, LoadingScreens, ZoneMusic,
  SoundEntries, CreatureDisplayInfo, CreatureModelData
                      Delves (13 custom maps; shipped as WDBX CSV row lists)

Deliberate deviation from Prestige's install notes: its SkillRaceClassInfo.dbc
also rewrites the race/class masks of every one of the 241 stock rows to -1.
We only take its 41 *added* rows -- those already carry -1/-1 masks with the
class-skill flag, which is what Draft Mode needs -- because the wholesale
rewrite would undo mod-uac's per-race rows and progression's era gating. If
a drafted spell ever turns out unusable, revisit with policy="override".

mod-uac's rows come out of its own client MPQ (client-patch/<variant>/
patch-z.mpq) rather than its SQL because the client needs the DBC form
anyway and the server-side `*_dbc` tables mod-uac installs carry identical
data (AzerothCore lets DB rows override DBC rows, so both being present is
harmless -- DBCDatabaseLoader.cpp).

Usage:
    python tools/build_patch/build_mod_dbcs.py [--uac-variant standard|enhanced]
Run tools/third_party/fetch.py first. Then docker-compose.override.yml mounts
these over the server's data/dbc and install_client.py packs them into
patch-Z.mpq.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "dbc"))
from layer_merge import Merger  # noqa: E402

import mpyq  # noqa: E402

STOCK_DIR = REPO_ROOT / "server" / "env" / "dist" / "data" / "dbc"
OUT_DIR = REPO_ROOT / "data" / "generated" / "dbc"
THIRD_PARTY = REPO_ROOT / "third-party"
UAC_ROOT = REPO_ROOT / "server" / "modules" / "mod-uac"
PRESTIGE_DBC = THIRD_PARTY / "Prestige-and-Draft-Mode" / "Sql & Serverside Files" / "DBC"
DELVES_CSV = THIRD_PARTY / "Delves" / "DBC_CSV" / "DBFilesClient"
PROGRESSION_STAGE = REPO_ROOT / "client-patch" / "progression-optional"

DELVES_FILES = [
    "Map", "MapDifficulty", "AreaTable", "WorldSafelocs", "LoadingScreens",
    "ZoneMusic", "SoundEntries", "CreatureDisplayInfo", "CreatureModelData",
]


def uac_dbc(variant: str, name: str, tmp_dir: Path) -> Path:
    mpq = UAC_ROOT / "client-patch" / variant / "patch-z.mpq"
    if not mpq.exists():
        raise SystemExit(f"{mpq} missing -- run tools/third_party/fetch.py")
    data = mpyq.MPQArchive(str(mpq)).read_file(f"DBFilesClient\\{name}")
    if data is None:
        raise SystemExit(f"{mpq} has no {name}")
    out = tmp_dir / name
    out.write_bytes(data)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uac-variant", choices=["standard", "enhanced"], default="standard",
                    help="mod-uac client patch flavour: standard = stock client, enhanced = HD client (default standard)")
    args = ap.parse_args()

    for p in (STOCK_DIR, PRESTIGE_DBC, DELVES_CSV, UAC_ROOT):
        if not p.is_dir():
            raise SystemExit(f"missing {p}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_DIR / ".uac-extract"
    tmp.mkdir(exist_ok=True)

    def stock(name: str) -> Path:
        p = STOCK_DIR / f"{name}.dbc"
        if not p.exists():
            raise SystemExit(f"stock {p} missing")
        return p

    merges: list[Merger] = []

    m = Merger(stock("CharBaseInfo"))
    m.layer_dbc("mod-uac", uac_dbc(args.uac_variant, "CharBaseInfo.dbc", tmp))
    m.layer_dbc("prestige", PRESTIGE_DBC / "CharBaseInfo.dbc")
    merges.append(m)

    m = Merger(stock("SkillRaceClassInfo"))
    if (PROGRESSION_STAGE / "SkillRaceClassInfo.dbc").exists():
        m.layer_dbc("individual-progression", PROGRESSION_STAGE / "SkillRaceClassInfo.dbc")
    else:
        print("note: no staged progression SkillRaceClassInfo.dbc (install_client.py "
              "--progression-module-root stages it); merging without it")
    m.layer_dbc("mod-uac", uac_dbc(args.uac_variant, "SkillRaceClassInfo.dbc", tmp))
    m.layer_dbc("prestige", PRESTIGE_DBC / "SkillRaceClassInfo.dbc")  # add-only, see module docstring
    merges.append(m)

    m = Merger(stock("CharStartOutfit"))
    m.layer_dbc("mod-uac", uac_dbc(args.uac_variant, "CharStartOutfit.dbc", tmp))
    merges.append(m)

    m = Merger(stock("CharTitles"))
    m.layer_dbc("prestige", PRESTIGE_DBC / "CharTitles.dbc")
    merges.append(m)

    for name in DELVES_FILES:
        m = Merger(stock(name))
        m.layer_csv("delves", DELVES_CSV / f"{name}.csv")
        merges.append(m)

    for m in merges:
        out = OUT_DIR / m.base_path.name
        m.write(out)
        print(m.summary())
        print(f"  -> {out}")

    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Patches a stock retail 3.3.5a client install with nekocore's era-talent
content -- the single command that replaces the manual steps this repo's
own testing has been done with by hand all session (build the DBCs,
package them into an MPQ, drop it in Data\\, copy the addons into
Interface\\AddOns\\).

Two pieces of client-side content, two different delivery mechanisms
(the client itself draws this distinction, not us):
  - The custom Talent.dbc/TalentTab.dbc data only loads from inside an MPQ
    archive under the client's Data\\ folder -- loose DBCs on disk are
    never read.
  - Addon Lua/.toc files only load as LOOSE files under
    Interface\\AddOns\\ -- an addon placed inside an MPQ is invisible to
    the client.

Nothing this script writes into the client install is ever committed to
this repo (see .gitignore: *.dbc, *.mpq) -- both the DBCs and the MPQ that
wraps them are derived from Blizzard's own client data, not ours to
distribute. Each user runs this script themselves, against their own
legally-owned client copy, the same way open-wow-client's tooling expects.

Usage:
    # Full rebuild, both eras (needs your own 1.12.1 and/or 2.4.3 clients
    # for source talent data -- pass whichever era roots you want in the
    # output; omitting one drops that era from this run's output, same as
    # build_era_tree.py itself)
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" \\
        --vanilla-root "D:\\...\\1.12.1" --tbc-root "D:\\...\\2.4.3" --build

    # Redeploy already-built data/generated/*.dbc + the addons, no rebuild
    python install_client.py --wotlk-root "D:\\...\\3.3.5a"

    # Addons only (fast path for iterating on Lua without touching DBCs)
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" --addons-only

    # Also fold in mod-individual-progression's optional Spell.dbc/skill DBCs
    # (needs 7z on PATH; --progression-variant V|S picks the mana-cost variant)
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" \\
        --progression-module-root "D:\\AzerothCore\\modules\\mod-individual-progression"

    # Additionally write a zip of just the patch (patch-Z.mpq + addons) that
    # an existing player extracts over their client folder
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" --bundle-zip website/downloads/nekocore-patch.zip

Third-party mods (tools/third_party/fetch.py) ride along automatically when
present -- the merged DBCs from build_mod_dbcs.py (mod-uac race/class
unlocks, Prestige titles) and the PrestigeSystem addon. One MPQ + one AddOns
folder is the whole client install; the mods' own patch-P.mpq / patch-z.mpq are NOT used
(their DBCs are merged into ours instead, they'd otherwise fight each other
over CharBaseInfo).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "mpq"))
from mpq_writer import write_archive  # noqa: E402

ALL_CLASSES = [
    "warrior", "paladin", "hunter", "rogue", "priest",
    "shaman", "mage", "warlock", "druid",
]

GENERATED_DIR = REPO_ROOT / "data" / "generated"
STAGED_MPQ = REPO_ROOT / "client-patch" / "patch-nekocore-talents.mpq"
ADDONS_DIR = REPO_ROOT / "client-patch" / "Interface" / "AddOns"
PROGRESSION_STAGE_DIR = REPO_ROOT / "client-patch" / "progression-optional"
MOD_DBC_DIR = REPO_ROOT / "data" / "generated" / "dbc"  # build_mod_dbcs.py output
THIRD_PARTY = REPO_ROOT / "third-party"
# third-party addon folders (loose files under Interface/AddOns, like ours)
THIRD_PARTY_ADDONS = [
    THIRD_PARTY / "Prestige-and-Draft-Mode" / "Client Side Files" / "Client Addon" / "PrestigeSystem",
]
# Our Questie fork (tools/third_party/fetch.py), staged by stage_questie() as
# the runtime files only, in the folder name the 3.3.5 client loads it under.
QUESTIE_SOURCE = THIRD_PARTY / "Questie-NekoCore"
QUESTIE_STAGED = THIRD_PARTY / "_staged" / "Questie-335"
THIRD_PARTY_ADDONS.append(QUESTIE_STAGED)
# deployed to the dev client, never shipped to players (bundle zip, full client zip)
DEV_ONLY_ADDONS = {"NekoTalentDebug"}
# the realm both player zips point realmlist.wtf at (the site shows the same
# address -- NEKO_REALM_ADDRESS)
REALM_ADDRESS = "wow1.nekos.farm"
LOCALE = "enUS"

# mod-individual-progression's optional/ ships these server-only DBCs in
# dbc.7z (unconditional) plus Spell.dbc in patch-V.7z/patch-S.7z (mutually
# exclusive mana-cost variants -- see that module's optional/patch-
# explanations.txt). All 5 need both a server-side data/dbc mount (see
# docker-compose.override.yml) AND, for Spell.dbc specifically, a place in
# our own client MPQ -- deliberately NOT the module's own patch-V.mpq/
# patch-S.mpq, which collide with unrelated same-named files already on
# the test client (confirmed by hash: different file, different origin).
PROGRESSION_DBC_ARCHIVE = "dbc.7z"
PROGRESSION_DBC_FILES = [
    "SkillLine.dbc", "SkillLineAbility.dbc", "SkillRaceClassInfo.dbc", "SpellItemEnchantment.dbc",
]
PROGRESSION_SPELL_ARCHIVE = {"V": "patch-V.7z", "S": "patch-S.7z"}


# port_era_spells.py's output: WotLK's Spell.dbc plus the era talent rank
# spells it rescued. The BASE for build_era_spells.py, never deployed as-is.
# It used to be written straight to GENERATED_SPELL, which meant every
# --build silently replaced the deployed Spell.dbc with one that has no era
# spells in it at all.
PRE_ERA_SPELL = REPO_ROOT / "data" / "inputs" / "pre-era-spells-Spell.dbc"
GENERATED_SPELL = GENERATED_DIR / "Spell.dbc"  # build_era_spells.py output: the deployed one
ERA_SPELL_MAP = GENERATED_DIR / "era-spell-map.json"


def port_spells(vanilla_root: Path | None, tbc_root: Path, wotlk_root: Path) -> None:
    """Rescues the era talent rank spells WotLK deleted (from the 2.4.3
    client) into data/generated/Spell.dbc, on top of mod-individual-
    progression's staged Spell.dbc so its mana-cost edits are kept. Must run
    BEFORE build_era_tree.py, which only emits talents whose spells exist."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "build_patch" / "port_era_spells.py"),
        "--wotlk-root", str(wotlk_root),
        "--tbc-root", str(tbc_root),
        "--base-spell", str(PROGRESSION_STAGE_DIR / "Spell.dbc"),
        "--out", str(PRE_ERA_SPELL),
    ]
    if vanilla_root:
        cmd += ["--vanilla-root", str(vanilla_root)]
    print("+ " + " ".join(cmd))
    PRE_ERA_SPELL.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)


def build_era_spells(vanilla_root: Path | None, tbc_root: Path | None, wotlk_root: Path) -> None:
    """Every era's own copy of every class spell (build_era_spells.py), on
    top of port_spells()'s output. Must run BEFORE build_era_tree.py, whose
    talent ranks point at these copies through era-spell-map.json."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "build_patch" / "build_era_spells.py"),
        "--wotlk-root", str(wotlk_root),
        "--base-spell", str(PRE_ERA_SPELL),
        "--out-dir", str(GENERATED_DIR),
    ]
    if vanilla_root:
        cmd += ["--vanilla-root", str(vanilla_root)]
    if tbc_root:
        cmd += ["--tbc-root", str(tbc_root)]
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def build_dbcs(vanilla_root: Path | None, tbc_root: Path | None, wotlk_root: Path, classes: list[str]) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "build_patch" / "build_era_tree.py"),
        "--wotlk-root", str(wotlk_root),
        "--out-dbc-dir", str(GENERATED_DIR),
        "--out-mapping-dir", str(REPO_ROOT / "data" / "vanilla"),
    ]
    if GENERATED_SPELL.exists():
        cmd += ["--spell-dbc", str(GENERATED_SPELL)]
    if ERA_SPELL_MAP.exists():
        cmd += ["--era-spell-map", str(ERA_SPELL_MAP)]
    else:
        print("note: no ported Spell.dbc (needs --tbc-root) -- talents whose spells WotLK deleted stay out")
    if vanilla_root:
        cmd += ["--vanilla-root", str(vanilla_root)]
    if tbc_root:
        cmd += ["--tbc-root", str(tbc_root)]
    for cls in classes:
        cmd += ["--class", cls]
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def extract_progression_dbcs(module_root: Path, variant: str) -> None:
    """Pulls the server-only DBCs + the chosen Spell.dbc mana-cost variant
    straight out of mod-individual-progression's own optional/*.7z archives
    into PROGRESSION_STAGE_DIR -- no separate copy of this data maintained
    in this repo, the module's own archives stay the source of truth."""
    if shutil.which("7z") is None:
        raise SystemExit(
            "7z not found on PATH -- install 7-Zip (the module's own optional/ "
            "archives are .7z, same tool needed to extract them by hand)."
        )

    optional_dir = module_root / "optional"
    dbc_archive = optional_dir / PROGRESSION_DBC_ARCHIVE
    spell_archive = optional_dir / PROGRESSION_SPELL_ARCHIVE[variant]
    for archive in (dbc_archive, spell_archive):
        if not archive.exists():
            raise SystemExit(f"Missing {archive} -- is --progression-module-root correct?")

    PROGRESSION_STAGE_DIR.mkdir(parents=True, exist_ok=True)
    for archive, wanted in [(dbc_archive, PROGRESSION_DBC_FILES), (spell_archive, ["Spell.dbc"])]:
        cmd = ["7z", "e", "-y", f"-o{PROGRESSION_STAGE_DIR}", str(archive), *wanted]
        print("+ " + " ".join(cmd))
        subprocess.run(cmd, check=True, capture_output=True)

    for name in [*PROGRESSION_DBC_FILES, "Spell.dbc"]:
        if not (PROGRESSION_STAGE_DIR / name).exists():
            raise SystemExit(f"Extraction didn't produce {name} -- check the archive still contains it.")
    print(f"Staged progression DBCs (variant {variant}) -> {PROGRESSION_STAGE_DIR}")


def package_mpq() -> None:
    talent = GENERATED_DIR / "Talent.dbc"
    talent_tab = GENERATED_DIR / "TalentTab.dbc"
    if not talent.exists() or not talent_tab.exists():
        raise SystemExit(
            f"Missing {talent} / {talent_tab} -- run with --build first "
            "(needs --vanilla-root and/or --tbc-root)."
        )
    files = {
        "DBFilesClient\\Talent.dbc": talent.read_bytes(),
        "DBFilesClient\\TalentTab.dbc": talent_tab.read_bytes(),
    }
    # Spell.dbc: the ported one (progression's edits + rescued era talent
    # spells) when built, else progression's alone. Same file the realm
    # bind-mounts (server/docker-compose.override.yml) -- they must match.
    if GENERATED_SPELL.exists():
        files["DBFilesClient\\Spell.dbc"] = GENERATED_SPELL.read_bytes()
        print(f"Including ported Spell.dbc ({GENERATED_SPELL}) in the client MPQ")
    elif (PROGRESSION_STAGE_DIR / "Spell.dbc").exists():
        files["DBFilesClient\\Spell.dbc"] = (PROGRESSION_STAGE_DIR / "Spell.dbc").read_bytes()
        print("Including progression Spell.dbc in the client MPQ "
              "(server-only DBCs -- SkillLine etc. -- don't need a client copy)")
    # SkillLineAbility: previously server-only (the client never validates
    # skill data against its own copy the way it does talents). Era spells
    # change that -- the client reads SkillLineAbility to decide which
    # spellbook tab a known spell belongs in, so without a client copy every
    # era clone a character knows would sit outside its class's tabs.
    # build_era_spells.py's output, which is progression's own copy plus one
    # row per clone; same file the realm bind-mounts.
    generated_sla = GENERATED_DIR / "SkillLineAbility.dbc"
    if generated_sla.exists():
        files["DBFilesClient\\SkillLineAbility.dbc"] = generated_sla.read_bytes()
        print(f"Including era-extended SkillLineAbility.dbc ({generated_sla}) in the client MPQ")

    # Spell index side tables, emitted by build_era_spells.py ONLY when an
    # era value had no equivalent row in WotLK's own table (e.g. a cast time
    # or range Vanilla had and WotLK does not). An era spell's
    # CastingTimeIndex/RangeIndex points into these, so a client without
    # them would render that spell with the wrong range or cast time --
    # they ship together or not at all. Same files the realm bind-mounts.
    for name in ["SpellCastTimes.dbc", "SpellDuration.dbc", "SpellRadius.dbc", "SpellRange.dbc"]:
        side = GENERATED_DIR / name
        if side.exists():
            files[f"DBFilesClient\\{name}"] = side.read_bytes()
            print(f"Including era-extended {name} in the client MPQ")

    mod_dbcs = sorted(MOD_DBC_DIR.glob("*.dbc")) if MOD_DBC_DIR.is_dir() else []
    for dbc in mod_dbcs:
        key = f"DBFilesClient\\{dbc.name}"
        if key in files:
            raise SystemExit(f"{dbc} collides with a DBC already staged from another source")
        files[key] = dbc.read_bytes()
    if mod_dbcs:
        print(f"Including {len(mod_dbcs)} merged third-party DBCs from {MOD_DBC_DIR}")
    else:
        print("note: no merged third-party DBCs (tools/build_patch/build_mod_dbcs.py) -- "
              "race/class unlocks and prestige titles won't be in the client")
    write_archive(STAGED_MPQ, files)
    print(f"Packaged {STAGED_MPQ} ({STAGED_MPQ.stat().st_size:,} bytes, {len(files)} files)")


def deploy_mpq(wotlk_root: Path, mpq_name: str) -> None:
    dest = wotlk_root / "Data" / mpq_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(STAGED_MPQ, dest)
    except PermissionError:
        raise SystemExit(
            f"Could not overwrite {dest} -- it's locked, almost certainly because "
            "the WoW client currently has it open. Close the client and rerun."
        )
    print(f"Deployed -> {dest}")


def stage_questie() -> None:
    """Copies what Questie loads at runtime into QUESTIE_STAGED: the same set
    upstream's build.py releases, plus the 3.3.5 fork's Compat layer and its
    own TOC. Leaves out .git, the 71 MB of ExternalScripts, the CLI and tests,
    none of which a player needs."""
    if not (QUESTIE_SOURCE / "Questie-335.toc").is_file():
        print(f"warning: {QUESTIE_SOURCE} missing -- run tools/third_party/fetch.py Questie-NekoCore; "
              "the patch ships without Questie", file=sys.stderr)
        shutil.rmtree(QUESTIE_STAGED, ignore_errors=True)
        return
    shutil.rmtree(QUESTIE_STAGED, ignore_errors=True)
    QUESTIE_STAGED.mkdir(parents=True)
    ignore = shutil.ignore_patterns("*.test.lua", "ExtractMapData")
    for d in ("Compat", "Database", "Icons", "Libs", "Localization", "Modules"):
        shutil.copytree(QUESTIE_SOURCE / d, QUESTIE_STAGED / d, ignore=ignore)
    for f in ("embeds.xml", "Questie.lua", "Questie-335.toc"):
        shutil.copy2(QUESTIE_SOURCE / f, QUESTIE_STAGED / f)
    # Questie-335.toc only loads the Wotlk translation lookups (they cover all
    # three expansions); the Classic/TBC ones are for the -Classic/-TBC TOCs.
    # 54 MB we'd otherwise ship. Removed by path: Database/Classic and
    # Database/TBC share the names and are needed.
    for unused in ("Classic", "TBC"):
        shutil.rmtree(QUESTIE_STAGED / "Localization" / "lookups" / unused)
    print(f"Staged Questie -> {QUESTIE_STAGED}")


def addon_dirs() -> list[Path]:
    ours = sorted(p for p in ADDONS_DIR.iterdir() if p.is_dir())
    theirs = [p for p in THIRD_PARTY_ADDONS if p.is_dir()]
    return ours + theirs


def player_addon_dirs() -> list[Path]:
    """What players get: every addon except the dev-only ones. The dev client
    still gets those via deploy_addons()."""
    return [p for p in addon_dirs() if p.name not in DEV_ONLY_ADDONS]


def deploy_addons(wotlk_root: Path) -> None:
    dest_root = wotlk_root / "Interface" / "AddOns"
    for addon_dir in addon_dirs():
        dest = dest_root / addon_dir.name
        shutil.copytree(addon_dir, dest, dirs_exist_ok=True)
        print(f"Deployed addon -> {dest}")


# The patch's version, stamped into three places that must agree: the
# NekoPatchCheck addon (which reports it in game), the file the worldserver
# compares that report against (bind-mounted, see the override), and the
# launcher manifest next to the bundle zip.
PATCH_CHECK_ADDON = "NekoPatchCheck"
PATCH_VERSION_LUA = ADDONS_DIR / PATCH_CHECK_ADDON / "Version.lua"
PATCH_VERSION_FILE = GENERATED_DIR / "patch-version.txt"


def stamp_patch_version() -> str:
    """Hashes what a player installs (the MPQ and the player addons, minus
    the version file itself) into a short version and writes it out. A
    content hash, not a counter: rebuilding the same patch gives the same
    version, so nobody is told to update for nothing."""
    h = hashlib.sha256(STAGED_MPQ.read_bytes())
    for addon_dir in player_addon_dirs():
        for f in sorted(p for p in addon_dir.rglob("*") if p.is_file()):
            if f == PATCH_VERSION_LUA:
                continue
            h.update(f"{addon_dir.name}/{f.relative_to(addon_dir).as_posix()}".encode())
            h.update(f.read_bytes())
    version = h.hexdigest()[:10]
    PATCH_VERSION_LUA.write_text(
        "-- Written by tools/install_patch/install_client.py; do not edit.\n"
        f'NEKO_PATCH_VERSION = "{version}"\n', encoding="utf-8")
    PATCH_VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    print(f"Patch version {version} -> {PATCH_VERSION_LUA.relative_to(REPO_ROOT)}, "
          f"{PATCH_VERSION_FILE.relative_to(REPO_ROOT)}")
    return version


def write_manifest(zip_path: Path, version: str) -> None:
    """<zip>.json beside the bundle: what the launcher reads to decide
    whether to download, and to verify what it downloaded."""
    data = zip_path.read_bytes()
    manifest = {
        "version": version,
        "file": zip_path.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    out = zip_path.with_suffix(".json")
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


def write_bundle_zip(out: Path, mpq_name: str, realm: str) -> None:
    """Everything a player drops over a stock client: Data/<mpq>, the realmlist
    and Interface/AddOns/*, so extracting it is the whole setup."""
    import zipfile
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(STAGED_MPQ, f"Data/{mpq_name}")
        z.writestr(f"Data/{LOCALE}/realmlist.wtf", f"set realmlist {realm}\n")
        for addon_dir in player_addon_dirs():
            for f in sorted(p for p in addon_dir.rglob("*") if p.is_file()):
                z.write(f, f"Interface/AddOns/{addon_dir.name}/{f.relative_to(addon_dir).as_posix()}")
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="the client install to patch")
    ap.add_argument("--vanilla-root", type=Path, help="1.12.1 client root (for --build; omit to leave Vanilla out)")
    ap.add_argument("--tbc-root", type=Path, help="2.4.3 client root (for --build; omit to leave TBC out)")
    ap.add_argument("--class", dest="classes", action="append", choices=ALL_CLASSES,
                     help="repeat to build a subset; default is all 9 eligible classes")
    ap.add_argument("--build", action="store_true", help="regenerate data/generated/*.dbc before packaging")
    ap.add_argument("--addons-only", action="store_true", help="skip DBC build/package/deploy entirely")
    ap.add_argument("--progression-module-root", type=Path,
                     help="mod-individual-progression checkout root (e.g. D:\\AzerothCore\\modules\\"
                          "mod-individual-progression) -- re-extracts its optional/ DBCs into the MPQ. "
                          "Omit to reuse whatever was staged by a previous run, if any.")
    ap.add_argument("--progression-variant", choices=["V", "S"], default="V",
                     help="mana-cost Spell.dbc variant: V = era-authentic lower costs, S = keep WotLK costs (default V)")
    ap.add_argument("--bundle-zip", type=Path,
                     help="also write a zip of the patch (Data/patch-Z.mpq + Interface/AddOns) for players to extract over a stock client")
    ap.add_argument("--realm", default=REALM_ADDRESS,
                     help=f"server address the bundle zip's realmlist.wtf points at (default {REALM_ADDRESS})")
    args = ap.parse_args()

    if not args.wotlk_root.is_dir():
        raise SystemExit(f"--wotlk-root does not exist: {args.wotlk_root}")

    if not args.addons_only:
        classes = args.classes or ALL_CLASSES
        if args.build and not args.vanilla_root and not args.tbc_root:
            raise SystemExit("--build requires --vanilla-root and/or --tbc-root")
        # progression's Spell.dbc is the base the spell port builds on, so
        # (re)stage it first when asked
        if args.progression_module_root:
            extract_progression_dbcs(args.progression_module_root, args.progression_variant)
        if args.build:
            if args.tbc_root:
                port_spells(args.vanilla_root, args.tbc_root, args.wotlk_root)
            build_era_spells(args.vanilla_root, args.tbc_root, args.wotlk_root)
            build_dbcs(args.vanilla_root, args.tbc_root, args.wotlk_root, classes)
            print("\nNOTE: era spell ids may have changed. Regenerate and apply the world SQL:\n"
                  "  python tools/build_patch/build_era_spell_sql.py "
                  "--out data/sql/db-world/base/zzz_nekocore_era_spells.sql\n"
                  "  (then sync_module.py + apply_module_sql.sh, see docs/deploy.md)")
        package_mpq()
        deploy_mpq(args.wotlk_root, "patch-Z.mpq")

    stage_questie()
    version = stamp_patch_version() if STAGED_MPQ.exists() else None
    deploy_addons(args.wotlk_root)
    if args.bundle_zip:
        if version is None:
            raise SystemExit("--bundle-zip needs a packaged MPQ; drop --addons-only")
        write_bundle_zip(args.bundle_zip, "patch-Z.mpq", args.realm)
        write_manifest(args.bundle_zip, version)

    if args.addons_only:
        print("\nDone. /reload is enough to pick up addon changes.")
    else:
        print("\nDone. Fully log out and back in (not just /reload) so the client "
              "picks up the new Data\\patch-Z.mpq.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

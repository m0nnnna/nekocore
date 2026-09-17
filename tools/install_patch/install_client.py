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
    # Full rebuild (needs your own 1.12.1 client for source talent data)
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" \\
        --source-root "D:\\...\\1.12.1" --build

    # Redeploy already-built data/generated/*.dbc + the addons, no rebuild
    python install_client.py --wotlk-root "D:\\...\\3.3.5a"

    # Addons only (fast path for iterating on Lua without touching DBCs)
    python install_client.py --wotlk-root "D:\\...\\3.3.5a" --addons-only
"""
from __future__ import annotations

import argparse
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


def build_dbcs(source_root: Path, wotlk_root: Path, classes: list[str]) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "build_patch" / "build_era_tree.py"),
        "--source-build", "1.12.1",
        "--source-root", str(source_root),
        "--wotlk-root", str(wotlk_root),
        "--out-dbc-dir", str(GENERATED_DIR),
        "--out-mapping-dir", str(REPO_ROOT / "data" / "vanilla"),
    ]
    for cls in classes:
        cmd += ["--class", cls]
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def package_mpq() -> None:
    talent = GENERATED_DIR / "Talent.dbc"
    talent_tab = GENERATED_DIR / "TalentTab.dbc"
    if not talent.exists() or not talent_tab.exists():
        raise SystemExit(
            f"Missing {talent} / {talent_tab} -- run with --build first "
            "(needs a 1.12.1 client root via --source-root)."
        )
    write_archive(STAGED_MPQ, {
        "DBFilesClient\\Talent.dbc": talent.read_bytes(),
        "DBFilesClient\\TalentTab.dbc": talent_tab.read_bytes(),
    })
    print(f"Packaged {STAGED_MPQ} ({STAGED_MPQ.stat().st_size:,} bytes)")


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


def deploy_addons(wotlk_root: Path) -> None:
    dest_root = wotlk_root / "Interface" / "AddOns"
    for addon_dir in sorted(p for p in ADDONS_DIR.iterdir() if p.is_dir()):
        dest = dest_root / addon_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in addon_dir.iterdir():
            shutil.copyfile(f, dest / f.name)
        print(f"Deployed addon -> {dest}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="the client install to patch")
    ap.add_argument("--source-root", type=Path, help="1.12.1 client root (required with --build)")
    ap.add_argument("--class", dest="classes", action="append", choices=ALL_CLASSES,
                     help="repeat to build a subset; default is all 9 eligible classes")
    ap.add_argument("--build", action="store_true", help="regenerate data/generated/*.dbc before packaging")
    ap.add_argument("--addons-only", action="store_true", help="skip DBC build/package/deploy entirely")
    args = ap.parse_args()

    if not args.wotlk_root.is_dir():
        raise SystemExit(f"--wotlk-root does not exist: {args.wotlk_root}")

    if not args.addons_only:
        classes = args.classes or ALL_CLASSES
        if args.build:
            if not args.source_root:
                raise SystemExit("--build requires --source-root (your 1.12.1 client)")
            build_dbcs(args.source_root, args.wotlk_root, classes)
        package_mpq()
        deploy_mpq(args.wotlk_root, "patch-Z.mpq")

    deploy_addons(args.wotlk_root)

    if args.addons_only:
        print("\nDone. /reload is enough to pick up addon changes.")
    else:
        print("\nDone. Fully log out and back in (not just /reload) so the client "
              "picks up the new Data\\patch-Z.mpq.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

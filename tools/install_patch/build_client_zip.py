"""
Packs a patched 3.3.5a client into the player-facing nekocore.zip: an
explicit ALLOWLIST of what a player needs and nothing else -- no Cache/WTF/
Logs, no third-party addons, no launcher leftovers, no editor backups.

    python tools/install_patch/build_client_zip.py \\
        --wotlk-root "D:\\Games\\World of Warcraft 3.3.5a" \\
        --out "D:\\Games\\nekocore.zip"

What goes in (decided 2026-09-20 against the dev box's live-tested client):

  Wow.exe                 the AwesomeWotlk-patched + camera-fixed exe
                          (tools/install_patch/patch_camera_bug.py); it imports
  AwesomeWotlkLib.dll     ...this, so the DLL ships. AwesomeWotlkPatch.exe
                          (the one-time patcher) and Wow.exe.bak do not.
  DivxDecoder.dll, msvcr80.dll   stock runtime deps
  Data/*.MPQ              the stock archives + patch-V.mpq (predates nekocore,
                          client was live-tested with it; patch-Z overrides
                          the files they share) + patch-Z.mpq (ours: era
                          talents, mod-uac/Prestige DBCs, progression Spell.dbc).
                          Patch-J/Patch-U (foreign loading screens) stay out.
  Data/enUS/              stock locale archives. patch-enUS.MPQ is taken from
                          the pristine .bak when one exists -- the old launcher
                          added an inert root-level Spell.dbc to the live one.
                          patch-enUS-4.MPQ (a Sep 16 talent test build,
                          superseded by patch-Z) stays out. realmlist.wtf is
                          written fresh pointing at the realm.
  Interface/AddOns/       Blizzard_* signature stubs (stock) + our addons only.

MPQs are stored uncompressed inside the zip (they're already compressed --
deflating 17 GB of them would take an hour for a few percent).
"""
from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

ROOT_FILES = ["Wow.exe", "AwesomeWotlkLib.dll", "DivxDecoder.dll", "msvcr80.dll"]

DATA_MPQS = [
    "common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ",
    "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ",
    "patch-V.mpq", "patch-Z.mpq",
]

LOCALE = "enUS"
LOCALE_MPQS = [
    "backup-{L}.MPQ", "base-{L}.MPQ", "locale-{L}.MPQ", "speech-{L}.MPQ",
    "expansion-locale-{L}.MPQ", "expansion-speech-{L}.MPQ",
    "lichking-locale-{L}.MPQ", "lichking-speech-{L}.MPQ",
    "patch-{L}-2.MPQ", "patch-{L}-3.MPQ",
]
LOCALE_EXTRAS = ["AccountBilling.url", "TechSupport.url", "Credits.html", "Credits_BC.html", "Credits_LK.html",
                 "connection-help.html", "eula.html", "tos.html"]
LOCALE_DIRS = ["Documentation", "Interface"]

OUR_ADDONS = ["NekoTalentUI", "PrestigeSystem"]

REALMLIST = "set realmlist wow1.nekos.farm\n"

ZIP_ROOT = "NekoCore"


def add_file(z: zipfile.ZipFile, src: Path, arc: str, stored: bool) -> int:
    z.write(src, f"{ZIP_ROOT}/{arc}", compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    return src.stat().st_size


def add_tree(z: zipfile.ZipFile, src: Path, arc: str) -> int:
    n = 0
    for f in sorted(src.rglob("*")):
        if f.is_file():
            n += add_file(z, f, f"{arc}/{f.relative_to(src).as_posix()}", f.suffix.lower() == ".mpq")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--realm", default=REALMLIST.split()[-1], help="realmlist host (default wow1.nekos.farm)")
    args = ap.parse_args()
    root: Path = args.wotlk_root
    loc = root / "Data" / LOCALE

    plan: list[tuple[Path, str, bool]] = []   # (source, archive path, stored)
    for name in ROOT_FILES:
        plan.append((root / name, name, False))
    for name in DATA_MPQS:
        plan.append((root / "Data" / name, f"Data/{name}", True))
    for tmpl in LOCALE_MPQS:
        name = tmpl.format(L=LOCALE)
        plan.append((loc / name, f"Data/{LOCALE}/{name}", True))
    main_locale = loc / f"patch-{LOCALE}.MPQ"
    pristine = main_locale.with_suffix(".MPQ.bak")
    plan.append((pristine if pristine.is_file() else main_locale, f"Data/{LOCALE}/patch-{LOCALE}.MPQ", True))
    for name in LOCALE_EXTRAS:
        if (loc / name).is_file():
            plan.append((loc / name, f"Data/{LOCALE}/{name}", False))

    missing = [str(p) for p, _, _ in plan if not p.is_file()]
    if missing:
        raise SystemExit("missing from the client:\n  " + "\n  ".join(missing))
    for addon in OUR_ADDONS:
        if not (root / "Interface" / "AddOns" / addon).is_dir():
            raise SystemExit(f"addon not deployed in the client: {addon} (run install_client.py first)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    t0 = time.time()
    with zipfile.ZipFile(args.out, "w", allowZip64=True) as z:
        for src, arc, stored in plan:
            print(f"  {arc}", flush=True)
            total += add_file(z, src, arc, stored)
        for d in LOCALE_DIRS:
            if (loc / d).is_dir():
                total += add_tree(z, loc / d, f"Data/{LOCALE}/{d}")
        z.writestr(f"{ZIP_ROOT}/Data/{LOCALE}/realmlist.wtf", f"set realmlist {args.realm}\n")
        addons = root / "Interface" / "AddOns"
        for d in sorted(addons.iterdir()):
            if d.is_dir() and (d.name.startswith("Blizzard_") or d.name in OUR_ADDONS):
                print(f"  Interface/AddOns/{d.name}", flush=True)
                total += add_tree(z, d, f"Interface/AddOns/{d.name}")

    print(f"wrote {args.out} ({args.out.stat().st_size / 2**30:.2f} GiB, {total / 2**30:.2f} GiB of input) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

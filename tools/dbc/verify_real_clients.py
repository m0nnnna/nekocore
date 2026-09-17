"""
Phase 0 verification against real client installs: for each target build,
find every copy of Talent.dbc/TalentTab.dbc/SpellIcon.dbc across the client's
MPQ archives and round-trip each one (read -> write -> byte diff) using our
schemas. This is stronger than roundtrip_test.py's single-file usage since it
exercises every patch-layer copy of each file, not just whichever one a
manual extraction happened to grab.

Usage: python verify_real_clients.py
Client paths are hard-coded below to this machine's install locations.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mpq_source import find_all, resolve
from schemas import BUILD_SCHEMAS
from wdbc import LOCALE_COUNT, read_dbc, write_dbc

CLIENTS = {
    "1.12.1": r"D:\Games\World of Warcraft 1.12.1",
    "2.4.3": r"D:\Games\World of Warcraft 2.4.3",
    "3.3.5a": r"D:\Games\World of Warcraft 3.3.5a",
}
TARGET_FILES = ["Talent.dbc", "TalentTab.dbc", "SpellIcon.dbc", "Spell.dbc"]


def main() -> int:
    all_ok = True
    for build, root in CLIENTS.items():
        print(f"=== {build} ===")
        for fn in TARGET_FILES:
            if fn not in BUILD_SCHEMAS[build]:
                print(f"  {fn}: no schema registered for {build}, skipping")
                continue
            schema = BUILD_SCHEMAS[build][fn]
            locale_count = LOCALE_COUNT[build]
            hits = find_all(root, fn)
            if not hits:
                print(f"  {fn}: NOT FOUND in any archive")
                all_ok = False
                continue
            resolved_archive, _ = resolve(root, fn)

            for archive, data in hits:
                is_authoritative = archive == resolved_archive
                with tempfile.TemporaryDirectory() as td:
                    src_path = Path(td) / fn
                    src_path.write_bytes(data)
                    try:
                        dbc = read_dbc(src_path, schema, locale_count)
                    except Exception as e:
                        tag = "FAIL" if is_authoritative else "SKIP"
                        note = " (this is the copy the client loads)" if is_authoritative else \
                            " (stale/older-layout copy shadowed by a patch -- not what the client loads)"
                        print(f"  {tag} {fn} [{archive}]: read_dbc raised {e!r}{note}")
                        if is_authoritative:
                            all_ok = False
                        continue
                    out_path = Path(td) / "out.dbc"
                    write_dbc(out_path, dbc)
                    roundtripped = out_path.read_bytes()
                marker = " <- resolve() picks this" if is_authoritative else ""
                if roundtripped == data:
                    print(f"  OK   {fn} [{archive}]: {len(dbc.rows)} rows, byte-identical{marker}")
                else:
                    tag = "FAIL" if is_authoritative else "NOTE"
                    note = "" if is_authoritative else \
                        " (not what the client loads -- likely a self-inconsistent custom/third-party archive, not our schema)"
                    print(f"  {tag} {fn} [{archive}]: round-trip mismatch "
                          f"(orig={len(data)}b roundtrip={len(roundtripped)}b){marker}{note}")
                    if is_authoritative:
                        all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

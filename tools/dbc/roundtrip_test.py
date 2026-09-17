"""
Phase 0 verification: read a stock DBC file, write it back unchanged, and
diff byte-for-byte against the original. This is the ground-truth check that
our schemas (field order, types, loc_string locale_count) actually match the
real file layout for a given client build -- if the schema were wrong, either
read_dbc() would already raise (field_count mismatch) or the round-trip
bytes would differ.

Usage:
    python roundtrip_test.py <build> <path-to-dbc> [<path-to-dbc> ...]

    build must be one of: 1.12.1, 2.4.3, 3.3.5a
    each dbc path's filename (e.g. Talent.dbc) is used to look up the schema.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from wdbc import LOCALE_COUNT, read_dbc, write_dbc
from schemas import BUILD_SCHEMAS


def check_one(build: str, path: Path) -> bool:
    schemas_for_build = BUILD_SCHEMAS[build]
    if path.name not in schemas_for_build:
        print(f"SKIP  {path.name}: no schema registered for build {build}")
        return True

    schema = schemas_for_build[path.name]
    locale_count = LOCALE_COUNT[build]

    original = path.read_bytes()
    dbc = read_dbc(path, schema, locale_count)

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / path.name
        write_dbc(out_path, dbc)
        roundtripped = out_path.read_bytes()

    if original == roundtripped:
        print(f"OK    {path.name} ({build}): {len(dbc.rows)} rows, byte-identical round-trip")
        return True

    print(f"FAIL  {path.name} ({build}): round-trip differs from original")
    print(f"      original size={len(original)} roundtrip size={len(roundtripped)}")
    for i, (a, b) in enumerate(zip(original, roundtripped)):
        if a != b:
            print(f"      first byte diff at offset {i}: original={a:#04x} roundtrip={b:#04x}")
            break
    return False


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    build = argv[1]
    if build not in BUILD_SCHEMAS:
        print(f"unknown build {build!r}, expected one of {list(BUILD_SCHEMAS)}")
        return 2

    ok = True
    for arg in argv[2:]:
        ok &= check_one(build, Path(arg))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

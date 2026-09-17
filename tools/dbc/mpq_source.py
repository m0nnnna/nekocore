"""
Locate and extract DBFilesClient/*.dbc entries directly out of a client
install's MPQ archives, so we don't need a separate manual MPQ-extraction
step before running the round-trip test or the era extractor.

mpyq can pull a file out of an MPQ by exact internal path without needing
the archive's (listfile) -- MPQ's hash table is keyed by name hash, so a
known path like "DBFilesClient\\Talent.dbc" resolves directly.

A given DBC filename may exist in more than one MPQ in a client install
(base archive + one or more patch archives overriding it). We don't hard-code
a single "correct" patch-priority order here -- for verification purposes we
want every copy we can find, not just the one the live client would load.
find_all() returns every (archive_name, bytes) pair containing the file;
callers that need "the one the client actually loads" should pick the last
entry (patches are conventionally named/loaded so the last-found match in
patch-priority order wins), but for schema/round-trip verification checking
every copy is strictly more thorough.
"""
from __future__ import annotations

import re
from pathlib import Path

import mpyq

DBC_INTERNAL_PREFIX = "DBFilesClient\\"

# Priority ranking for picking "the copy the client actually loads" when a
# DBC exists in more than one archive. Confirmed empirically (see
# verify_real_clients.py) against real 1.12.1/2.4.3/3.3.5a installs: base
# archives (dbc.MPQ, common.MPQ, expansion.MPQ, lichking.MPQ,
# locale-enUS.MPQ) can lag behind the live client's actual record layout --
# e.g. this 2.4.3 install's locale-enUS.MPQ still has TalentTab.dbc in the
# pre-2.1.0.6692 15-field layout, while patch-enUS.MPQ has the 16-locale
# layout the running 2.4.3 client actually uses. Official numbered patches
# (patch.MPQ, patch-2.MPQ, ... / patch-enUS.MPQ, patch-enUS-2.MPQ, ...)
# override base archives, and higher patch numbers override lower ones.
# Custom single-letter patches (patch-J.mpq, patch-U.mpq, patch-V.mpq seen
# in this 3.3.5a install) aren't ranked here since none of our target DBCs
# were found in them -- if that changes, this needs real load-order info
# for that specific client build, not a guess.
_PATCH_NUM_RE = re.compile(r"patch(?:-[a-zA-Z]+)?-(\d+)\.mpq$", re.IGNORECASE)
_PATCH_BASE_RE = re.compile(r"(^|\\)patch(-[a-zA-Z]+)?\.mpq$", re.IGNORECASE)


def _priority(archive_relpath: str) -> int:
    m = _PATCH_NUM_RE.search(archive_relpath)
    if m:
        return 1 + int(m.group(1))
    if _PATCH_BASE_RE.search(archive_relpath):
        return 1
    return 0


def find_all(client_root: str | Path, dbc_filename: str) -> list[tuple[str, bytes]]:
    """Search every top-level *.MPQ (case-insensitive) directly under
    <client_root>/Data (and one level of locale subfolders, e.g. Data/enUS)
    for dbc_filename, returning (archive_relative_path, raw_bytes) for each
    archive that contains it."""
    data_dir = Path(client_root) / "Data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"no Data/ folder under {client_root}")

    internal_path = DBC_INTERNAL_PREFIX + dbc_filename
    found: list[tuple[str, bytes]] = []

    mpq_paths = sorted(data_dir.glob("*.[Mm][Pp][Qq]")) + sorted(
        data_dir.glob("*/*.[Mm][Pp][Qq]")
    )

    for mpq_path in mpq_paths:
        try:
            archive = mpyq.MPQArchive(str(mpq_path))
        except Exception:
            continue  # not a real MPQ / unsupported variant, skip
        try:
            data = archive.read_file(internal_path)
        except Exception:
            data = None
        if data:
            found.append((str(mpq_path.relative_to(data_dir)), data))

    return found


def resolve(client_root: str | Path, dbc_filename: str) -> tuple[str, bytes]:
    """Return the (archive_relative_path, bytes) for the copy of
    dbc_filename the running client actually loads, per the patch-priority
    ranking in _priority(). Raises FileNotFoundError if no archive has it."""
    hits = find_all(client_root, dbc_filename)
    if not hits:
        raise FileNotFoundError(f"{dbc_filename} not found in any MPQ under {client_root}")
    return max(hits, key=lambda hit: _priority(hit[0]))

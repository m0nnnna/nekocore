"""
Minimal MPQ (v0) archive writer -- just enough to build a small, uncompressed
patch archive the retail 3.3.5a client will load (e.g. a merged Talent.dbc).

Neither sibling project (open-wow-client's `mpq` crate, this repo's own
mpyq-based mpq_source.py) can WRITE an archive, only read one -- so this is
new code, not a port. The crypto (hash table generation, path hashing,
stream cipher) is transcribed from open-wow-client's crates/mpq/src/crypt.rs,
which documents its own known-answer test vectors
(hash("(hash table)", FILE_KEY) == 0xC3AF3770, etc.) -- reused here rather
than re-derived, and checked again below at import time so a transcription
error fails loud instead of producing a silently-corrupt archive.

Deliberately minimal: every file is stored SINGLE_UNIT, uncompressed,
unencrypted. No sector table, no compression codec, no (listfile) member
(not required for the client to find a file by its known internal path --
only used by tools that enumerate an archive's contents). Scope is "produce
a patch archive with a handful of known DBC paths in it," not a general MPQ
writer.

Format reference: https://wowdev.wiki/MPQ (the same source open-wow-client's
reader cites).
"""
from __future__ import annotations

import struct
from pathlib import Path

MAGIC = b"MPQ\x1a"
HASH_ENTRY_EMPTY = 0xFFFFFFFF
HASH_ENTRY_DELETED = 0xFFFFFFFE

FLAG_EXISTS = 0x80000000
FLAG_SINGLE_UNIT = 0x01000000

_HASH_TABLE_KEY = "(hash table)"
_BLOCK_TABLE_KEY = "(block table)"

TABLE_OFFSET, NAME_A, NAME_B, FILE_KEY = range(4)

_MASK32 = 0xFFFFFFFF


def _build_crypt_table() -> list[int]:
    table = [0] * 0x500
    seed = 0x00100001
    for i in range(0x100):
        idx = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            hi = seed & 0xFFFF
            seed = (seed * 125 + 3) % 0x2AAAAB
            lo = seed & 0xFFFF
            table[idx] = (hi << 16) | lo
            idx += 0x100
    return table


_CRYPT_TABLE = _build_crypt_table()


def _normalize(byte: int) -> int:
    ch = chr(byte)
    if ch == "/":
        return ord("\\")
    if "a" <= ch <= "z":
        return byte - 32
    return byte


def mpq_hash(path: str, kind: int) -> int:
    base = kind * 0x100
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for byte in path.encode("ascii"):
        ch = _normalize(byte)
        seed1 = (_CRYPT_TABLE[base + ch] ^ ((seed1 + seed2) & _MASK32)) & _MASK32
        seed2 = (ch + seed1 + seed2 + (seed2 << 5) + 3) & _MASK32
    return seed1


def _file_key(path: str) -> int:
    base = path.replace("/", "\\").rsplit("\\", 1)[-1]
    return mpq_hash(base, FILE_KEY)


def _next_key(key: int) -> int:
    """The ((!key).wrapping_shl(0x15).wrapping_add(0x1111_1111)) | (key >> 0x0B)
    update, evaluated -- as Rust does -- entirely against the key value from
    before this update (both the NOT+shift term and the `key >> 0x0B` term)."""
    shifted = (((~key) & _MASK32) << 0x15) & _MASK32
    return ((shifted + 0x11111111) & _MASK32) | (key >> 0x0B)


def _encrypt_words(words: list[int], key: int) -> list[int]:
    out = []
    seed = 0xEEEEEEEE
    for word in words:
        seed = (seed + _CRYPT_TABLE[0x400 + (key & 0xFF)]) & _MASK32
        cipher = (word ^ ((key + seed) & _MASK32)) & _MASK32
        out.append(cipher)
        seed = (word + seed + (seed << 5) + 3) & _MASK32
        key = _next_key(key)
    return out


def _decrypt_words(words: list[int], key: int) -> list[int]:
    """Only used by this module's own self-test (encrypt/decrypt inverse
    check) -- the archive we write is never read back through this."""
    out = []
    seed = 0xEEEEEEEE
    for word in words:
        seed = (seed + _CRYPT_TABLE[0x400 + (key & 0xFF)]) & _MASK32
        plain = (word ^ ((key + seed) & _MASK32)) & _MASK32
        out.append(plain)
        seed = (plain + seed + (seed << 5) + 3) & _MASK32
        key = _next_key(key)
    return out


def _validate_known_answers() -> None:
    a = mpq_hash(_HASH_TABLE_KEY, FILE_KEY)
    b = mpq_hash(_BLOCK_TABLE_KEY, FILE_KEY)
    if (a, b) != (0xC3AF3770, 0xEC83B3A3):
        raise AssertionError(
            f"MPQ crypt table/hash transcription error: "
            f"hash('(hash table)')={a:#010x} (want 0xc3af3770), "
            f"hash('(block table)')={b:#010x} (want 0xec83b3a3)"
        )
    plain = [(i * 0x01010101 + 7) & _MASK32 for i in range(64)]
    key = 0x12345678
    cipher = _encrypt_words(plain, key)
    if cipher == plain:
        raise AssertionError("MPQ encrypt self-test: cipher == plaintext (no-op cipher?)")
    roundtrip = _decrypt_words(cipher, key)
    if roundtrip != plain:
        raise AssertionError("MPQ encrypt/decrypt self-test: round-trip mismatch")


_validate_known_answers()


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


def _pack_words(words: list[int]) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


def _bytes_to_words(data: bytes) -> list[int]:
    assert len(data) % 4 == 0
    return list(struct.unpack(f"<{len(data) // 4}I", data))


def write_archive(path: str | Path, files: dict[str, bytes], *, hash_table_slack: int = 2) -> None:
    """Writes a minimal MPQ v0 archive at `path` containing `files`
    (internal archive path -> raw bytes, e.g. {"DBFilesClient\\\\Talent.dbc": b"..."}).
    Every file is stored SINGLE_UNIT and uncompressed."""
    names = list(files.keys())
    hash_table_size = _next_pow2(max(4, len(names) * hash_table_slack))

    header_size = 32
    file_offset = header_size
    block_entries = []  # (offset, packed_size, size, flags)
    file_blobs = []
    for name in names:
        data = files[name]
        block_entries.append((file_offset, len(data), len(data), FLAG_EXISTS | FLAG_SINGLE_UNIT))
        file_blobs.append(data)
        file_offset += len(data)

    hash_table_pos = file_offset
    block_table_pos = hash_table_pos + hash_table_size * 16

    # hash table: HASH_ENTRY_EMPTY-filled, then real entries placed by probing
    hash_slots = [(HASH_ENTRY_EMPTY, HASH_ENTRY_EMPTY, 0xFFFFFFFF, HASH_ENTRY_EMPTY) for _ in range(hash_table_size)]
    for block_index, name in enumerate(names):
        start = mpq_hash(name, TABLE_OFFSET) % hash_table_size
        name_a = mpq_hash(name, NAME_A)
        name_b = mpq_hash(name, NAME_B)
        i = start
        while hash_slots[i][0] != HASH_ENTRY_EMPTY:
            i = (i + 1) % hash_table_size
        # locale 0 (neutral), platform 0, packed into one u32 as locale|platform<<16
        hash_slots[i] = (name_a, name_b, 0x00000000, block_index)

    hash_words: list[int] = []
    for name_a, name_b, locale_platform, block_index in hash_slots:
        hash_words += [name_a, name_b, locale_platform, block_index]
    hash_bytes = _pack_words(_encrypt_words(hash_words, mpq_hash(_HASH_TABLE_KEY, FILE_KEY)))

    block_words: list[int] = []
    for offset, packed_size, size, flags in block_entries:
        block_words += [offset, packed_size, size, flags]
    block_bytes = _pack_words(_encrypt_words(block_words, mpq_hash(_BLOCK_TABLE_KEY, FILE_KEY)))

    archive_size = block_table_pos + len(block_bytes)
    header = struct.pack(
        "<4sIIHHIIII",
        MAGIC,
        header_size,
        archive_size,
        0,  # format_version 0
        0,  # sector_size_shift (unused -- every file here is SINGLE_UNIT)
        hash_table_pos,
        block_table_pos,
        hash_table_size,
        len(names),
    )
    assert len(header) == header_size, len(header)

    out = bytearray()
    out += header
    for blob in file_blobs:
        out += blob
    assert len(out) == hash_table_pos, (len(out), hash_table_pos)
    out += hash_bytes
    out += block_bytes
    assert len(out) == archive_size, (len(out), archive_size)

    Path(path).write_bytes(bytes(out))


def read_archive_file(path: str | Path, internal_path: str) -> bytes | None:
    """Reads one file back out of an archive written by write_archive().

    Exists because nothing else in this project can: mpq_source.py's mpyq
    refuses to even OPEN our archives, because write_archive deliberately
    emits no (listfile) member and mpyq requires one. That silently turned
    every one of our own deployed patches into "not found" for find_all()/
    resolve() -- a blind spot that made it impossible to verify what we had
    actually shipped to a client, as opposed to what we meant to.

    Only handles what write_archive produces: MPQ v0, files stored
    SINGLE_UNIT, uncompressed and unencrypted. Returns None if the archive
    has no such path. Not a general MPQ reader -- for a stock Blizzard
    archive, keep using mpq_source.py.
    """
    data = Path(path).read_bytes()
    magic, header_size, _archive_size, _fmt, _sector_shift, hash_pos, block_pos, hash_size, block_count = \
        struct.unpack_from("<4sIIHHIIII", data, 0)
    if magic != MAGIC:
        raise ValueError(f"{path}: not an MPQ archive (magic {magic!r})")

    hash_words = _decrypt_words(
        _bytes_to_words(data[hash_pos:hash_pos + hash_size * 16]),
        mpq_hash(_HASH_TABLE_KEY, FILE_KEY))
    block_words = _decrypt_words(
        _bytes_to_words(data[block_pos:block_pos + block_count * 16]),
        mpq_hash(_BLOCK_TABLE_KEY, FILE_KEY))

    want_a = mpq_hash(internal_path, NAME_A)
    want_b = mpq_hash(internal_path, NAME_B)
    slot = mpq_hash(internal_path, TABLE_OFFSET) % hash_size
    for _ in range(hash_size):  # linear probe, same as write_archive's placement
        name_a, name_b, _locale_platform, block_index = hash_words[slot * 4:slot * 4 + 4]
        if name_a == HASH_ENTRY_EMPTY:
            return None
        if (name_a, name_b) == (want_a, want_b):
            offset, packed_size, size, flags = block_words[block_index * 4:block_index * 4 + 4]
            if not flags & FLAG_EXISTS:
                return None
            if packed_size != size:
                raise NotImplementedError(
                    f"{path}: {internal_path} is compressed ({packed_size} -> {size}); "
                    "this reader only handles what write_archive emits")
            return data[offset:offset + size]
        slot = (slot + 1) % hash_size
    return None

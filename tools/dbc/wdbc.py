"""
Generic reader/writer for the WDBC binary format used by WoW client DBC files
across 1.12.1, 2.4.3, and 3.3.5a (pre-Cataclysm "WDBC" magic, fixed-width
4-byte fields, trailing string block).

Format reference: https://wowdev.wiki/DBC
    header: 'WDBC' magic, record_count u32, field_count u32, record_size u32,
            string_block_size u32
    records: record_count * record_size bytes, field_count 4-byte fields per record
    string_block: string_block_size bytes, null-terminated strings, referenced by
                  byte offset from fields typed 'string'/loc_string

Localized string fields ("loc_string" in our schemas) are NOT a single 4-byte
field pre-Cataclysm -- they are one string offset per client locale slot plus a
trailing flags bitmask, all 4 bytes each:
    - 1.12.1 (pre 2.1.0.6692): 8 locale slots + 1 flags = 9 x 4-byte fields (36 bytes)
    - 2.4.3 and 3.3.5a (post 2.1.0.6692): 16 locale slots + 1 flags = 17 x 4-byte
      fields (68 bytes)
This differs between our three target client builds, so locale_count must be
passed explicitly per build rather than assumed -- see LOCALE_COUNT below.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAGIC = b"WDBC"

# Locale slot count (excludes the trailing flags field) for loc_string fields,
# keyed by the client build that produced the DBC. Confirmed via wowdev.wiki:
# the locale slot count changed at client build 2.1.0.6692 (mid-TBC), so 2.4.3
# and 3.3.5a both use the later 16-slot layout while 1.12.1 uses the earlier
# 8-slot layout.
LOCALE_COUNT = {
    "1.12.1": 8,
    "2.4.3": 16,
    "3.3.5a": 16,
}

ENUS_LOCALE_INDEX = 0


@dataclass
class FieldSpec:
    name: str
    type: str  # 'int32' | 'uint32' | 'float32' | 'string' | 'loc_string'


Schema = list[FieldSpec]


def field_slot_count(f: FieldSpec, locale_count: int) -> int:
    """Number of 4-byte slots a field occupies in the fixed-width record."""
    if f.type == "loc_string":
        return locale_count + 1  # + flags
    return 1


def schema_slot_count(schema: Schema, locale_count: int) -> int:
    return sum(field_slot_count(f, locale_count) for f in schema)


@dataclass
class DbcFile:
    schema: Schema
    locale_count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    string_block: bytes = b"\x00"

    def get_string(self, offset: int) -> str:
        if offset == 0:
            return ""
        end = self.string_block.index(b"\x00", offset)
        return self.string_block[offset:end].decode("utf-8")


class StringBlockBuilder:
    """Appends new strings onto an existing DBC string block, interning
    duplicates (returns the same offset for a string already present or
    already appended this session, matching how these files are normally
    produced). Needed whenever a new/modified row introduces a string that
    isn't just copied verbatim from an existing row's offset -- e.g. a
    'string'/loc_string field built fresh rather than carried over from a
    source row of a DIFFERENT build (whose string block is a different
    file, so its offsets are meaningless against ours)."""

    def __init__(self, existing_block: bytes):
        self.block = bytearray(existing_block)
        self._offset_by_string: dict[str, int] = {}
        # index existing strings so appends can still dedupe against them
        i = 0
        while i < len(self.block):
            end = self.block.index(b"\x00", i)
            s = bytes(self.block[i:end]).decode("utf-8")
            if s:
                self._offset_by_string.setdefault(s, i)
            i = end + 1

    def intern(self, s: str) -> int:
        if not s:
            return 0
        if s in self._offset_by_string:
            return self._offset_by_string[s]
        offset = len(self.block)
        self.block += s.encode("utf-8") + b"\x00"
        self._offset_by_string[s] = offset
        return offset

    def build(self) -> bytes:
        return bytes(self.block)


# Matches the bitmask stock 3.3.5a/2.4.3 loc_string rows use when only the
# enUS slot (index 0) is populated -- confirmed against a real TalentTab.dbc
# row. Locale flag semantics beyond "which slots have data" aren't otherwise
# used by this project; reused as-is for new rows built from scratch.
STOCK_ENUS_ONLY_LOC_FLAGS = 0xFEFEFE


def new_loc_string(builder: StringBlockBuilder, enus_text: str, locale_count: int) -> dict:
    offsets = [builder.intern(enus_text)] + [0] * (locale_count - 1)
    return {"offsets": offsets, "enUS": enus_text, "flags": STOCK_ENUS_ONLY_LOC_FLAGS}


def new_string_field(builder: StringBlockBuilder, text: str) -> dict:
    offset = builder.intern(text)
    return {"offset": offset, "value": text}


def read_dbc(path: str | Path, schema: Schema, locale_count: int) -> DbcFile:
    data = Path(path).read_bytes()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: not a WDBC file (magic={data[:4]!r})")

    record_count, field_count, record_size, string_block_size = struct.unpack_from(
        "<IIII", data, 4
    )

    expected_slots = schema_slot_count(schema, locale_count)
    if field_count != expected_slots:
        raise ValueError(
            f"{path}: header field_count={field_count} does not match schema "
            f"({expected_slots} slots for {len(schema)} fields @ locale_count="
            f"{locale_count}). Schema is wrong for this file/build."
        )
    if record_size != field_count * 4:
        raise ValueError(
            f"{path}: record_size={record_size} != field_count*4 ({field_count * 4})"
        )

    records_start = 20
    string_block_start = records_start + record_count * record_size
    string_block = data[string_block_start : string_block_start + string_block_size]

    rows: list[dict[str, Any]] = []
    for i in range(record_count):
        rec_off = records_start + i * record_size
        row: dict[str, Any] = {}
        off = rec_off
        for f in schema:
            if f.type == "int32":
                (row[f.name],) = struct.unpack_from("<i", data, off)
                off += 4
            elif f.type == "uint32":
                (row[f.name],) = struct.unpack_from("<I", data, off)
                off += 4
            elif f.type == "float32":
                (row[f.name],) = struct.unpack_from("<f", data, off)
                off += 4
            elif f.type == "string":
                (soff,) = struct.unpack_from("<I", data, off)
                row[f.name] = {"offset": soff}
                off += 4
            elif f.type == "loc_string":
                offsets = list(
                    struct.unpack_from(f"<{locale_count}I", data, off)
                )
                off += locale_count * 4
                (flags,) = struct.unpack_from("<I", data, off)
                off += 4
                row[f.name] = {"offsets": offsets, "flags": flags}
            else:
                raise ValueError(f"unknown field type {f.type!r} for {f.name}")
        rows.append(row)

    dbc = DbcFile(schema=schema, locale_count=locale_count, rows=rows, string_block=string_block)

    # decode convenience strings after string_block is attached
    for row in rows:
        for f in schema:
            if f.type == "string":
                row[f.name]["value"] = dbc.get_string(row[f.name]["offset"])
            elif f.type == "loc_string":
                enus_off = row[f.name]["offsets"][ENUS_LOCALE_INDEX]
                row[f.name]["enUS"] = dbc.get_string(enus_off)

    return dbc


def write_dbc(path: str | Path, dbc: DbcFile) -> None:
    """Writes rows back using each row's raw offsets/flags as-is (no string
    block rebuilding). Round-trips a file byte-for-byte if nothing in
    dbc.rows was modified -- used by the Phase 0 round-trip test. Building
    new/modified string content requires a StringBlockBuilder pass before
    calling this (see build_patch, added when that tool is built)."""
    field_count = schema_slot_count(dbc.schema, dbc.locale_count)
    record_size = field_count * 4
    record_count = len(dbc.rows)

    buf = bytearray()
    for row in dbc.rows:
        for f in dbc.schema:
            v = row[f.name]
            if f.type == "int32":
                buf += struct.pack("<i", v)
            elif f.type == "uint32":
                buf += struct.pack("<I", v)
            elif f.type == "float32":
                buf += struct.pack("<f", v)
            elif f.type == "string":
                buf += struct.pack("<I", v["offset"])
            elif f.type == "loc_string":
                buf += struct.pack(f"<{dbc.locale_count}I", *v["offsets"])
                buf += struct.pack("<I", v["flags"])
            else:
                raise ValueError(f"unknown field type {f.type!r} for {f.name}")

    header = struct.pack(
        "<4sIIII", MAGIC, record_count, field_count, record_size, len(dbc.string_block)
    )
    Path(path).write_bytes(header + bytes(buf) + dbc.string_block)

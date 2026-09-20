"""
Row-level merge of several mods' edits to the same 3.3.5a DBC, without a
per-file schema.

The problem this solves: mod-uac, Prestige-and-Draft-Mode, Delves and
mod-individual-progression each ship their own copy of e.g.
SkillRaceClassInfo.dbc / CharBaseInfo.dbc, every one of them "stock plus my
rows". Installing them as instructed (copy over Data/dbc, drop an MPQ in the
client) means whichever was copied last silently wins and the others break.
So instead: take the stock file as the base, diff each mod's copy against it,
and layer the resulting row additions/overrides into one output that both
the server (docker-compose bind mount) and the client (patch-Z.mpq) load.

Why schema-less: wdbc.py's typed schemas cover the four DBCs the era-talent
work needed. This has to handle ~15 more and the exact field semantics don't
matter for a merge -- only three things do, all inferable from the stock
file itself:
  - which 4-byte columns are string-block offsets (must be re-based into the
    merged string block instead of copied as raw ints),
  - which are floats (only matters when parsing CSV input),
  - the record key (column 0 for normal files; the whole record for the
    few byte-packed files like CharBaseInfo where record_size != 4*fields).
String detection: every value in the column is 0 or a valid offset that sits
right after a NUL in the string block, with >= 2 distinct non-zero values
(rules out 0/1 flag columns, whose 1 would otherwise "point at" the first
string). Float detection: every non-zero value has an IEEE exponent byte in
the range of sane magnitudes (~1e-5..1e15 either sign); plausible ints never
land there (1.0f is 1065353216). Cross-checked against AzerothCore's own
DBCfmt.h for every file we actually merge -- see build_mod_dbcs.py.

Inputs a layer can come from:
  - another .dbc with the same field count (a mod's edited copy): rows whose
    key isn't in the base are added; with policy "override", rows that differ
    from base replace it too. Strings are resolved from that file's own block.
  - a WDBX Editor CSV export (what Delves ships): header row = column names,
    one row per record. Column count must match the base. `*_Lang_*` columns
    (other than `_Lang_Mask`) are strings regardless of the heuristic; text
    that isn't a number is a string; the rest follows the base's types.
"""
from __future__ import annotations

import csv
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")

STRING, INT, FLOAT = "s", "i", "f"

# Column names WDBX uses for plain (non-localized) string columns in the 3.3.5a
# files Delves touches. Anything else non-numeric in a CSV is also a string.
_CSV_STRING_NAMES = {"Directory", "Name", "FileName", "SetName", "File", "Path", "Difficultystring"}


@dataclass
class RawDbc:
    field_count: int
    record_size: int
    records: list[bytes]
    string_block: bytes

    @property
    def packed(self) -> bool:
        """True for byte-packed layouts (CharBaseInfo, CharStartOutfit) where a
        record isn't just field_count uint32s; such files are merged as opaque
        byte records keyed on their leading bytes."""
        return self.record_size != 4 * self.field_count

    def string_at(self, offset: int) -> str:
        end = self.string_block.find(b"\0", offset)
        if end < 0:
            end = len(self.string_block)
        return self.string_block[offset:end].decode("utf-8", "replace")


def read_raw(path: str | Path) -> RawDbc:
    data = Path(path).read_bytes()
    magic, nrec, nfld, rsize, ssize = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"{path}: not a WDBC file (magic {magic!r})")
    body = HEADER.size
    recs = [data[body + i * rsize: body + (i + 1) * rsize] for i in range(nrec)]
    sb = data[body + nrec * rsize: body + nrec * rsize + ssize]
    return RawDbc(nfld, rsize, recs, sb)


def _unpack(dbc: RawDbc, rec: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{dbc.field_count}I", rec)


def detect_types(dbc: RawDbc) -> list[str]:
    """Per-column STRING/INT/FLOAT for a non-packed file, from its own data."""
    if dbc.packed:
        raise ValueError("detect_types is for uint32-field files only")
    cols = list(zip(*(_unpack(dbc, r) for r in dbc.records))) if dbc.records else [()] * dbc.field_count
    sb, ssize = dbc.string_block, len(dbc.string_block)
    types: list[str] = []
    for c in cols:
        nonzero = {v for v in c if v}
        is_str = (
            len(nonzero) >= 2
            and all(v < ssize and sb[v - 1] == 0 for v in nonzero)
        )
        if is_str:
            types.append(STRING)
            continue
        is_float = bool(nonzero) and all(
            0x38 <= ((v >> 24) & 0x7F) <= 0x4F for v in nonzero
        )
        types.append(FLOAT if is_float else INT)
    return types


# ---------------------------------------------------------------------------
# typed rows: tuple of int | float | str per column, key = row[0]

Row = tuple


def rows_from_dbc(dbc: RawDbc, types: list[str]) -> dict[int, Row]:
    out: dict[int, Row] = {}
    for rec in dbc.records:
        raw = _unpack(dbc, rec)
        row = tuple(
            dbc.string_at(v) if t == STRING else
            struct.unpack("<f", struct.pack("<I", v))[0] if t == FLOAT else v
            for v, t in zip(raw, types)
        )
        out[raw[0]] = row
    return out


def rows_from_csv(path: str | Path, types: list[str]) -> tuple[dict[int, Row], list[str]]:
    """Returns (rows, effective column types) -- the CSV can prove a column
    is a string (localized-name columns, plain text cells) where the base
    file couldn't (all its rows had 0 there, e.g. unused locale slots)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
    header, body = reader[0], [r for r in reader[1:] if any(cell.strip() for cell in r)]
    if len(header) != len(types):
        raise ValueError(f"{path}: {len(header)} CSV columns, base file has {len(types)} fields")
    eff = list(types)
    for i, name in enumerate(header):
        if ("_Lang_" in name and not name.endswith("_Lang_Mask")) or name in _CSV_STRING_NAMES:
            eff[i] = STRING
    for r in body:
        if len(r) != len(types):
            raise ValueError(f"{path}: row {r[0]!r} has {len(r)} cells, expected {len(types)}")
        for i, cell in enumerate(r):
            if eff[i] != STRING and cell != "" and not _is_number(cell):
                eff[i] = STRING  # plainly text: trust the data over the heuristic
    out: dict[int, Row] = {}
    for r in body:
        vals = []
        for cell, t in zip(r, eff):
            if t == STRING:
                vals.append(cell)
            elif t == FLOAT:
                vals.append(float(cell or 0))
            elif "." in cell or "e" in cell.lower():
                vals.append(float(cell))
            else:
                vals.append(int(cell or 0) & 0xFFFFFFFF)
        out[int(vals[0])] = tuple(vals)
    return out, eff


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------

@dataclass
class MergeReport:
    added: list[int] = field(default_factory=list)
    overridden: list[int] = field(default_factory=list)
    skipped_existing: list[int] = field(default_factory=list)


class Merger:
    """Base + layers -> merged file. One instance per output DBC."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self.base = read_raw(base_path)
        if self.base.packed:
            self.types = None
            # key = whole record when it's tiny (CharBaseInfo: race+class), else
            # the leading uint32 (CharStartOutfit: race/class/gender/outfit bytes)
            self._key = (lambda r: r) if self.base.record_size <= 4 else (lambda r: r[:4])
            self.rows: dict = {self._key(r): r for r in self.base.records}
            if len(self.base.string_block) > 1:
                raise ValueError(f"{base_path}: byte-packed layout with a string block -- unsupported")
        else:
            self.types = detect_types(self.base)
            self.rows = rows_from_dbc(self.base, self.types)
            self.base_order = list(self.rows)  # file order, before any layer
        self.base_keys = set(self.rows)
        self.reports: dict[str, MergeReport] = {}

    def layer_dbc(self, name: str, path: str | Path, policy: str = "add") -> MergeReport:
        other = read_raw(path)
        if other.field_count != self.base.field_count or other.record_size != self.base.record_size:
            raise ValueError(
                f"{path}: layout {other.field_count}x{other.record_size} doesn't match base "
                f"{self.base.field_count}x{self.base.record_size}")
        if self.base.packed:
            rows = {self._key(r): r for r in other.records}
        else:
            self._upgrade_types(detect_types(other))
            rows = rows_from_dbc(other, self.types)
        return self._apply(name, rows, policy)

    def layer_csv(self, name: str, path: str | Path, policy: str = "add") -> MergeReport:
        if self.base.packed:
            raise ValueError("CSV layers need a uint32-field base")
        rows, eff = rows_from_csv(path, self.types)
        self._upgrade_types(eff)
        return self._apply(name, rows, policy)

    def _upgrade_types(self, other_types: list[str]) -> None:
        """A column the base file couldn't type (every row 0 -> INT) may be
        proven a STRING by a layer that actually fills it (a mod's non-enUS
        locale slot, a CSV name column). Promote it -- for base rows 0 and ""
        are the same offset anyway. Any other disagreement is a real layout
        mismatch and is refused rather than guessed."""
        for i, (mine, theirs) in enumerate(zip(self.types, other_types)):
            if mine == theirs or theirs == INT:
                continue
            if mine == INT and all(row[i] == 0 for row in self.rows.values()):
                self.types[i] = theirs
                blank = "" if theirs == STRING else 0.0
                self.rows = {k: tuple(blank if j == i else v for j, v in enumerate(row))
                             for k, row in self.rows.items()}
            else:
                raise ValueError(f"{self.base_path.name}: column {i} is {mine!r} in base but "
                                 f"{theirs!r} in a layer")

    def _apply(self, name: str, rows: dict, policy: str) -> MergeReport:
        if policy not in ("add", "override"):
            raise ValueError(policy)
        rep = MergeReport()
        for key, row in rows.items():
            if key not in self.rows:
                self.rows[key] = row
                rep.added.append(key)
            elif self.rows[key] == row:
                continue
            elif policy == "override":
                self.rows[key] = row
                rep.overridden.append(key)
            else:
                rep.skipped_existing.append(key)
        self.reports[name] = rep
        return rep

    def _base_sort_key(self):
        """Row ordering that matches the base file. The client binary-searches
        some DBCs by a field other than the id -- SkillRaceClassInfo is stored
        sorted by skillID -- and a merged file re-sorted by id makes every
        lookup miss (in-game: the Skills window lists nothing but languages).
        Find the first field the base is sorted by (ties broken by id) and sort
        the output the same way; a base with no sortable field keeps its own
        order with new rows appended, which is what mod patches do too."""
        base_rows = [self.rows[k] for k in self.base_order]
        for f in range(len(self.types)):
            if self.types[f] == STRING:
                continue
            key = lambda r, f=f: (r[f], r[0])
            if all(key(a) <= key(b) for a, b in zip(base_rows, base_rows[1:])):
                return lambda k, key=key: key(self.rows[k])
        pos = {k: i for i, k in enumerate(self.base_order)}
        return lambda k: (0, pos[k]) if k in pos else (1, k)

    def write(self, out_path: str | Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.base.packed:
            keys = sorted(self.rows, key=lambda k: bytes(k))
            body = b"".join(self.rows[k] for k in keys)
            sb = self.base.string_block or b"\0"
        else:
            keys = sorted(self.rows, key=self._base_sort_key())
            sb_parts = [b"\0"]
            offsets: dict[str, int] = {"": 0}
            size = 1

            def intern(s: str) -> int:
                nonlocal size
                if s in offsets:
                    return offsets[s]
                enc = s.encode("utf-8") + b"\0"
                offsets[s] = size
                sb_parts.append(enc)
                size += len(enc)
                return offsets[s]

            recs = []
            for k in keys:
                packed = []
                for v, t in zip(self.rows[k], self.types):
                    if t == STRING:
                        packed.append(intern(v if isinstance(v, str) else str(v)))
                    elif isinstance(v, float):
                        packed.append(struct.unpack("<I", struct.pack("<f", v))[0])
                    else:
                        packed.append(int(v) & 0xFFFFFFFF)
                recs.append(struct.pack(f"<{self.base.field_count}I", *packed))
            body = b"".join(recs)
            sb = b"".join(sb_parts)
        header = HEADER.pack(MAGIC, len(keys), self.base.field_count, self.base.record_size, len(sb))
        out_path.write_bytes(header + body + sb)

    def summary(self) -> str:
        lines = [f"{self.base_path.name}: base {len(self.base_keys)} rows -> {len(self.rows)} rows"]
        if self.types:
            lines.append("  layout: " + "".join(self.types))
        for name, rep in self.reports.items():
            bits = [f"+{len(rep.added)}"]
            if rep.overridden:
                bits.append(f"~{len(rep.overridden)}")
            if rep.skipped_existing:
                bits.append(f"kept-base-for {len(rep.skipped_existing)}")
            lines.append(f"  {name}: " + " ".join(bits))
        return "\n".join(lines)

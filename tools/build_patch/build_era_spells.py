"""
Builds per-era COPIES of class spells into the WotLK Spell.dbc, so two
characters on the same realm can cast genuinely different versions of the
same spell.

Why this works, and why it is much cheaper than the era-talent equivalent:
a spellbook is per-character server state (character_spell ->
SMSG_INITIAL_SPELLS), not a shared file the client renders wholesale the
way it renders Talent.dbc. The client simply looks up whatever spell ids it
is told the character knows. So if Spell.dbc contains BOTH a Vanilla
Fireball and a WotLK Fireball under different ids, each character can hold
the authentic one -- correct tooltip, mana cost, cast time and damage --
with no custom client UI at all. (build_era_tree.py needed dedicated tab
ids AND NekoTalentUI precisely because talents do not work like this.)

Id allocation, same arithmetic-offset shape as build_era_tree.py's
talent ids:

    Vanilla clone of spell N  ->  N + 300_000
    TBC clone of spell N      ->  N + 400_000

Kept deliberately modest: sSpellStore and SpellMgr's mSpellInfoMap are flat
arrays sized max_id + 1 (DBCStore.h GetNumRows / SpellMgr.cpp
LoadSpellInfoStore), and the era-talent work already found that very large
offsets (900,000) break DBCStorage::LookupEntry. 400_000 puts the top id at
~481k, under 4 MB of pointer table per store. See ERA_CONFIG for why these
are not the 100k/200k this started at.

Two different strategies per spell, and the split is the main thing keeping
this safe:

  * The spell still exists in WotLK (the large majority). The clone starts
    as a copy of the WOTLK row and only the gameplay fields that actually
    differ are overwritten from the era row. That keeps WotLK's own
    SpellVisualID/SpellIconID, its string-block offsets, and -- the part
    that matters most -- its SpellClassSet/SpellClassMask, so talent
    spellmods and the core's own family-mask logic still match the clone.
  * The spell was deleted by WotLK. There is no WotLK row to build on, so
    the whole row is ported wholesale from the era client (port_era_row).
    Two kinds, handled differently:

      - Ones a character LEARNS (Curse of Recklessness, Elune's Grace,
        Turn Undead, the ranks WotLK collapsed away): ported at the ERA
        id, like every other class spell, so a Vanilla character's class
        spells are uniformly 300000-range. Putting them back at their
        original id would make them the one kind of class spell shared
        between eras, which the gate could not separate. Their
        SkillLineAbility rows come from the era's own file, since WotLK
        has none to mirror.
      - Ones only REFERENCED by another spell (a trigger or aura
        condition), such as the damage proc behind Vanilla Lightning
        Shield: ported at their original id, because the referring row
        names them by that id.

    "WotLK has nothing there" is judged against the realm, not just the
    client file: AzerothCore re-adds a number of dropped spells
    SERVERSIDE through the `spell_dbc` world table (Execute's trigger,
    26651, among them), and those already resolve, so porting over one
    would only fight the core.

Index fields are remapped BY VALUE, never copied. CastingTimeIndex,
DurationIndex, RangeIndex and EffectRadiusIndex_* are indices into small
per-build side tables whose ids do not line up across builds. This tool
looks up the era value, finds the WotLK row that means the same thing, and
appends a new row to the WotLK table when nothing matches -- which is why
it can also emit patched SpellCastTimes/SpellDuration/SpellRange/
SpellRadius DBCs alongside Spell.dbc.

What is deliberately NOT taken from the era row: spell visuals and icons,
and the spell family fields. Name and tooltip ARE the era's (see
build_clone), with tokens naming other spells pointed at their era copies. --tag-names appends an era marker to the clone's
name; that is a TESTING aid, not for a real build.

Usage:
    # Spike: a handful of named spells, TBC era only
    python build_era_spells.py --wotlk-root "D:\\...\\3.3.5a" \\
        --tbc-root "D:\\...\\2.4.3" \\
        --base-spell data/inputs/pre-era-spells-Spell.dbc \\
        --only 172,11366,348 --tag-names \\
        --out-dir data/generated

    # Everything: every class spell of every era passed
    python build_era_spells.py --wotlk-root "D:\\...\\3.3.5a" \\
        --tbc-root "D:\\...\\2.4.3" --base-spell data/inputs/pre-era-spells-Spell.dbc \\
        --out-dir data/generated

Runs AFTER port_era_spells.py in the pipeline -- its output (the WotLK
Spell.dbc plus the era talent rank spells it rescued) is this tool's input,
so a clone can be built on a row that port_era_spells put there.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dbc"))
from wdbc import (  # noqa: E402
    LOCALE_COUNT,
    DbcFile,
    StringBlockBuilder,
    new_loc_string,
    read_dbc,
    write_dbc,
)
from schemas import BUILD_SCHEMAS  # noqa: E402
import mpq_source  # noqa: E402


ERA_CONFIG = {
    # Mirrors build_era_tree.py's ERA_CONFIG. id_offset is added to the
    # WotLK spell id to get that era's clone id.
    #
    # 300k/400k, NOT the 100k/200k this started at. 100000-200000 is the
    # conventional band for custom SERVERSIDE spells, and the live realm
    # already had six of them sitting exactly on top of era clone ids:
    # AzerothCore's own 100001/100099/100100/100101/100102 (Drain Soul,
    # Stairway Event, Twin Val'kyr, arena gear scaling) and mod-transmog's
    # 200100. Those load from the `spell_dbc` world table AFTER Spell.dbc,
    # so each one would have silently overridden a clone -- 100100 and
    # 200100 are the Vanilla and TBC copies of Charge. Dodging those six
    # ids individually would not help: the band belongs to that convention
    # and any core update or new module can add more. --reserved-ids is
    # checked on every build so a future collision fails loudly instead of
    # quietly replacing a spell.
    "1.12.1": {"label": "Vanilla", "id_offset": 300_000, "root_arg": "vanilla_root"},
    "2.4.3": {"label": "TBC", "id_offset": 400_000, "root_arg": "tbc_root"},
}

# Fields the clone keeps from the WOTLK row even when the era row differs.
# Everything else that exists in both schemas is overridden from the era.
KEEP_FROM_WOTLK = {
    "ID",
    # Presentation: era icons/visuals are ids into that build's own
    # SpellVisual/SpellIcon tables and would point at the wrong art here.
    "SpellVisualID_0", "SpellVisualID_1", "SpellIconID", "ActiveIconID",
    # Strings. Every string field is listed here so the generic copy loop
    # never touches one: an era row's loc_string holds offsets into ITS
    # build's string block, and Vanilla has 8 locale slots where WotLK has
    # 16, so copying the dict across produces a row that cannot even be
    # packed. build_clone re-interns the era's own text afterwards.
    "Name_lang", "NameSubtext_lang", "Description_lang", "AuraDescription_lang",
    # Spell family. Talent spellmods ("Improved X by Y%") and a good deal
    # of core logic match spells by family + mask, so a clone has to keep
    # WotLK's, not the era's (whose bits were reassigned between builds --
    # the same caveat port_era_spells.py documents).
    "SpellClassSet", "SpellClassMask_0", "SpellClassMask_1",
    # School/defense/prevention changed representation between builds more
    # than they changed meaning; WotLK's are what the core expects.
    "SchoolMask", "DefenseType", "PreventionType", "StanceBarOrder", "SpellPriority",
}

# field name -> the side table its value indexes into
INDEX_FIELDS = {
    "CastingTimeIndex": "SpellCastTimes.dbc",
    "DurationIndex": "SpellDuration.dbc",
    "RangeIndex": "SpellRange.dbc",
    "EffectRadiusIndex_0": "SpellRadius.dbc",
    "EffectRadiusIndex_1": "SpellRadius.dbc",
    "EffectRadiusIndex_2": "SpellRadius.dbc",
}

SPELL_AURA_ADD_FLAT_MODIFIER = 107
SPELL_AURA_ADD_PCT_MODIFIER = 108
SPELLMOD_AURAS = {SPELL_AURA_ADD_FLAT_MODIFIER, SPELL_AURA_ADD_PCT_MODIFIER}
EFFECT_MASK_FIELDS = ["EffectSpellClassMaskA", "EffectSpellClassMaskB", "EffectSpellClassMaskC"]

# Fields on a clone that name ANOTHER spell. An era row can point at a spell
# WotLK deleted, which would leave the clone silently doing nothing (Vanilla
# Lightning Shield's damage proc, Execute's trigger, ...), so these drive the
# transitive port pass.
SPELL_REF_FIELDS = [
    "EffectTriggerSpell_0", "EffectTriggerSpell_1", "EffectTriggerSpell_2",
    "CasterAuraSpell", "TargetAuraSpell", "ExcludeCasterAuraSpell", "ExcludeTargetAuraSpell",
]

# Every playable race each era had, as a RaceMask: Vanilla races 1-8, TBC
# adds Blood Elf (10) and Draenei (11).
ERA_ALL_RACES = {"Vanilla": 0x0FF, "TBC": 0x6FF}

# Ids WotLK reused for a different spell even though the effect layout
# happens to match, so is_reused_id's layout test cannot see it. Each was
# confirmed by the WotLK world rows sitting on the id (a script or proc
# written for the WotLK spell): Empowered Fireball -> Empowered Fire (TBC),
# Sanctified Judgement -> Judgements of the Wise (TBC), Spirit Tap ->
# Improved Spirit Tap, Judgement -> Judgement of Light (TBC).
REUSED_SAME_LAYOUT = {31656, 31657, 31658, 31876, 31877, 31878, 15337, 15338, 20271}


def effect_layout(row: dict) -> tuple:
    return tuple((row[f"Effect_{i}"], row[f"EffectAura_{i}"]) for i in range(3))


SPELL_EFFECT_DUMMY = 3
SPELL_EFFECT_HEAL = 10
SPELL_EFFECT_SCRIPT_EFFECT = 77

# `$12345s1`, `$/87;20187s3`, `${$20335m1*2}`: a tooltip token naming another
# spell by id. Group 1 is everything before the id, so only the id changes.
SPELL_REF_TOKEN = re.compile(r"(\$(?:[/*][\d.]+;)?)(\d+)(?=[a-zA-Z])")


def remap_era_text_refs(text: str, era_ids: dict[int, int]) -> str:
    """Points tooltip tokens that name another spell at that spell's copy in
    the same era. Vanilla Seal of Righteousness r2 reads "$/87;20280s3": 20280
    is a spell WotLK deleted, so the client printed the token raw, and Seal of
    the Crusader's "$21183s1" read WotLK's Heart of the Crusader (1) instead
    of the era's Judgement of the Crusader. A spell with no era copy keeps
    its id, which is then the shared spell the era uses too."""
    return SPELL_REF_TOKEN.sub(lambda m: m.group(1) + str(era_ids.get(int(m.group(2)), int(m.group(2)))), text)


def is_reused_id(spell_id: int, era_row: dict, wotlk_row: dict) -> bool:
    """Whether WotLK gave this id to a DIFFERENT spell than the era had.

    Blizzard reused ids in 3.0 when it rebuilt the talent trees and
    retired old ranks: Vanilla Ice Block (11958) is WotLK Cold Snap, Death
    Wish (12328) is Sweeping Strikes, Wing Clip ranks 2-3 (14267/14268) are
    the battleground flags. Cloning such a row keeps WotLK's name, tooltip,
    family masks and -- through build_era_spell_sql.py -- WotLK's scripts
    and procs, all of which belong to the other spell: a Vanilla Ice Block
    that shows as "Cold Snap" and runs Cold Snap's script. So these are
    ported wholesale instead, exactly like spells WotLK deleted.

    The test is a changed name AND a changed effect layout. A name change
    alone is usually a pure rename (Blessing -> Hand of Protection, Swipe
    -> Swipe (Bear)) whose WotLK world rows are still right; a layout
    change alone is the same ability evolving (Renew gained an effect). Both
    together mean the row describes something else, and where that still
    leaves an evolved ability (Blessing of Salvation's 5-minute buff vs
    Hand of Salvation's 10 seconds), porting it whole is the era-authentic
    answer anyway. REUSED_SAME_LAYOUT covers the few that share a layout.
    """
    if spell_id in REUSED_SAME_LAYOUT:
        return True
    same_name = era_row["Name_lang"]["enUS"].strip().casefold() == wotlk_row["Name_lang"]["enUS"].strip().casefold()
    return not same_name and effect_layout(era_row) != effect_layout(wotlk_row)


# The value columns that decide whether two rows of a side table mean the
# same thing. Everything else in those rows is an id or a display string.
INDEX_VALUE_FIELDS = {
    "SpellCastTimes.dbc": ["Base", "PerLevel", "Minimum"],
    "SpellDuration.dbc": ["Duration", "DurationPerLevel", "MaxDuration"],
    "SpellRadius.dbc": ["Radius", "RadiusPerLevel", "RadiusMax"],
    # SpellRange widened Min/Max to [2] in WotLK (friendly/hostile split);
    # a Vanilla/TBC row's single value maps onto both, handled in
    # IndexRemapper.
    "SpellRange.dbc": ["RangeMin_0", "RangeMin_1", "RangeMax_0", "RangeMax_1", "Flags"],
}


def load_from_client(build: str, filename: str, root: Path, tmp_dir: Path) -> DbcFile:
    schema = BUILD_SCHEMAS[build][filename]
    archive, data = mpq_source.resolve(root, filename)
    print(f"  {build} {filename}: resolved from {archive}", file=sys.stderr)
    path = tmp_dir / f"{build}-{filename}"
    path.write_bytes(data)
    return read_dbc(path, schema, LOCALE_COUNT[build])


class IndexRemapper:
    """Translates a side-table index from a source build into the WotLK
    table, matching on the row's VALUES rather than its id. Appends a new
    WotLK row when the era value has no equivalent, so a Vanilla-only cast
    time or duration is still expressible."""

    def __init__(self, filename: str, wotlk: DbcFile):
        self.filename = filename
        self.wotlk = wotlk
        self.value_fields = INDEX_VALUE_FIELDS[filename]
        self.appended = 0
        self._by_value: dict[tuple, int] = {}
        for row in wotlk.rows:
            self._by_value.setdefault(self._key(row), row["ID"])
        self._next_id = max((r["ID"] for r in wotlk.rows), default=0) + 1

    def _key(self, row: dict) -> tuple:
        return tuple(row[f] for f in self.value_fields)

    def _era_key(self, era_row: dict) -> tuple:
        if self.filename != "SpellRange.dbc":
            return tuple(era_row[f] for f in self.value_fields)
        # Vanilla/TBC store one RangeMin and one RangeMax; WotLK splits each
        # into [hostile, friendly]. Same range for both is what WotLK's own
        # rows carrying a pre-WotLK range look like.
        return (era_row["RangeMin"], era_row["RangeMin"],
                era_row["RangeMax"], era_row["RangeMax"], era_row["Flags"])

    def remap(self, era_index: int, era_table: DbcFile) -> int:
        if era_index == 0:
            return 0
        era_row = next((r for r in era_table.rows if r["ID"] == era_index), None)
        if era_row is None:
            # A dangling index in the source data; 0 is the client's own
            # "none" and is what a missing row degrades to safely.
            print(f"    warning: {self.filename} index {era_index} missing from source build", file=sys.stderr)
            return 0
        key = self._era_key(era_row)
        if key in self._by_value:
            return self._by_value[key]
        new_id = self._next_id
        self._next_id += 1
        # A fresh row of WotLK's own layout. String fields need the shape
        # write_dbc packs (offset dict / offsets+flags dict), not a bare 0 --
        # offset 0 is the string block's leading NUL, i.e. the empty string,
        # which is right for the display name of a range row nothing shows.
        new_row = {}
        for f in self.wotlk.schema:
            if f.type == "loc_string":
                new_row[f.name] = {"offsets": [0] * self.wotlk.locale_count, "enUS": "", "flags": 0}
            elif f.type == "string":
                new_row[f.name] = {"offset": 0, "value": ""}
            elif f.type == "float32":
                new_row[f.name] = 0.0
            else:
                new_row[f.name] = 0
        new_row["ID"] = new_id
        for i, f in enumerate(self.value_fields):
            new_row[f] = key[i]
        self.wotlk.rows.append(new_row)
        self._by_value[key] = new_id
        self.appended += 1
        return new_id


def port_era_row(
    era_row: dict,
    new_id: int,
    *,
    era: str,
    remappers: dict[str, IndexRemapper],
    era_tables: dict[str, DbcFile],
    strings: StringBlockBuilder,
    locale_count: int,
) -> dict:
    """Builds a whole WotLK row out of an era row, for a spell WotLK has no
    copy of at all.

    Same job as port_era_spells.py's convert_row, which does this for the
    talent rank spells WotLK deleted -- but three things here are handled
    that that one does not, because they did not come up for talent ranks:

      * Vanilla has a School INDEX where TBC/WotLK have a SchoolMask
        bitfield, so a straight name-keyed copy would leave a ported
        Vanilla spell with no school at all.
      * The index fields are remapped by value, not carried over raw.
      * Vanilla's EffectDicePerLevel is a float where TBC's is an int.

    Worth folding back into one shared converter -- deliberately not done
    mid-stream, since port_era_spells.py is load-bearing for the era talent
    trees that already work.
    """
    schema = BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"]
    out: dict = {}
    for f in schema:
        if f.type == "loc_string":
            src = era_row.get(f.name)
            out[f.name] = new_loc_string(strings, src["enUS"] if src else "", locale_count)
        elif f.name in era_row:
            out[f.name] = era_row[f.name]
        else:
            out[f.name] = 0.0 if f.type == "float32" else 0
    out["ID"] = new_id
    # Vanilla/TBC store these as scalars; WotLK widened both to [2].
    out["ShapeshiftMask_0"] = era_row["ShapeshiftMask"]
    out["ShapeshiftExclude_0"] = era_row["ShapeshiftExclude"]
    if era == "1.12.1":
        # School index (0 physical .. 6 arcane) -> WotLK's SchoolMask bit.
        out["SchoolMask"] = 1 << era_row["School"]
    for name, table in INDEX_FIELDS.items():
        out[name] = remappers[table].remap(era_row[name], era_tables[table])
    # A per-effect spellmod mask lives in EffectItemType pre-WotLK; WotLK
    # moved it into its own 96-bit EffectSpellClassMask{A,B,C} (first word).
    for i in range(3):
        if era_row[f"EffectAura_{i}"] in SPELLMOD_AURAS:
            out[f"{EFFECT_MASK_FIELDS[i]}_0"] = era_row[f"EffectItemType_{i}"]
            out[f"EffectItemType_{i}"] = 0
    return out


def build_skill_line_abilities(
    base_sla: DbcFile,
    id_map: dict[str, dict[str, int]],
    era_offsets: dict[str, int],
    era_sla: dict[str, dict[int, list[dict]]],
    valid_skill_lines: set[int],
    ported: dict[str, set[int]],
) -> tuple[list[dict], int]:
    """Gives every clone a SkillLineAbility row, so the client files it in
    the right spellbook tab instead of leaving it loose.

    Each clone row is a copy of the WOTLK row for the spell it was cloned
    from, not the era's own. Three reasons, all of them things the era rows
    get wrong here:

      * SkillLine 40 and 261 exist in the Vanilla/TBC files and NOT in
        WotLK's SkillLine.dbc -- a row pointing at either names a skill line
        the client cannot resolve.
      * Where a shared spell's SkillLine disagrees across builds (15 rows
        Vanilla, 20 TBC), WotLK's is the one this client can place.
      * The era RaceMask has no bits for races that did not exist yet. That
        is exactly the live bug build_era_tree.py hit, where a Blood Elf
        Rogue could not see their own era talent tabs. WotLK's mask covers
        every race, and class eligibility is already enforced elsewhere.

    AcquireMethod is forced to 0 (trainer-learned) on every clone row, no
    matter what the original says. Player.cpp's skill-reward pass auto-
    learns any row with AcquireMethod 1 or 2 that matches the character's
    race and class -- which would hand every character all three eras'
    copies of a spell the moment they gained the skill. Era spells are
    granted deliberately, by this project's own code, or not at all. The
    ~60-70 era rows that really were auto-learned on skill therefore need
    granting explicitly; they are counted below rather than lost silently.
    """
    by_spell: dict[int, list[dict]] = {}
    for row in base_sla.rows:
        by_spell.setdefault(row["Spell"], []).append(row)

    new_rows: list[dict] = []
    auto_learn_lost = 0
    next_fallback_id = max(row["ID"] for row in base_sla.rows) + 1
    for label, mapping in id_map.items():
        offset = era_offsets[label]
        era_fallback = era_sla.get(label, {})
        for base_spell_str, clone_id in mapping.items():
            # A ported spell (deleted, or its id reused by WotLK) takes the
            # era's row even when WotLK has one: WotLK's row at a reused id
            # describes the other spell's skill line and class.
            sources = [] if int(base_spell_str) in ported.get(label, set())                 else by_spell.get(int(base_spell_str), [])
            if not sources:
                # A spell WotLK deleted outright: there is no WotLK row to
                # mirror, so the era's own row is the only description of
                # which skill line and class it belongs to. Its SkillLine
                # has to exist in WOTLK's SkillLine.dbc -- Vanilla and TBC
                # both carry lines 40 and 261 that WotLK dropped, and a row
                # naming one of those points at a skill line this client
                # cannot resolve.
                for era_row in era_fallback.get(int(base_spell_str), []):
                    if era_row["SkillLine"] not in valid_skill_lines:
                        continue
                    row = {f.name: era_row.get(f.name, 0)
                           for f in BUILD_SCHEMAS["3.3.5a"]["SkillLineAbility.dbc"]}
                    row["ID"] = next_fallback_id
                    next_fallback_id += 1
                    row["Spell"] = clone_id
                    row["AcquireMethod"] = 0
                    # RaceMask 0 means "every race", which is what a WotLK
                    # row would carry. An era mask naming every race the
                    # era had has no bits for races added later -- the
                    # exact bug that hid era talent tabs from a Blood Elf --
                    # so that becomes 0. A mask naming FEWER is a genuine
                    # racial class spell (Elune's Grace, Touch of Weakness)
                    # and is kept, or every priest could buy every race's.
                    era_all = ERA_ALL_RACES[label]
                    if era_row["RaceMask"] & era_all == era_all:
                        row["RaceMask"] = 0
                    nxt = era_row["SupercededBySpell"]
                    row["SupercededBySpell"] = mapping.get(str(nxt), 0) if nxt else 0
                    new_rows.append(row)
                continue

            for src in sources:
                row = dict(src)
                row["ID"] = src["ID"] + offset
                row["Spell"] = clone_id
                if src["AcquireMethod"] != 0:
                    auto_learn_lost += 1
                row["AcquireMethod"] = 0
                # Point the rank chain at this era's copy of the next rank.
                # A next rank with no clone was identical to WotLK's, so the
                # WotLK id IS this era's version and is right to keep.
                nxt = src["SupercededBySpell"]
                if nxt:
                    row["SupercededBySpell"] = mapping.get(str(nxt), nxt)
                new_rows.append(row)
    return new_rows, auto_learn_lost


def row_differs(a: dict, b: dict) -> bool:
    """Whether two Spell.dbc rows differ in CONTENT.

    A plain `a == b` would not do: a string field holds the byte offset into
    its own file's string block, and the same text sits at different offsets
    in two different files. Comparing those reports every row as changed.
    """
    for f in BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"]:
        av, bv = a[f.name], b[f.name]
        if f.type == "loc_string":
            if av["enUS"] != bv["enUS"]:
                return True
        elif f.type == "string":
            if av["value"] != bv["value"]:
                return True
        elif av != bv:
            return True
    return False


SKILL_CATEGORY_CLASS = 7


def class_skill_lines(root: Path) -> set[int]:
    """The SkillLine ids that are CLASS skill lines (Frost, Holy, Beast
    Mastery, ...), as opposed to weapon, armour, profession or secondary
    ones.

    Read positionally rather than through a schema in schemas.py: only the
    first two columns are wanted (ID, CategoryID) and they sit at the front
    of the record in all three builds, while the rest of the row is 20 to 54
    further columns of mostly localised strings that nothing here looks at.
    Authoring three full SkillLine schemas to read two integers would be
    a lot of surface for no benefit.
    """
    archive, data = mpq_source.resolve(root, "SkillLine.dbc")
    record_count, field_count, record_size, _ = struct.unpack_from("<IIII", data, 4)
    lines = set()
    for i in range(record_count):
        skill_id, category = struct.unpack_from("<II", data, 20 + i * record_size)
        if category == SKILL_CATEGORY_CLASS:
            lines.add(skill_id)
    return lines


def all_skill_lines(root: Path) -> set[int]:
    """Every SkillLine id this build has, class or not. A ported spell's
    era row may name a line WotLK dropped (40 and 261 are both gone), and
    such a row is unusable here."""
    archive, data = mpq_source.resolve(root, "SkillLine.dbc")
    record_count, _field_count, record_size, _ = struct.unpack_from("<IIII", data, 4)
    return {struct.unpack_from("<I", data, 20 + i * record_size)[0] for i in range(record_count)}


def talent_rank_spells(build: str, root: Path, tmp_dir: Path) -> set[int]:
    """Every spell an era's Talent.dbc names as one of a talent's ranks."""
    talents = load_from_client(build, "Talent.dbc", root, tmp_dir)
    return {v for row in talents.rows for k, v in row.items() if k.startswith("SpellRank") and v}


def untrainable_ported(ported: dict[str, dict], era_by_id: dict[int, dict],
                       sla_by_spell: dict[int, list[dict]], class_lines: set[int],
                       talent_spells: set[int]) -> set[int]:
    """The ported spells (ones WotLK deleted) that a trainer never sold.

    build_era_spell_sql.py has to invent trainer rows for ported spells,
    and "has a class" turned out to be far too loose a test for that: two
    thirds of them are talent ranks (Improved Drain Life), talent procs
    (Vindication, Rampage), racials (Berserking) or automatic grants (Shoot
    Bow). Stocked on a trainer, those sold talents for 1 silver.

    Nothing in the client says what a trainer sold -- those lists were
    server data and never shipped -- so this reads the closest signals the
    era client does have, each of which rules a spell OUT:

      * a talent's own rank spell (the era's Talent.dbc);
      * no SkillLineAbility row that is both AcquireMethod 0 (trained, as
        opposed to granted on skill gain) and on a class skill line --
        which drops racials and auto-learned spells;
      * no level: every trainer spell WotLK deleted has one, while talent
        effects and procs are level 0 or 1;
      * triggered by another class spell (EffectTriggerSpell), so it is
        cast by its parent rather than learned. Only class spells count --
        NPC and item spells trigger player spells too, and counting them
        dropped Curse of Recklessness.

    Two pair rules then catch proc halves that the client lists exactly
    like real abilities, because they reach their parent through the
    core's proc tables rather than a trigger field:

      * of two spells with the same name AND rank, the later id is the proc
        half (Touch of Weakness 2652 vs 2943, Shadowguard 18137 vs 28377);
      * "Judgement of ..." spells are the debuffs the Judgement spell
        applies (trainers sold the Seals), and an unranked copy of a ranked
        spell is its effect (Bloodthirst's heal, Bestial Wrath's pet auras).
    """
    def name(spell_id: int) -> str:
        return era_by_id[spell_id]["Name_lang"]["enUS"]

    def rank(spell_id: int) -> str:
        return era_by_id[spell_id]["NameSubtext_lang"]["enUS"]

    class_spells = {s for s, rows in sla_by_spell.items()
                    if s in era_by_id and any(r["SkillLine"] in class_lines for r in rows)}
    triggered = {era_by_id[s][f"EffectTriggerSpell_{i}"] for s in class_spells for i in range(3)} - {0}
    ranked_names = {name(s) for s in class_spells if rank(s).startswith("Rank")}

    out: set[int] = set()
    kept: dict[tuple[str, str], int] = {}
    for spell_id_str, info in sorted(ported.items(), key=lambda kv: int(kv[0])):
        spell_id = int(spell_id_str)
        trained_row = any(r["AcquireMethod"] == 0 and r["SkillLine"] in class_lines
                          for r in sla_by_spell.get(spell_id, []))
        if (spell_id in talent_spells or not trained_row or int(info.get("level") or 0) <= 1
                or spell_id in triggered or name(spell_id).startswith("Judgement of ")
                or (not rank(spell_id) and name(spell_id) in ranked_names)
                or (name(spell_id), rank(spell_id)) in kept):
            out.add(spell_id)
            continue
        kept[(name(spell_id), rank(spell_id))] = spell_id
    return out


RANK_TEXT = re.compile(r"^Rank (\d+)$")


def resolve_rank_claim(claims: set[int], links: set[tuple[int, int]]) -> int:
    """Which of the spells labelled with one rank is the chain's member, or 0.

    Two spells claiming one rank are usually a buff and its proc half, and
    then neither is kept rather than guessing. The exception is a pair the
    era's own SkillLineAbility already orders: Vanilla Seal of Righteousness
    has two "Rank 1" spells, 20154 -> 21084, and leaving both out cut 21084
    off from Rank 2 -- two unrelated chains, so Rank 2 never replaced Rank 1.
    The spell the link leads TO is the one the chain carries on from.
    """
    if len(claims) == 1:
        return next(iter(claims))
    last = [c for c in claims if not any((c, other) in links for other in claims)]
    return last[0] if len(last) == 1 and any((o, last[0]) in links for o in claims) else 0


def rank_links_touching_ported(era_map: dict[str, int], ported: set[int], era_by_id: dict[int, dict],
                               sla_by_spell: dict[int, list[dict]]) -> list[list[int]]:
    """The era's own rank links (lower rank -> next) for every link that
    touches a ported spell, in original (unoffset) ids.

    build_era_spell_sql.py builds rank chains from WotLK's spell_ranks,
    which knows nothing of a spell WotLK deleted and describes a different
    spell at a reused id. Without these, Curse of Recklessness's four ranks
    were four unrelated spells and Vanilla Wing Clip's chain stopped at
    rank 1.

    The era client says what a rank is in two places. SkillLineAbility's
    SupercededBySpell is authoritative but Vanilla fills it almost only for
    pet skills, so the main source is what the trainer and spellbook
    themselves show: spells of the same name on the same class skill line,
    ordered by their "Rank N" subtext.
    """
    in_era = {int(s) for s in era_map}
    links: set[tuple[int, int]] = set()
    for spell_id, rows in sla_by_spell.items():
        for row in rows:
            nxt = row["SupercededBySpell"]
            if nxt and spell_id in in_era and nxt in in_era:
                links.add((spell_id, nxt))

    by_name: dict[tuple[str, int], dict[int, set[int]]] = {}
    for spell_id in in_era:
        row = era_by_id.get(spell_id)
        match = RANK_TEXT.match(row["NameSubtext_lang"]["enUS"].strip()) if row else None
        if not match:
            continue
        for sla_row in sla_by_spell.get(spell_id, []):
            ranks = by_name.setdefault((row["Name_lang"]["enUS"].strip(), sla_row["SkillLine"]), {})
            ranks.setdefault(int(match.group(1)), set()).add(spell_id)
    for ranks in by_name.values():
        resolved = {n: resolve_rank_claim(claims, links) for n, claims in ranks.items()}
        for n in sorted(resolved):
            a, b = resolved[n], resolved.get(n + 1)
            if a and b:
                links.add((a, b))

    return sorted([a, b] for a, b in links if a in ported or b in ported)


SPELL_AURA_SCHOOL_IMMUNITY = 39
MECHANIC_FREEZE = 13
MECHANIC_INVULNERABILITY = 25
MECHANIC_IMMUNE_SHIELD = 29
TARGET_UNIT_CASTER = 1
SPELL_SCHOOL_MASK_MAGIC = 0x7E
# SPELL_ATTR7_NO_CLIENT_FAIL_WHILE_STUNNED_FLEEING_CONFUSED. WotLK sets it on
# the self-cast bubbles, Divine Shield 642 and Ice Block 45438, and on TBC's
# Ice Block. Both of those stun or pacify their own caster.
ATTR7_IMMUNE_SHIELD_SELF = 0x00100000


def as_immune_shield(row: dict) -> bool:
    """Retags an era immunity bubble the way WotLK tags its own.

    Vanilla marked its bubbles MECHANIC_INVULNERABILITY (Divine Shield,
    Divine Protection, Blessing of Protection) or MECHANIC_FREEZE (Ice
    Block). 3.0 moved every player bubble to MECHANIC_IMMUNE_SHIELD, which is
    what AzerothCore keys on: SpellInfo::_IsPositiveEffect treats it as a
    buff outright, and Mass Dispel and Shattering Throw look for it. The TBC
    clones already carry it, and the Vanilla ones were left as the only
    bubbles the core did not recognise.

    Returns whether the row was changed.
    """
    auras = [row[f"EffectAura_{i}"] for i in range(3)]
    if SPELL_AURA_SCHOOL_IMMUNITY not in auras:
        return False
    if row["Mechanic"] not in (MECHANIC_FREEZE, MECHANIC_INVULNERABILITY):
        return False
    row["Mechanic"] = MECHANIC_IMMUNE_SHIELD
    magic_on_self = any(
        row[f"EffectAura_{i}"] == SPELL_AURA_SCHOOL_IMMUNITY
        and row[f"ImplicitTargetA_{i}"] == TARGET_UNIT_CASTER
        and row[f"EffectMiscValue_{i}"] & SPELL_SCHOOL_MASK_MAGIC == SPELL_SCHOOL_MASK_MAGIC
        for i in range(3))
    if magic_on_self:
        row["AttributesExG"] |= ATTR7_IMMUNE_SHIELD_SELF
    return True


SPELL_EFFECT_APPLY_AURA = 6
SPELLMOD_EFFECT2 = 12
SPELLFAMILY_GENERIC = 0
MAGE_FIRE_WARD_MASK = 0x8
MAGE_FROST_WARD_MASK = 0x100

# Era talents whose reflect chance was a DUMMY the old core read by hand:
# "Causes your Fire Ward to have a $s1% chance to reflect Fire spells".
# WotLK's Fire Ward and Frost Ward already carry the reflect itself, a
# SPELL_AURA_REFLECT_SPELLS_SCHOOL at 0% in effect 2, and WotLK's own Molten
# Shields raises it with a flat EFFECT2 spellmod. The era talent is rewritten
# to do the same, so the core's spellmod code applies it and no handler is
# needed. Keyed by ORIGINAL era spell id: effect index -> the ward it raises.
ERA_WARD_REFLECT_TALENTS = {
    11094: (0, MAGE_FIRE_WARD_MASK),   # Improved Fire Ward / Molten Shields r1
    13043: (0, MAGE_FIRE_WARD_MASK),   # r2
    11189: (1, MAGE_FROST_WARD_MASK),  # Frost Warding r1
    28332: (1, MAGE_FROST_WARD_MASK),  # r2
}

# Era talents to hide from a core lookup that would give them WotLK
# behaviour. AuraEffect::HandleAuraModShapeshift finds Furor by druid
# family + icon 238 and applies WotLK's Cat Form rule ("keep up to N
# energy") instead of the era's ("N% chance to gain 40 energy").
# src/EraSpellScripts.cpp's spell_era_dru_furor does the era's version.
ERA_HIDDEN_FROM_CORE = {17056, 17058, 17059, 17060, 17061}  # Furor r1-r5

# Illumination r1-r5. spell_pal_illumination reads the mana returned, as a
# percent of the heal's base cost, from effect 1's value. WotLK and TBC store
# it there (TBC: "$s2% of the base cost", 60). The 1.12 rows leave the slot at
# 0 -- "gain Mana equal to the base cost of the spell", all of it, hard-coded
# by that core -- so a Vanilla clone returned 1% of the cost, i.e. no mana on
# a crit. Only an empty slot is filled; TBC keeps its own 60%.
ERA_ILLUMINATION = {20210, 20212, 20213, 20214, 20215}
VANILLA_ILLUMINATION_COST_PCT = 100


def apply_era_talent_rewrites(row: dict, original_id: int) -> bool:
    """ERA_WARD_REFLECT_TALENTS, ERA_HIDDEN_FROM_CORE and ERA_ILLUMINATION. Returns whether
    the row was changed."""
    if original_id in ERA_WARD_REFLECT_TALENTS:
        i, ward_mask = ERA_WARD_REFLECT_TALENTS[original_id]
        row[f"Effect_{i}"] = SPELL_EFFECT_APPLY_AURA
        row[f"EffectAura_{i}"] = SPELL_AURA_ADD_FLAT_MODIFIER
        row[f"EffectMiscValue_{i}"] = SPELLMOD_EFFECT2
        row[f"ImplicitTargetA_{i}"] = TARGET_UNIT_CASTER
        row[f"{EFFECT_MASK_FIELDS[i]}_0"] = ward_mask
        row[f"{EFFECT_MASK_FIELDS[i]}_1"] = 0
        row[f"{EFFECT_MASK_FIELDS[i]}_2"] = 0
        return True
    if original_id in ERA_HIDDEN_FROM_CORE:
        row["SpellClassSet"] = SPELLFAMILY_GENERIC
        return True
    if original_id in ERA_ILLUMINATION and row["EffectBasePoints_1"] == 0:
        row["EffectBasePoints_1"] = VANILLA_ILLUMINATION_COST_PCT - 1
        return True
    return False


SPELLFAMILY_PALADIN = 10
SPELL_AURA_DUMMY = 4
FORBEARANCE = 25771


SPELL_AURA_PROC_TRIGGER_SPELL = 42

# Seals whose melee proc is a spell of its own carrying the era's numbers.
# Rank 1 of each points at an id WotLK rewrote in place: Seal of Light's
# heal 20167 became "0.15 AP + 0.15 SP" (base points -1, spell_bonus_data
# 0.15/0.15) and Seal of Wisdom's 20168 a 4%-of-max-mana energize (effect
# 137). The era rows at those ids are flat -- 39 health, 50 mana in both
# 1.12 and 2.4.3 -- but the clone kept naming the shared id, so it healed
# and read like WotLK's ("$20167s1" printed 66). Seal of Command's 20424
# differs too (70% weapon damage, WotLK's is 36%) but is not here:
# spell_pal_seal_of_command makes it a 3-target cleave cast by id, which is
# its own piece of work.
ERA_SEAL_PROC_NAMES = {"Seal of Light", "Seal of Wisdom"}


def is_era_seal(row: dict) -> bool:
    """An era row that is a seal proper: paladin, "Seal of ...", naming its
    judgement in an EFFECT_2 dummy. Same-named rows without that dummy are
    the seal's proc halves (Seal of Light's heal, 20333)."""
    return (row["SpellClassSet"] == SPELLFAMILY_PALADIN and row["Name_lang"]["enUS"].startswith("Seal of")
            and row["Effect_2"] == SPELL_EFFECT_APPLY_AURA and row["EffectAura_2"] == SPELL_AURA_DUMMY)


def seal_proc_halves(spell_ids, era_by_id: dict[int, dict]) -> dict[int, tuple[int, int]]:
    """{seal id: (effect index, proc half id)} for the ERA_SEAL_PROC_NAMES
    seals among spell_ids, from the era's own PROC_TRIGGER_SPELL effect.

    Each proc half gets an era copy (era_side_spells), the seal's clone is
    pointed at it (remap_seal_procs) and so is its tooltip, through
    remap_era_text_refs. The copy is flat, like the era it comes from: it is
    listed in era-spell-map.json's "no_bonus", for which
    build_era_spell_sql.py writes a zero spell_bonus_data row in place of
    WotLK's 0.15 AP + 0.15 SP or the 1.12 rule's instant-cast default. 1.12
    gave this heal no bonus; 2.4.3's row is DmgClass NONE with a flat
    "$20167s1" (WotLK's spells out its AP/SP terms), and its ranks 2-5,
    which WotLK left unchanged, already healed flat here."""
    out: dict[int, tuple[int, int]] = {}
    for spell_id in spell_ids:
        row = era_by_id.get(spell_id)
        if row is None or not is_era_seal(row) or row["Name_lang"]["enUS"] not in ERA_SEAL_PROC_NAMES:
            continue
        for i in range(3):
            proc = row[f"EffectTriggerSpell_{i}"]
            if (row[f"Effect_{i}"] == SPELL_EFFECT_APPLY_AURA and row[f"EffectAura_{i}"] == SPELL_AURA_PROC_TRIGGER_SPELL
                    and proc in era_by_id):
                out[spell_id] = (i, proc)
    return out


def remap_seal_procs(rows: list[dict], offset: int, era_ids: dict[int, int],
                     procs: dict[int, tuple[int, int]]) -> list[int]:
    """Points each seal clone's proc trigger at its proc half's era copy (see
    seal_proc_halves). Returns the seal clones changed."""
    changed = []
    for row in rows:
        entry = procs.get(row["ID"] - offset)
        if entry is None or entry[1] not in era_ids:
            continue
        i, proc = entry
        if row[f"EffectTriggerSpell_{i}"] == proc:
            row[f"EffectTriggerSpell_{i}"] = era_ids[proc]
            changed.append(row["ID"])
    return changed


def era_side_spells(wanted: set[int], era_by_id: dict[int, dict]) -> set[int]:
    """Spells an era needs its own copy of although no class learns them.

      * The judgement each seal names. A seal names it only as a number, its
        EFFECT_2 dummy amount (spell_era_pal_judgement reads it), so the
        transitive port never saw it. Vanilla Judgement of the Crusader r1,
        21183, is Heart of the Crusader in WotLK: judging Seal of the
        Crusader cast the WotLK talent debuff. Vanilla Judgement of Command
        is itself a dummy naming its damage spell, so that is followed too.
      * Seal of Light's and Seal of Wisdom's proc halves (seal_proc_halves).
      * Forbearance, which lasts 1 minute in both eras and 2 in WotLK. The
        era immunity handler applies the era's copy.
    """
    out: set[int] = {proc for _, proc in seal_proc_halves(wanted, era_by_id).values()}

    def named(row: dict, i: int) -> int:
        return row[f"EffectBasePoints_{i}"] + 1

    for spell_id in wanted:
        row = era_by_id[spell_id]
        if not is_era_seal(row):
            continue
        judgement = era_by_id.get(named(row, 2))
        if judgement is None:
            continue
        out.add(judgement["ID"])
        if judgement["Effect_0"] == SPELL_EFFECT_DUMMY and named(judgement, 0) in era_by_id:
            out.add(named(judgement, 0))
    if FORBEARANCE in era_by_id:
        out.add(FORBEARANCE)
    return out


# Every seal carries one of these WotLK family bits, and AzerothCore finds
# seals by them (SpellInfo::GetSpellSpecific): that is what makes seals
# replace each other and what sets the aura state Judgement requires.
WOTLK_SEAL_FLAGS = (0x0A000000, 0x26000C00, 0)
# Seal of Blood / the Martyr's bit: TBC/WotLK-only seals no era character
# holds, and nothing in the core reads it for anything but seal-ness.
ERA_SEAL_FLAG_1 = 0x00000400


def as_wotlk_seal(row: dict) -> bool:
    """Gives a ported era seal a WotLK seal family bit. Returns whether the
    row changed.

    A seal WotLK deleted keeps its era family bits, and Seal of the
    Crusader's (0x200) are not a WotLK seal's. So the core did not treat it
    as a seal at all: it stacked with every other seal instead of replacing
    it, and never set the aura state Judgement needs -- Judgement could not
    be cast with only Crusader up, and when Righteousness was added after
    it, Crusader was judged instead.
    """
    if not is_era_seal(row):
        return False
    if any(row[f"SpellClassMask_{i}"] & WOTLK_SEAL_FLAGS[i] for i in range(3)):
        return False
    row["SpellClassMask_1"] |= ERA_SEAL_FLAG_1
    return True


# WotLK's hidden paladin markers: Avenging Wrath Marker and Immune Shield
# Marker, both 2 minutes. 1.12 had neither -- its Spell.dbc has no
# Exclude*AuraSpell columns at all.
WOTLK_PALADIN_MARKERS = {61987, 61988}


def drop_wotlk_paladin_markers(row: dict) -> bool:
    """Clears WotLK's marker auras from a Vanilla copy's exclude-aura
    fields. Returns whether the row changed.

    A ported row keeps WotLK's Exclude*AuraSpell, since the era had none to
    give it, and Spell::PrepareTriggersExecutedOnHit applies a negative
    excluded aura on hit. So Vanilla Divine Shield, Divine Protection and
    Blessing of Protection still put WotLK's invisible 2-minute Immune
    Shield Marker on their target, and its exclude check then refused the
    next bubble for 2 minutes -- on top of the era's own 1-minute
    Forbearance, which spell_era_pal_immunities applies and checks.
    """
    changed = False
    for field in ("ExcludeCasterAuraSpell", "ExcludeTargetAuraSpell"):
        if row[field] in WOTLK_PALADIN_MARKERS:
            row[field] = 0
            changed = True
    return changed


MECHANIC_BANDAGE = 16
SPELL_PREVENTION_TYPE_PACIFY = 2


def allow_bandage_while_pacified(rows: list[dict]) -> list[int]:
    """Lets First Aid bandages be used while pacified, as in 1.12 and 2.4.

    Bandages had no PreventionType before 3.0; WotLK gave them the pacify
    one. Vanilla Divine Protection pacifies its paladin ("cannot attack or
    use physical abilities"), so with WotLK's bandages a Vanilla paladin
    could not bubble-bandage, which the era allowed. This is the shared
    WotLK spell, so it applies to every era -- WotLK's own player bubbles
    do not pacify, which keeps the change out of WotLK play.
    """
    changed = []
    for row in rows:
        if row["Mechanic"] == MECHANIC_BANDAGE and row["PreventionType"] == SPELL_PREVENTION_TYPE_PACIFY:
            row["PreventionType"] = 0
            changed.append(row["ID"])
    return changed


# --- Vanilla spell power coefficients ---------------------------------------
#
# A clone inherited WotLK's spell_bonus_data through build_era_spell_sql.py:
# WotLK's coefficients, and WotLK's attack power scaling on spells that had
# none in 1.12 (Exorcism, Holy Wrath, Thunder Clap, Revenge, Arcane Shot,
# Multi-Shot ...). 1.12 had no table for most spells: the core derived the
# coefficient from the cast time, duration and effects. This is that rule,
# ported from vmangos (SpellEntry::GetCastTimeForBonus and
# CalculateDefaultCoefficient), the 1.12 core. Healing uses it unchanged --
# the realm restores Vanilla's separate +healing gear, which is what the
# rule was measured against, so WotLK's x1.88 for spell power does not apply.

SPELL_EFFECT_SCHOOL_DAMAGE = 2
SPELL_EFFECT_ENVIRONMENTAL_DAMAGE = 7
SPELL_EFFECT_POWER_DRAIN = 8
SPELL_EFFECT_HEALTH_LEECH = 9
SPELL_EFFECT_POWER_BURN = 62
DIRECT_EFFECTS = {SPELL_EFFECT_SCHOOL_DAMAGE, SPELL_EFFECT_POWER_DRAIN, SPELL_EFFECT_HEALTH_LEECH,
                  SPELL_EFFECT_ENVIRONMENTAL_DAMAGE, SPELL_EFFECT_POWER_BURN, SPELL_EFFECT_HEAL}
SPELL_AURA_PERIODIC_DAMAGE = 3
SPELL_AURA_PERIODIC_HEAL = 8
SPELL_AURA_PERIODIC_LEECH = 53
PERIODIC_AURAS = {SPELL_AURA_PERIODIC_DAMAGE, SPELL_AURA_PERIODIC_HEAL, SPELL_AURA_PERIODIC_LEECH}
# Extra effects that cost a share of the coefficient: +1 = -5%, +2 = -10%.
PENALTY_AURAS = {SPELL_AURA_DUMMY: 1, 33: 1, 5: 2, 12: 2, 26: 2}  # dummy, slow, confuse, stun, root
# Implicit targets AzerothCore selects as an area or cone (SpellInfo.cpp's
# target table): an area spell gets half the coefficient.
AREA_TARGETS = {7, 8, 15, 16, 20, 24, 30, 31, 33, 34, 37, 51, 52, 54, 56, 59, 60, 61, 93, 104, 108}
SPELL_ATTR1_CHANNELED = 0x4 | 0x40
SPELL_SCHOOL_MASK_NORMAL = 1
SPELL_DAMAGE_CLASS_MELEE, SPELL_DAMAGE_CLASS_RANGED = 2, 3

# Coefficients 1.12 set by hand rather than by the rule, keyed by original
# spell id: (direct, dot, ap_dot). Garrote: "$AP*0.03" per tick, from patch
# 1.12.0 ("Garrote now increases in potency with greater attack power").
#
# Retribution Aura r1-r5: a damage shield, which took no bonus in 1.12. With
# no row, the core adds the target's "damage taken" bonus at the instant-cast
# default of 43% (Unit::SpellDamageBonusTaken treats a coefficient <= 0 as
# "use the default"), so Judgement of the Crusader put ~21 on every reflect.
# 0.0001 is the smallest row that turns that default off.
VANILLA_BONUS_OVERRIDES = {
    703: (0.0, 0.0, 0.03), 8631: (0.0, 0.0, 0.03), 8632: (0.0, 0.0, 0.03), 8633: (0.0, 0.0, 0.03),
    11289: (0.0, 0.0, 0.03), 11290: (0.0, 0.0, 0.03),
    **{s: (0.0001, 0.0, 0.0) for s in (7294, 10298, 10299, 10300, 10301)},
}


# Channelled and ground-effect spells whose 1.12 coefficient the general
# rule overstates: it gives Blizzard 100% and Mind Flay 81%, where the era's
# measured values were a third and 45%. Total over the whole duration, keyed
# by name so every rank is covered.
VANILLA_DOT_TOTAL_BY_NAME = {
    "Blizzard": 1 / 3, "Rain of Fire": 1 / 3, "Hurricane": 1 / 3, "Consecration": 1 / 3, "Mind Flay": 0.45,
}
SPELL_EFFECT_PERSISTENT_AREA_AURA = 27


def vanilla_coefficients(row: dict, cast_ms: int, duration_ms: int) -> tuple[float, float] | None:
    """(direct, per-tick dot) spell power coefficients under the 1.12 rule,
    or None when the spell has nothing to scale."""
    # A persistent area aura (Consecration, Blizzard) carries its periodic
    # aura on the ground effect rather than an APPLY_AURA.
    effects = [(row[f"Effect_{i}"], row[f"EffectAura_{i}"]
                if row[f"Effect_{i}"] in (SPELL_EFFECT_APPLY_AURA, SPELL_EFFECT_PERSISTENT_AREA_AURA) else 0)
               for i in range(3)]
    direct = any(e in DIRECT_EFFECTS for e, _ in effects)
    periodic = any(a in PERIODIC_AURAS for _, a in effects)
    if not direct and not periodic:
        return None
    # Physical abilities did not scale with spell damage at all.
    if row["SchoolMask"] == SPELL_SCHOOL_MASK_NORMAL or (
            row["DefenseType"] in (SPELL_DAMAGE_CLASS_MELEE, SPELL_DAMAGE_CLASS_RANGED)
            and not row["SchoolMask"] & ~SPELL_SCHOOL_MASK_NORMAL):
        return (0.0, 0.0)

    channeled = bool(row["AttributesEx"] & SPELL_ATTR1_CHANNELED)
    area = any(row[f"ImplicitTargetA_{i}"] in AREA_TARGETS or row[f"ImplicitTargetB_{i}"] in AREA_TARGETS
               or row[f"Effect_{i}"] == SPELL_EFFECT_PERSISTENT_AREA_AURA for i in range(3))
    leech = any(e == SPELL_EFFECT_HEALTH_LEECH or a == SPELL_AURA_PERIODIC_LEECH for e, a in effects)
    penalties = sum(PENALTY_AURAS.get(a, 0) for _, a in effects)
    over_time = duration_ms if periodic and duration_ms > 0 else 0

    def cast_time_for_bonus(dot: bool) -> float:
        t = min(max(duration_ms if channeled else cast_ms, 1500), 7000)
        if dot and not channeled:
            t = 3500
        if over_time and direct:
            original = min(max(cast_ms, 1500), 7000)
            share_dot = (over_time / 15000) / ((over_time / 15000) + (original / 3500))
            t = int(t * share_dot) if dot else (int(t * (1 - share_dot)) if share_dot < 1 else 0)
        if area:
            t //= 2
        if leech:
            t //= 2
        return t * 0.95 ** penalties

    def max_ticks() -> int:
        d = min(duration_ms, 30000)
        if d <= 0:
            return 1
        for i in range(3):
            if effects[i][1] in PERIODIC_AURAS:
                period = row[f"EffectAuraPeriod_{i}"]
                return d // period if period else 6
        return 6

    direct_coeff = cast_time_for_bonus(False) / 3500 if direct else 0.0
    dot_coeff = 0.0
    total = VANILLA_DOT_TOTAL_BY_NAME.get(row["Name_lang"]["enUS"])
    if periodic and total is not None:
        dot_coeff = total / max(max_ticks(), 1)
    elif periodic:
        factor = 1.0 if channeled else max(duration_ms, 0) / 15000
        dot_coeff = cast_time_for_bonus(True) / 3500 * factor / max(max_ticks(), 1)
    return (round(direct_coeff, 4), round(dot_coeff, 4))


# The racial skill lines: Dwarven 101, Tauren 124, Orcish 125, Night Elf 126,
# Troll 220, Undead 733, Gnomish 753, Human 754, Blood Elf 756, Draenei 760.
# Their spells are per-era too (Human Spirit 5% vs 3%, Blood Fury, the weapon
# specialisations, Escape Artist, Berserking...), and the gate and login sync
# in src/ move them like any class spell. Mirrored by RACIAL_SKILL_LINES in
# src/EraSpells.h, which also drops the racials WotLK added.
RACIAL_SKILL_LINES = {101, 124, 125, 126, 220, 733, 753, 754, 756, 760}


def class_spell_ids(sla: DbcFile, class_lines: set[int]) -> set[int]:
    """Spells a player character of some class or race can know.

    Two tests, unioned, because neither alone is enough:

      * ClassMask != 0 -- an explicit "these classes only" row.
      * The row's SkillLine is a CLASS skill line.

    ClassMask alone was this project's first definition and it is too
    narrow: plenty of real class spells carry ClassMask 0 because their
    skill line already implies the class, and they were silently left out.
    Holy Light rank 5, Curse of Agony rank 2, Aimed Shot and Holy Shield
    all sit in class skill lines with ClassMask 0 -- and skipping the
    middle rank of a chain leaves the rest of that chain broken. Widening
    to the union takes Vanilla from 1,936 spells to 3,328.

    Racial skill lines count too (RACIAL_SKILL_LINES), so racials follow the
    same per-era design.
    """
    return {row["Spell"] for row in sla.rows
            if row["ClassMask"] != 0 or row["SkillLine"] in class_lines
            or row["SkillLine"] in RACIAL_SKILL_LINES}


def build_clone(
    era_row: dict,
    wotlk_row: dict,
    clone_id: int,
    *,
    remappers: dict[str, IndexRemapper],
    era_tables: dict[str, DbcFile],
    strings: StringBlockBuilder,
    locale_count: int,
    tag: str | None,
) -> tuple[dict, list[str]]:
    """WotLK row + era overrides. Returns the clone and the names of the
    fields that actually changed, so a run can report what it did rather
    than just how many rows it wrote."""
    clone = dict(wotlk_row)
    clone["ID"] = clone_id
    changed: list[str] = []

    # EquippedItemSubclass/InvTypes only mean anything when the spell
    # actually requires an item class. When neither build requires one
    # (EquippedItemClass == -1), the two disagree purely on how they spell
    # "unset" -- Vanilla writes -1 in the subclass, WotLK writes 0. Copying
    # that across produced 190 clones whose ONLY difference from the WotLK
    # spell was that encoding, i.e. 190 rows of pure noise.
    item_reqs_are_moot = era_row["EquippedItemClass"] == -1 == wotlk_row["EquippedItemClass"]

    for name, value in era_row.items():
        if name in KEEP_FROM_WOTLK or name not in wotlk_row:
            continue
        if item_reqs_are_moot and name.startswith("EquippedItem"):
            continue
        if name in INDEX_FIELDS:
            table = INDEX_FIELDS[name]
            value = remappers[table].remap(value, era_tables[table])
        if clone[name] != value:
            clone[name] = value
            changed.append(name)

    # The rank label DOES come from the era, unlike the other strings.
    # WotLK dropped "Rank 1" from spells it collapsed to a single rank, and
    # renumbered others outright -- it added Water Shield ranks 1-6 as new
    # ids and pushed TBC's originals to ranks 7-8, so a TBC clone labelled
    # from WotLK would read "Rank 7" for what TBC called rank 1. Re-interned
    # rather than copied: the era row's offset points into that build's own
    # string block, which means nothing in the file being written.
    era_rank = era_row["NameSubtext_lang"]["enUS"]
    if era_rank != wotlk_row["NameSubtext_lang"]["enUS"]:
        clone["NameSubtext_lang"] = new_loc_string(strings, era_rank, locale_count)
        changed.append("NameSubtext_lang")

    # The name and tooltip come from the era too. Keeping WotLK's text was
    # the first approach, on the grounds that its $s1-style tokens resolve
    # against the clone's own era values -- but the text still describes the
    # WotLK spell around those numbers. Players saw Vanilla Lay on Hands warn
    # about Avenging Wrath, "Hand of Protection" where Vanilla had Blessing of
    # Protection, a 2-minute Forbearance, TBC Aspect of the Viper describing
    # the 3.x mana mechanic, and the 3.0 pushback "reduction" where the era
    # rolled a chance (core patch 0003). The era's own text describes what
    # the clone now does. Tokens naming another spell ($20187s3) are pointed
    # at that spell's era copy afterwards, by remap_era_text_refs.
    for field in ("Name_lang", "Description_lang", "AuraDescription_lang"):
        text = era_row[field]["enUS"]
        if text != wotlk_row[field]["enUS"]:
            clone[field] = new_loc_string(strings, text, locale_count)
            changed.append(field)

    # Vanilla Holy Light and Flash of Light heal through SCRIPT_EFFECT: the
    # 1.12 core turned it into the heal (and a Libram bonus) by hand. This
    # core has no such handler, so the clone cast and healed nothing. WotLK's
    # row carries the plain HEAL in the same slot with the same targets.
    for i in range(3):
        if clone[f"Effect_{i}"] == SPELL_EFFECT_SCRIPT_EFFECT and wotlk_row[f"Effect_{i}"] == SPELL_EFFECT_HEAL:
            clone[f"Effect_{i}"] = SPELL_EFFECT_HEAL
            changed.append(f"Effect_{i}")

    if tag:
        text = f"{wotlk_row['Name_lang']['enUS']} [{tag}]"
        clone["Name_lang"] = new_loc_string(strings, text, locale_count)

    return clone, changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path,
                    help="3.3.5a client -- source of the WotLK side tables and the stock Spell.dbc fallback")
    ap.add_argument("--vanilla-root", type=Path, help="1.12.1 client")
    ap.add_argument("--tbc-root", type=Path, help="2.4.3 client")
    ap.add_argument("--base-spell", type=Path,
                    help="Spell.dbc to build on (normally port_era_spells.py's output). Defaults to the stock client's.")
    ap.add_argument("--base-skill-line-ability", type=Path,
                    default=Path("client-patch/progression-optional/SkillLineAbility.dbc"),
                    help="SkillLineAbility.dbc to add clone rows to -- the copy the realm mounts "
                         "(mod-individual-progression's). Falls back to the stock client's if absent.")
    ap.add_argument("--reserved-ids", type=Path,
                    default=Path("data/generated/reserved-spell-ids.txt"),
                    help="newline-separated spell ids the realm defines serverside (`spell_dbc`), "
                         "dumped by tools/server/dump_reserved_spell_ids.sh. A clone landing on one "
                         "of these fails the build.")
    ap.add_argument("--npc-spells", type=Path,
                    default=Path("data/generated/classic-npc-spells.txt"),
                    help="newline-separated spell ids that are not class spells but need a Vanilla copy "
                         "because creatures cast them (written by build_classic_mobs.py). Vanilla only: "
                         "the creatures it concerns are 1.12 creatures.")
    ap.add_argument("--rank-chains", type=Path,
                    default=Path("data/generated/spell-rank-chains.txt"),
                    help="'<first_spell_id> <spell_id>' per line, dumped by "
                         "tools/server/dump_reserved_spell_ids.sh. Used to clone a rank chain whole.")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--only", help="comma-separated WotLK spell ids -- clone just these (spike/debug)")
    ap.add_argument("--keep-global-era-edits", action="store_true",
                    help="do NOT restore stock WotLK values for class spells. See --help text in the "
                         "doc comment: by default a class spell's WotLK row is reset to the stock "
                         "client's, so mod-individual-progression's patch-V era edits stop applying "
                         "to every character regardless of era.")
    ap.add_argument("--tag-names", action="store_true",
                    help="append [Vanilla]/[TBC] to each clone's name. TESTING ONLY -- makes a clone unmistakable in game.")
    args = ap.parse_args()

    eras = [e for e, cfg in ERA_CONFIG.items() if getattr(args, cfg["root_arg"]) is not None]
    if not eras:
        print("error: pass at least one of --vanilla-root/--tbc-root", file=sys.stderr)
        return 2

    only = {int(x) for x in args.only.split(",")} if args.only else None
    args.out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        if args.base_spell and args.base_spell.exists():
            base = read_dbc(args.base_spell, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"], LOCALE_COUNT["3.3.5a"])
            print(f"  base Spell.dbc: {args.base_spell} ({len(base.rows)} rows)", file=sys.stderr)
        else:
            base = load_from_client("3.3.5a", "Spell.dbc", args.wotlk_root, tmp)

        wotlk_by_id = {r["ID"]: r for r in base.rows}
        strings = StringBlockBuilder(base.string_block)
        locale_count = LOCALE_COUNT["3.3.5a"]

        # WotLK side tables, loaded once -- the remappers mutate these in
        # place as they append rows, and they are written back out only if
        # something was actually appended.
        wotlk_tables = {
            name: load_from_client("3.3.5a", name, args.wotlk_root, tmp)
            for name in INDEX_VALUE_FIELDS
        }
        remappers = {name: IndexRemapper(name, tbl) for name, tbl in wotlk_tables.items()}

        # Which spells any era treats as a class spell. Collected up front
        # because it decides two things: what gets cloned per era, and (just
        # below) which rows are reset to stock WotLK first.
        era_class_ids: dict[str, set[int]] = {}
        era_sla_by_spell: dict[str, dict[int, list[dict]]] = {}
        for era in eras:
            root = getattr(args, ERA_CONFIG[era]["root_arg"])
            era_sla_file = load_from_client(era, "SkillLineAbility.dbc", root, tmp)
            era_class_ids[era] = class_spell_ids(era_sla_file, class_skill_lines(root))
            per_spell: dict[int, list[dict]] = {}
            for sla_row in era_sla_file.rows:
                per_spell.setdefault(sla_row["Spell"], []).append(sla_row)
            era_sla_by_spell[ERA_CONFIG[era]["label"]] = per_spell
        all_class_ids = set().union(*era_class_ids.values())
        all_class_ids |= class_spell_ids(
            load_from_client("3.3.5a", "SkillLineAbility.dbc", args.wotlk_root, tmp),
            class_skill_lines(args.wotlk_root))
        wotlk_skill_lines = all_skill_lines(args.wotlk_root)

        if not args.keep_global_era_edits:
            # The base Spell.dbc is normally mod-individual-progression's
            # patch-V, which restores Vanilla/TBC mana costs, reagents,
            # durations and spell-focus requirements GLOBALLY -- every
            # character, whatever era they are actually in. That was the only
            # way to get era-authentic values before per-era rows existed.
            # Now that a Vanilla character can hold a Vanilla row of their
            # own, a WotLK character should get WotLK's numbers back.
            #
            # Scoped deliberately to CLASS spells, not the whole file:
            # patch-V's other edits are profession and item spells, which
            # have no per-era mechanism here, so reverting those would lose
            # era authenticity with nothing replacing it (and would break
            # the optional SQL that depends on them). patch-V's ADDED rows
            # are never touched -- they exist in no stock file, and
            # zz_optional_spell_damage_and_healing.sql points item_template
            # straight at them.
            stock = load_from_client("3.3.5a", "Spell.dbc", args.wotlk_root, tmp)
            stock_by_id = {r["ID"]: r for r in stock.rows}
            reset = 0
            for i, row in enumerate(base.rows):
                sid = row["ID"]
                if sid not in all_class_ids:
                    continue
                stock_row = stock_by_id.get(sid)
                if stock_row is None or not row_differs(stock_row, row):
                    continue
                # Strings come from the stock file's OWN block, so they have
                # to be re-interned into the one being written.
                fixed = dict(stock_row)
                for f in BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"]:
                    if f.type == "loc_string":
                        fixed[f.name] = new_loc_string(strings, stock_row[f.name]["enUS"], locale_count)
                    elif f.type == "string":
                        fixed[f.name] = {"offset": strings.intern(stock_row[f.name]["value"]),
                                         "value": stock_row[f.name]["value"]}
                base.rows[i] = fixed
                reset += 1
            wotlk_by_id = {r["ID"]: r for r in base.rows}
            print(f"  reset {reset} class spell row(s) to stock WotLK values "
                  f"(patch-V's global era edits no longer apply outside an era's own rows)",
                  file=sys.stderr)

        # Spell ids the realm defines SERVERSIDE (`spell_dbc`). These count
        # as already existing even though no client DBC has them: the core
        # loads them into sSpellStore after Spell.dbc, so a clone pointing
        # at one resolves fine and porting our own copy on top would only
        # fight it. Live example: 26651, Execute's trigger, which WotLK
        # dropped from the client file and AzerothCore re-added serverside.
        reserved: set[int] = set()
        if args.reserved_ids and args.reserved_ids.exists():
            reserved = {int(x) for x in args.reserved_ids.read_text().split() if x.strip()}
            print(f"  {len(reserved)} serverside spell id(s) read from {args.reserved_ids}", file=sys.stderr)
        else:
            print("  WARNING: no --reserved-ids list, so clone ids are NOT checked against the "
                  "serverside spells in `spell_dbc` (see ERA_CONFIG)", file=sys.stderr)

        # head spell id -> every spell in that rank chain, from the realm's
        # own `spell_ranks` (tools/server/dump_reserved_spell_ids.sh).
        rank_chains: dict[int, set[int]] = {}
        if args.rank_chains and args.rank_chains.exists():
            for line in args.rank_chains.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2:
                    rank_chains.setdefault(int(parts[0]), set()).add(int(parts[1]))
            print(f"  {len(rank_chains)} rank chain(s) read from {args.rank_chains}", file=sys.stderr)
        else:
            print("  WARNING: no --rank-chains list, so a partially-reachable rank chain may be "
                  "cloned with a hole in it", file=sys.stderr)

        # SkillLine -> the classes that line belongs to, unioned over
        # every row that states one. A ported spell often carries
        # ClassMask 0 because its skill line already implies the class, so
        # this is how that gets recovered.
        line_class_mask: dict[int, int] = {}
        for per_spell_rows in era_sla_by_spell.values():
            for rows_for_spell in per_spell_rows.values():
                for sla_row in rows_for_spell:
                    if sla_row["ClassMask"]:
                        line_class_mask[sla_row["SkillLine"]] = \
                            line_class_mask.get(sla_row["SkillLine"], 0) | sla_row["ClassMask"]
        valid_skill_lines_for_port = wotlk_skill_lines

        new_rows: list[dict] = []
        era_bonus: dict[str, dict[str, list[float]]] = {}
        era_no_bonus: dict[str, list[int]] = {}
        era_ported: dict[str, dict[str, dict]] = {cfg["label"]: {} for cfg in ERA_CONFIG.values()}
        reused_ids: dict[str, list[int]] = {}
        era_rank_links: dict[str, list[list[int]]] = {}
        id_map: dict[str, dict[str, int]] = {}
        skipped_missing_wotlk: dict[str, list[int]] = {}

        for era in eras:
            cfg = ERA_CONFIG[era]
            root = getattr(args, cfg["root_arg"])
            label, offset = cfg["label"], cfg["id_offset"]
            print(f"\n[{label}] reading {root}", file=sys.stderr)

            if "Spell.dbc" not in BUILD_SCHEMAS[era]:
                print(f"[{label}] no Spell.dbc schema for build {era} -- skipping "
                      f"(see this tool's doc comment: Vanilla needs a 1.12.1 schema)", file=sys.stderr)
                continue

            era_spell = load_from_client(era, "Spell.dbc", root, tmp)
            era_tables = {name: load_from_client(era, name, root, tmp) for name in INDEX_VALUE_FIELDS}
            era_by_id = {r["ID"]: r for r in era_spell.rows}

            wanted = era_class_ids[era] & set(era_by_id)
            extra = era_side_spells(wanted, era_by_id)
            if extra - wanted:
                print(f"[{label}] +{len(extra - wanted)} spell(s) named by seals or era rules "
                      f"(judgements, Forbearance)", file=sys.stderr)
                wanted |= extra
            # Close over rank chains. Whether a rank is reachable through
            # SkillLineAbility varies within a single chain -- Pummel and
            # Nature Resist rank 1 have no row in either era client while
            # their later ranks do -- and cloning only part of a chain
            # leaves this era's version of that ability with a hole in the
            # middle, which anything walking the chain then trips over.
            # Restricted to ranks the era actually HAS: Water Shield and
            # Steady Shot rank 1 are WotLK-only ids, and an era that never
            # had them should not gain them here.
            if rank_chains:
                added = set()
                for members in rank_chains.values():
                    if members & wanted:
                        added |= (members & set(era_by_id)) - wanted
                if added:
                    wanted |= added
                    print(f"[{label}] +{len(added)} spell(s) pulled in to keep rank chains whole",
                          file=sys.stderr)
            if era == "1.12.1" and args.npc_spells and args.npc_spells.exists():
                npc = {int(x) for x in args.npc_spells.read_text().split() if x.strip()} & set(era_by_id)
                print(f"[{label}] +{len(npc - wanted)} creature-cast spell(s) from {args.npc_spells.name}",
                      file=sys.stderr)
                wanted |= npc
            if only is not None:
                wanted &= only
            print(f"[{label}] {len(wanted)} class spells to consider", file=sys.stderr)

            era_rows_start = len(new_rows)
            cloned = 0
            identical = 0
            ported_direct = 0
            missing: list[int] = []
            era_map: dict[str, int] = {}
            for spell_id in sorted(wanted):
                clone_id = spell_id + offset
                wotlk_row = wotlk_by_id.get(spell_id)
                reused = wotlk_row is not None and is_reused_id(spell_id, era_by_id[spell_id], wotlk_row)
                if reused:
                    reused_ids.setdefault(label, []).append(spell_id)
                    wotlk_row = None  # a different spell under this id: see is_reused_id
                if wotlk_row is None:
                    # WotLK deleted this spell outright (or reused its id
                    # for something else), so there is no row to overlay --
                    # port the era's own row wholesale.
                    #
                    # At the ERA id, not the original one. These are spells
                    # a character holds (Curse of Recklessness, Elune's
                    # Grace, Turn Undead), so they have to obey the same
                    # rule as every other class spell: a Vanilla character's
                    # are 300000-range ids and a TBC character's are
                    # 400000-range. Putting them back at their original id
                    # would make them the one kind of class spell shared
                    # between eras, which the gate has no way to separate.
                    new_rows.append(port_era_row(
                        era_by_id[spell_id], clone_id, era=era, remappers=remappers,
                        era_tables=era_tables, strings=strings, locale_count=locale_count))
                    era_map[str(spell_id)] = clone_id
                    # Recorded for build_era_spell_sql.py, which has to
                    # invent trainer rows for these: WotLK's database has no
                    # record of a spell WotLK deleted, so there is nothing
                    # to clone. It needs the class and level, which only
                    # exist in the era's own DBCs.
                    sla_rows = era_sla_by_spell[label].get(spell_id, [])
                    class_mask = 0
                    skill_line = 0
                    for sla_row in sla_rows:
                        if sla_row["SkillLine"] not in valid_skill_lines_for_port:
                            continue
                        skill_line = skill_line or sla_row["SkillLine"]
                        class_mask = class_mask or sla_row["ClassMask"] or \
                            line_class_mask.get(sla_row["SkillLine"], 0)
                    era_ported[label][str(spell_id)] = {
                        "clone": clone_id,
                        "classMask": class_mask,
                        "level": era_by_id[spell_id]["SpellLevel"] or era_by_id[spell_id]["BaseLevel"],
                        "skillLine": skill_line,
                        "reused": reused,
                    }
                    ported_direct += 1
                    continue
                clone, changed = build_clone(
                    era_by_id[spell_id], wotlk_row, clone_id,
                    remappers=remappers, era_tables=era_tables,
                    strings=strings, locale_count=locale_count,
                    tag=label if args.tag_names else None,
                )
                if not changed:
                    # Identical to WotLK's own version. Cloned ANYWAY, and
                    # that is deliberate -- skipping these was a real bug.
                    #
                    # Rank chains are the clearest case: WotLK Holy Light
                    # rank 5 happens to match Vanilla's, so skipping it left
                    # the Vanilla chain as ranks 1-4, 6-13 with a hole where
                    # rank 5 should be (4 chains Vanilla, 10 TBC, TBC Aimed
                    # Shot missing its first six). Anything that reasons
                    # over a chain -- trainers offering the next rank,
                    # learnSpell superseding the previous one -- then sees a
                    # broken one.
                    #
                    # It also makes era separation total: every class spell
                    # a Vanilla character knows is a 300000-range id, with
                    # no WotLK ids mixed in, which is a far simpler rule for
                    # the era gate to enforce than "these ids, plus those
                    # shared ones". The cost is about 1,200 extra rows on a
                    # 53,000-row file.
                    identical += 1
                new_rows.append(clone)
                era_map[str(spell_id)] = clone_id
                cloned += 1
                if only is not None:
                    name = wotlk_row["Name_lang"]["enUS"]
                    print(f"    {spell_id} -> {clone_id}  {name}: {', '.join(changed) or '(name tag only)'}")

            # Seal of Light / Wisdom clones still trigger the shared proc
            # half WotLK rewrote; point them at this era's copy instead.
            era_procs = seal_proc_halves(wanted, era_by_id)
            seal_era_ids = {int(k): v for k, v in era_map.items()}
            repointed = remap_seal_procs(new_rows[era_rows_start:], offset, seal_era_ids, era_procs)
            era_no_bonus[label] = sorted({seal_era_ids[p] for _, p in era_procs.values() if p in seal_era_ids})
            print(f"[{label}] pointed {len(repointed)} seal(s) at this era's copy of their proc "
                  f"(flat, no spell power): {repointed}", file=sys.stderr)

            # Transitive port: a clone can point at a spell WotLK deleted
            # (Vanilla Lightning Shield triggers 26545, Execute triggers
            # 26651, ...). Left alone the clone still casts but its trigger
            # does nothing, which is the quiet kind of broken. Port those
            # rows in at their ORIGINAL ids -- safe because by definition
            # WotLK has nothing there, and verified to be conflict-free
            # across eras (where Vanilla and TBC both want an id, the two
            # rows are identical).
            #
            # Loops because a ported row can itself reference another
            # missing spell.
            present = set(wotlk_by_id) | {r["ID"] for r in new_rows} | reserved
            ported_here = 0
            unportable: list[int] = []
            # (row, the WotLK row it was cloned from -- None for a ported
            # row, which has no WotLK counterpart by definition).
            clone_ids = set(era_map.values())
            # A row ported wholesale (a spell WotLK deleted) has no WotLK
            # counterpart, so it pairs with None -- meaning every spell it
            # references is chased, none of them excusable as "already
            # dangling upstream".
            ported_clone_ids = {info["clone"] for info in era_ported[label].values()}
            frontier = [(r, None if r["ID"] in ported_clone_ids else wotlk_by_id.get(r["ID"] - offset))
                        for r in new_rows if r["ID"] in clone_ids]
            while frontier:
                wanted: set[int] = set()
                for row, wotlk_src in frontier:
                    for f in SPELL_REF_FIELDS:
                        ref = row[f]
                        if not ref or ref in present:
                            continue
                        if wotlk_src is not None and wotlk_src[f] == ref:
                            # Dangling in WotLK's own row already, and the
                            # clone just kept it. Not something cloning
                            # introduced, so not ours to chase.
                            continue
                        wanted.add(ref)
                frontier = []
                for ref in sorted(wanted):
                    era_src = era_by_id.get(ref)
                    if era_src is None:
                        # Dangling in the era's OWN client data too -- there
                        # is nothing to port. Authentic to the source, and
                        # reported rather than papered over.
                        unportable.append(ref)
                        present.add(ref)
                        continue
                    ported = port_era_row(
                        era_src, ref, era=era, remappers=remappers,
                        era_tables=era_tables, strings=strings, locale_count=locale_count)
                    new_rows.append(ported)
                    present.add(ref)
                    frontier.append((ported, None))
                    ported_here += 1
            if ported_here or unportable:
                print(f"[{label}] ported {ported_here} spell(s) WotLK deleted but these clones "
                      f"reference; {len(unportable)} referenced id(s) absent from the era client too "
                      f"{sorted(unportable)}", file=sys.stderr)

            era_ids = {int(k): v for k, v in era_map.items()}
            retexted = 0
            for row in new_rows[era_rows_start:]:
                for field in ("Description_lang", "AuraDescription_lang"):
                    text = row[field]["enUS"]
                    remapped = remap_era_text_refs(text, era_ids)
                    if remapped != text:
                        row[field] = new_loc_string(strings, remapped, locale_count)
                        retexted += 1
            print(f"[{label}] pointed {retexted} tooltip(s) at this era's copies of the spells they name",
                  file=sys.stderr)

            if label == "Vanilla":
                by_id = {r["ID"]: r for r in new_rows[era_rows_start:]}
                casts = {r["ID"]: r["Base"] for r in wotlk_tables["SpellCastTimes.dbc"].rows}
                durations = {r["ID"]: r["Duration"] for r in wotlk_tables["SpellDuration.dbc"].rows}
                bonus: dict[str, list[float]] = {}
                for base_id, clone_id in era_ids.items():
                    row = by_id[clone_id]
                    if clone_id in era_no_bonus[label]:
                        continue  # zero row from build_era_spell_sql.py (seal_proc_halves)
                    if base_id in VANILLA_BONUS_OVERRIDES:
                        bonus[str(clone_id)] = list(VANILLA_BONUS_OVERRIDES[base_id])
                        continue
                    coeffs = vanilla_coefficients(row, casts.get(row["CastingTimeIndex"], 0),
                                                  durations.get(row["DurationIndex"], 0))
                    if coeffs is not None:
                        bonus[str(clone_id)] = [coeffs[0], coeffs[1], 0.0]
                era_bonus[label] = bonus
                print(f"[{label}] {len(bonus)} spell power coefficient(s) under the 1.12 rule",
                      file=sys.stderr)

            not_trainable = untrainable_ported(
                era_ported[label], era_by_id, era_sla_by_spell[label],
                class_skill_lines(root), talent_rank_spells(era, root, tmp))
            for spell_id, info in era_ported[label].items():
                info["trainable"] = int(spell_id) not in not_trainable
            print(f"[{label}] {len(era_ported[label]) - len(not_trainable)} of the "
                  f"{len(era_ported[label])} spell(s) WotLK deleted are trainer spells "
                  f"(the rest are talent ranks, procs and automatic grants)", file=sys.stderr)

            era_rank_links[label] = rank_links_touching_ported(
                era_map, {int(s) for s in era_ported[label]}, era_by_id, era_sla_by_spell[label])

            id_map[label] = era_map
            skipped_missing_wotlk[label] = missing
            print(f"[{label}] cloned {cloned} ({identical} byte-identical to WotLK, cloned anyway to "
                  f"keep rank chains whole), ported {ported_direct} spell(s) WotLK deleted outright",
                  file=sys.stderr)

        # Fail loudly rather than let a serverside spell quietly replace a
        # clone (see ERA_CONFIG). The list is dumped from the live realm by
        # tools/server/dump_reserved_spell_ids.sh; a build without it says
        # so instead of pretending it checked.
        if reserved:
            clash = sorted({r["ID"] for r in new_rows} & reserved)
            if clash:
                print(f"error: {len(clash)} era spell id(s) collide with serverside spells already "
                      f"defined in the `spell_dbc` world table: {clash[:20]}\n"
                      f"       Those rows load AFTER Spell.dbc and would override these clones. "
                      f"Move ERA_CONFIG's id_offset clear of them.", file=sys.stderr)
                return 1
            print(f"  checked {len(new_rows)} new row ids against {len(reserved)} reserved "
                  f"serverside spell ids: no collisions", file=sys.stderr)

        shields = [r["ID"] for r in new_rows if as_immune_shield(r)]
        print(f"  tagged {len(shields)} era immunity bubble(s) as WotLK immune shields: {shields}",
              file=sys.stderr)
        seals = [r["ID"] for r in new_rows if as_wotlk_seal(r)]
        print(f"  gave {len(seals)} ported era seal(s) a WotLK seal family bit: {seals}", file=sys.stderr)
        vanilla = range(ERA_CONFIG["1.12.1"]["id_offset"], ERA_CONFIG["2.4.3"]["id_offset"])
        unmarked = [r["ID"] for r in new_rows if r["ID"] in vanilla and drop_wotlk_paladin_markers(r)]
        print(f"  dropped WotLK's paladin marker auras from {len(unmarked)} Vanilla row(s): {unmarked}",
              file=sys.stderr)
        bandages = allow_bandage_while_pacified(base.rows)
        print(f"  {len(bandages)} bandage spell(s) usable while pacified again", file=sys.stderr)
        offsets = sorted((cfg["id_offset"] for cfg in ERA_CONFIG.values()), reverse=True)
        rewritten = [r["ID"] for r in new_rows if r["ID"] >= offsets[-1]
                     and apply_era_talent_rewrites(r, r["ID"] - next(o for o in offsets if r["ID"] >= o))]
        print(f"  rewrote {len(rewritten)} era talent row(s) (ERA_WARD_REFLECT_TALENTS, "
              f"ERA_HIDDEN_FROM_CORE): {rewritten}", file=sys.stderr)

        base.rows.extend(new_rows)
        base.rows.sort(key=lambda r: r["ID"])
        base.string_block = strings.build()
        out_spell = args.out_dir / "Spell.dbc"
        write_dbc(out_spell, base)
        print(f"\nwrote {out_spell}: {len(base.rows)} rows (+{len(new_rows)} era clones), "
              f"max id {max(r['ID'] for r in base.rows)}", file=sys.stderr)

        for name, remapper in remappers.items():
            if remapper.appended:
                out = args.out_dir / name
                write_dbc(out, wotlk_tables[name])
                print(f"wrote {out}: +{remapper.appended} new rows "
                      f"(era values WotLK's table had no equivalent for)", file=sys.stderr)

        # SkillLineAbility: the realm mounts mod-individual-progression's
        # copy (docker-compose.override.yml), so that -- not the stock
        # client's -- is what clone rows have to be added to, or its own
        # edits would be dropped.
        sla_base_path = args.base_skill_line_ability
        if sla_base_path and sla_base_path.exists():
            base_sla = read_dbc(sla_base_path, BUILD_SCHEMAS["3.3.5a"]["SkillLineAbility.dbc"],
                                LOCALE_COUNT["3.3.5a"])
            print(f"  base SkillLineAbility.dbc: {sla_base_path} ({len(base_sla.rows)} rows)", file=sys.stderr)
        else:
            base_sla = load_from_client("3.3.5a", "SkillLineAbility.dbc", args.wotlk_root, tmp)
        sla_rows, auto_learn_lost = build_skill_line_abilities(
            base_sla, id_map, {ERA_CONFIG[e]["label"]: ERA_CONFIG[e]["id_offset"] for e in ERA_CONFIG},
            era_sla_by_spell, wotlk_skill_lines,
            {label: {int(s) for s in ported} for label, ported in era_ported.items()})
        base_sla.rows.extend(sla_rows)
        base_sla.rows.sort(key=lambda r: r["ID"])
        out_sla = args.out_dir / "SkillLineAbility.dbc"
        write_dbc(out_sla, base_sla)
        print(f"wrote {out_sla}: {len(base_sla.rows)} rows (+{len(sla_rows)} for era clones); "
              f"{auto_learn_lost} of them had AcquireMethod != 0 and are now trainer-only "
              f"(they need granting by our own code)", file=sys.stderr)

        out_map = args.out_dir / "era-spell-map.json"
        out_map.write_text(json.dumps(
            {"id_map": id_map, "deleted_by_wotlk": skipped_missing_wotlk,
             "ported": era_ported, "reused": reused_ids, "supersede": era_rank_links,
             "bonus": era_bonus, "no_bonus": era_no_bonus},
            indent=2), encoding="utf-8")
        for label, ids in reused_ids.items():
            print(f"[{label}] {len(ids)} id(s) WotLK reused for a different spell, ported whole "
                  f"(see is_reused_id)", file=sys.stderr)
        print(f"wrote {out_map}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

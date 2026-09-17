"""
Per-build DBC schemas used by this project.

Sourced from the community-maintained WoWDBDefs project
(https://github.com/wowdev/WoWDBDefs, definitions/*.dbd), cross-checked
against the exact client build ranges we target:
    - Vanilla 1.12.1  -> build range 1.0.0.3980-1.12.3.6141
    - TBC 2.4.3       -> build range 2.0.0.5610-2.4.3.8606
    - WotLK 3.3.5a    -> build range 3.0.1.8622-3.3.5.12340

Talent.dbc and TalentTab.dbc use IDENTICAL field layouts across Vanilla and
TBC (only loc_string locale_count differs: 8 vs 16 -- see wdbc.LOCALE_COUNT).
WotLK's 3.3.5a layout adds CategoryMask/CategoryEnumID fields on top of the
Vanilla/TBC layout, so it is NOT a drop-in match -- kept as a separate schema.

Spell.dbc layouts for TBC 2.4.3 (build 2.4.3.8606) and WotLK 3.3.5a (build
3.3.3.11685-3.3.5.12340) differ meaningfully -- WotLK drops CastUI/
EffectBaseDice/EffectDicePerLevel, widens ShapeshiftMask/ShapeshiftExclude/
SpellClassMask to arrays, adds the CasterAuraSpell/TargetAuraSpell/
ExcludeCasterAuraSpell/ExcludeTargetAuraSpell quad, AttributesExG,
EffectSpellClassMaskA/B/C, and a RuneCostID..Difficulty tail. Each is its own
schema below rather than derived from the other, to avoid silently
misaligning fields if a future edit touches one but not the other.
"""
from __future__ import annotations

try:
    from .wdbc import FieldSpec as F
    from .wdbc import Schema
except ImportError:  # allows running tools in this dir as standalone scripts
    from wdbc import FieldSpec as F
    from wdbc import Schema


def _array(name: str, type_: str, count: int) -> list[F]:
    return [F(f"{name}_{i}", type_) for i in range(count)]

# --- Talent.dbc -------------------------------------------------------

TALENT_VANILLA_TBC: Schema = [
    F("ID", "int32"),
    F("TabID", "int32"),
    F("TierID", "int32"),
    F("ColumnIndex", "int32"),
    F("SpellRank_0", "int32"),
    F("SpellRank_1", "int32"),
    F("SpellRank_2", "int32"),
    F("SpellRank_3", "int32"),
    F("SpellRank_4", "int32"),
    F("SpellRank_5", "int32"),
    F("SpellRank_6", "int32"),
    F("SpellRank_7", "int32"),
    F("SpellRank_8", "int32"),
    F("PrereqTalent_0", "int32"),
    F("PrereqTalent_1", "int32"),
    F("PrereqTalent_2", "int32"),
    F("PrereqRank_0", "int32"),
    F("PrereqRank_1", "int32"),
    F("PrereqRank_2", "int32"),
    F("Flags", "int32"),
    F("RequiredSpellID", "int32"),
]

TALENT_WOTLK: Schema = TALENT_VANILLA_TBC + [
    F("CategoryMask_0", "int32"),
    F("CategoryMask_1", "int32"),
]

SPELL_RANK_FIELDS = [f"SpellRank_{i}" for i in range(9)]
PREREQ_TALENT_FIELDS = [f"PrereqTalent_{i}" for i in range(3)]
PREREQ_RANK_FIELDS = [f"PrereqRank_{i}" for i in range(3)]

# --- TalentTab.dbc ------------------------------------------------------

TALENT_TAB_VANILLA_TBC: Schema = [
    F("ID", "int32"),
    F("Name_lang", "loc_string"),
    F("SpellIconID", "int32"),
    F("RaceMask", "int32"),
    F("ClassMask", "int32"),
    F("OrderIndex", "int32"),
    F("BackgroundFile", "string"),
]

TALENT_TAB_WOTLK: Schema = [
    F("ID", "int32"),
    F("Name_lang", "loc_string"),
    F("SpellIconID", "int32"),
    F("RaceMask", "int32"),
    F("ClassMask", "int32"),
    F("CategoryEnumID", "int32"),
    F("OrderIndex", "int32"),
    F("BackgroundFile", "string"),
]

# --- SpellIcon.dbc (identical across all three target builds) ----------

SPELL_ICON: Schema = [
    F("ID", "int32"),
    F("TextureFilename", "string"),
]

# --- Spell.dbc: TBC 2.4.3 (build 2.4.3.8606) ----------------------------

SPELL_TBC: Schema = [
    F("ID", "int32"),
    F("Category", "int32"),
    F("CastUI", "int32"),
    F("DispelType", "int32"),
    F("Mechanic", "int32"),
    F("Attributes", "int32"),
    F("AttributesEx", "int32"),
    F("AttributesExB", "int32"),
    F("AttributesExC", "int32"),
    F("AttributesExD", "int32"),
    F("AttributesExE", "int32"),
    F("AttributesExF", "int32"),
    F("ShapeshiftMask", "int32"),
    F("ShapeshiftExclude", "int32"),
    F("Targets", "int32"),
    F("TargetCreatureType", "int32"),
    F("RequiresSpellFocus", "int32"),
    F("FacingCasterFlags", "int32"),
    F("CasterAuraState", "int32"),
    F("TargetAuraState", "int32"),
    F("ExcludeCasterAuraState", "int32"),
    F("ExcludeTargetAuraState", "int32"),
    F("CastingTimeIndex", "int32"),
    F("RecoveryTime", "int32"),
    F("CategoryRecoveryTime", "int32"),
    F("InterruptFlags", "int32"),
    F("AuraInterruptFlags", "int32"),
    F("ChannelInterruptFlags", "int32"),
    F("ProcTypeMask", "int32"),
    F("ProcChance", "int32"),
    F("ProcCharges", "int32"),
    F("MaxLevel", "int32"),
    F("BaseLevel", "int32"),
    F("SpellLevel", "int32"),
    F("DurationIndex", "int32"),
    F("PowerType", "int32"),
    F("ManaCost", "int32"),
    F("ManaCostPerLevel", "int32"),
    F("ManaPerSecond", "int32"),
    F("ManaPerSecondPerLevel", "int32"),
    F("RangeIndex", "int32"),
    F("Speed", "float32"),
    F("ModalNextSpell", "int32"),
    F("CumulativeAura", "int32"),
    *_array("Totem", "int32", 2),
    *_array("Reagent", "int32", 8),
    *_array("ReagentCount", "int32", 8),
    F("EquippedItemClass", "int32"),
    F("EquippedItemSubclass", "int32"),
    F("EquippedItemInvTypes", "int32"),
    *_array("Effect", "int32", 3),
    *_array("EffectDieSides", "int32", 3),
    *_array("EffectBaseDice", "int32", 3),
    *_array("EffectDicePerLevel", "int32", 3),
    *_array("EffectRealPointsPerLevel", "float32", 3),
    *_array("EffectBasePoints", "int32", 3),
    *_array("EffectMechanic", "int32", 3),
    *_array("ImplicitTargetA", "int32", 3),
    *_array("ImplicitTargetB", "int32", 3),
    *_array("EffectRadiusIndex", "int32", 3),
    *_array("EffectAura", "int32", 3),
    *_array("EffectAuraPeriod", "int32", 3),
    *_array("EffectAmplitude", "float32", 3),
    *_array("EffectChainTargets", "int32", 3),
    *_array("EffectItemType", "int32", 3),
    *_array("EffectMiscValue", "int32", 3),
    *_array("EffectMiscValueB", "int32", 3),
    *_array("EffectTriggerSpell", "int32", 3),
    *_array("EffectPointsPerCombo", "float32", 3),
    *_array("SpellVisualID", "int32", 2),
    F("SpellIconID", "int32"),
    F("ActiveIconID", "int32"),
    F("SpellPriority", "int32"),
    F("Name_lang", "loc_string"),
    F("NameSubtext_lang", "loc_string"),
    F("Description_lang", "loc_string"),
    F("AuraDescription_lang", "loc_string"),
    F("ManaCostPct", "int32"),
    F("StartRecoveryCategory", "int32"),
    F("StartRecoveryTime", "int32"),
    F("MaxTargetLevel", "int32"),
    F("SpellClassSet", "int32"),
    *_array("SpellClassMask", "int32", 2),
    F("MaxTargets", "int32"),
    F("DefenseType", "int32"),
    F("PreventionType", "int32"),
    F("StanceBarOrder", "int32"),
    *_array("EffectChainAmplitude", "float32", 3),
    F("MinFactionID", "int32"),
    F("MinReputation", "int32"),
    F("RequiredAuraVision", "int32"),
    *_array("RequiredTotemCategoryID", "int32", 2),
    F("RequiredAreasID", "int32"),
    F("SchoolMask", "int32"),
]

# --- Spell.dbc: WotLK 3.3.5a (build 3.3.3.11685-3.3.5.12340) ------------

SPELL_WOTLK: Schema = [
    F("ID", "int32"),
    F("Category", "int32"),
    F("DispelType", "int32"),
    F("Mechanic", "int32"),
    F("Attributes", "int32"),
    F("AttributesEx", "int32"),
    F("AttributesExB", "int32"),
    F("AttributesExC", "int32"),
    F("AttributesExD", "int32"),
    F("AttributesExE", "int32"),
    F("AttributesExF", "int32"),
    F("AttributesExG", "int32"),
    *_array("ShapeshiftMask", "int32", 2),
    *_array("ShapeshiftExclude", "int32", 2),
    F("Targets", "int32"),
    F("TargetCreatureType", "int32"),
    F("RequiresSpellFocus", "int32"),
    F("FacingCasterFlags", "int32"),
    F("CasterAuraState", "int32"),
    F("TargetAuraState", "int32"),
    F("ExcludeCasterAuraState", "int32"),
    F("ExcludeTargetAuraState", "int32"),
    F("CasterAuraSpell", "int32"),
    F("TargetAuraSpell", "int32"),
    F("ExcludeCasterAuraSpell", "int32"),
    F("ExcludeTargetAuraSpell", "int32"),
    F("CastingTimeIndex", "int32"),
    F("RecoveryTime", "int32"),
    F("CategoryRecoveryTime", "int32"),
    F("InterruptFlags", "int32"),
    F("AuraInterruptFlags", "int32"),
    F("ChannelInterruptFlags", "int32"),
    F("ProcTypeMask", "int32"),
    F("ProcChance", "int32"),
    F("ProcCharges", "int32"),
    F("MaxLevel", "int32"),
    F("BaseLevel", "int32"),
    F("SpellLevel", "int32"),
    F("DurationIndex", "int32"),
    F("PowerType", "int32"),
    F("ManaCost", "int32"),
    F("ManaCostPerLevel", "int32"),
    F("ManaPerSecond", "int32"),
    F("ManaPerSecondPerLevel", "int32"),
    F("RangeIndex", "int32"),
    F("Speed", "float32"),
    F("ModalNextSpell", "int32"),
    F("CumulativeAura", "int32"),
    *_array("Totem", "int32", 2),
    *_array("Reagent", "int32", 8),
    *_array("ReagentCount", "int32", 8),
    F("EquippedItemClass", "int32"),
    F("EquippedItemSubclass", "int32"),
    F("EquippedItemInvTypes", "int32"),
    *_array("Effect", "int32", 3),
    *_array("EffectDieSides", "int32", 3),
    *_array("EffectRealPointsPerLevel", "float32", 3),
    *_array("EffectBasePoints", "int32", 3),
    *_array("EffectMechanic", "int32", 3),
    *_array("ImplicitTargetA", "int32", 3),
    *_array("ImplicitTargetB", "int32", 3),
    *_array("EffectRadiusIndex", "int32", 3),
    *_array("EffectAura", "int32", 3),
    *_array("EffectAuraPeriod", "int32", 3),
    *_array("EffectAmplitude", "float32", 3),
    *_array("EffectChainTargets", "int32", 3),
    *_array("EffectItemType", "int32", 3),
    *_array("EffectMiscValue", "int32", 3),
    *_array("EffectMiscValueB", "int32", 3),
    *_array("EffectTriggerSpell", "int32", 3),
    *_array("EffectPointsPerCombo", "float32", 3),
    *_array("EffectSpellClassMaskA", "int32", 3),
    *_array("EffectSpellClassMaskB", "int32", 3),
    *_array("EffectSpellClassMaskC", "int32", 3),
    *_array("SpellVisualID", "int32", 2),
    F("SpellIconID", "int32"),
    F("ActiveIconID", "int32"),
    F("SpellPriority", "int32"),
    F("Name_lang", "loc_string"),
    F("NameSubtext_lang", "loc_string"),
    F("Description_lang", "loc_string"),
    F("AuraDescription_lang", "loc_string"),
    F("ManaCostPct", "int32"),
    F("StartRecoveryCategory", "int32"),
    F("StartRecoveryTime", "int32"),
    F("MaxTargetLevel", "int32"),
    F("SpellClassSet", "int32"),
    *_array("SpellClassMask", "int32", 3),
    F("MaxTargets", "int32"),
    F("DefenseType", "int32"),
    F("PreventionType", "int32"),
    F("StanceBarOrder", "int32"),
    *_array("EffectChainAmplitude", "float32", 3),
    F("MinFactionID", "int32"),
    F("MinReputation", "int32"),
    F("RequiredAuraVision", "int32"),
    *_array("RequiredTotemCategoryID", "int32", 2),
    F("RequiredAreasID", "int32"),
    F("SchoolMask", "int32"),
    F("RuneCostID", "int32"),
    F("SpellMissileID", "int32"),
    F("PowerDisplayID", "int32"),
    *_array("EffectBonusCoefficient", "float32", 3),
    F("DescriptionVariablesID", "int32"),
    F("Difficulty", "int32"),
]

EFFECT_FIELDS = ["Effect", "EffectBasePoints", "EffectAura", "EffectTriggerSpell",
                 "EffectMiscValue", "EffectMiscValueB", "EffectMechanic",
                 "EffectDieSides", "EffectAuraPeriod", "EffectAmplitude",
                 "EffectRadiusIndex", "EffectChainTargets", "EffectItemType",
                 "EffectPointsPerCombo", "ImplicitTargetA", "ImplicitTargetB"]


def spell_effect_indexed(row: dict, base_name: str, i: int):
    """row[f'{base_name}_{i}'] convenience accessor for a Spell.dbc effect-slot field."""
    return row[f"{base_name}_{i}"]

# --- per-build registry --------------------------------------------------

BUILD_SCHEMAS = {
    "1.12.1": {
        "Talent.dbc": TALENT_VANILLA_TBC,
        "TalentTab.dbc": TALENT_TAB_VANILLA_TBC,
        "SpellIcon.dbc": SPELL_ICON,
    },
    "2.4.3": {
        "Talent.dbc": TALENT_VANILLA_TBC,
        "TalentTab.dbc": TALENT_TAB_VANILLA_TBC,
        "SpellIcon.dbc": SPELL_ICON,
        "Spell.dbc": SPELL_TBC,
    },
    "3.3.5a": {
        "Talent.dbc": TALENT_WOTLK,
        "TalentTab.dbc": TALENT_TAB_WOTLK,
        "SpellIcon.dbc": SPELL_ICON,
        "Spell.dbc": SPELL_WOTLK,
    },
}

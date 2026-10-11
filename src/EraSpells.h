/*
 * Shared era-spell definitions for EraSpellGate.cpp / EraSpellSync.cpp.
 *
 * Id ranges must stay in sync with tools/build_patch/build_era_spells.py's
 * ERA_CONFIG: a class spell's Vanilla copy is its WotLK id + 300000 and its
 * TBC copy is + 400000. Those offsets are deliberately clear of the
 * 100000-200000 band, which AzerothCore and several modules use for their
 * own serverside spells (`spell_dbc`) -- see that tool's ERA_CONFIG comment.
 *
 * The era a character is entitled to is NekoEraTalents::EraOfPlayer, reused
 * rather than reimplemented so spells and talents can never disagree about
 * which era someone is in.
 */
#pragma once

#include "Define.h"
#include "DBCStores.h"
#include "Player.h"
#include "SpellMgr.h"

#include "EraTalents.h"

namespace NekoEraSpells
{
    using NekoEraTalents::Era;
    using NekoEraTalents::ERA_WOTLK;
    using NekoEraTalents::ERA_VANILLA;
    using NekoEraTalents::ERA_TBC;

    constexpr uint32 VANILLA_SPELL_OFFSET = 300000;
    constexpr uint32 TBC_SPELL_OFFSET = 400000;
    constexpr uint32 ERA_SPELL_MIN = VANILLA_SPELL_OFFSET;
    constexpr uint32 ERA_SPELL_MAX = TBC_SPELL_OFFSET + 99999;

    inline Era EraOfSpell(uint32 spellId)
    {
        if (spellId >= TBC_SPELL_OFFSET && spellId <= ERA_SPELL_MAX)
            return ERA_TBC;
        if (spellId >= VANILLA_SPELL_OFFSET && spellId < TBC_SPELL_OFFSET)
            return ERA_VANILLA;
        return ERA_WOTLK;
    }

    inline uint32 OffsetOfEra(Era era)
    {
        switch (era)
        {
            case ERA_VANILLA: return VANILLA_SPELL_OFFSET;
            case ERA_TBC:     return TBC_SPELL_OFFSET;
            default:          return 0;
        }
    }

    /// The WotLK spell an era copy was made from; `spellId` itself if it is
    /// not an era copy.
    inline uint32 BaseSpellOf(uint32 spellId)
    {
        return spellId - OffsetOfEra(EraOfSpell(spellId));
    }

    /// That era's copy of `baseSpellId`, or 0 when there is none.
    ///
    /// Asking sSpellStore is the authoritative test and costs an array
    /// index: build_era_spells.py only emits a clone for a spell the era
    /// actually has, so "the row exists" and "this era has its own version"
    /// are the same question.
    inline uint32 EraSpellFor(Era era, uint32 baseSpellId)
    {
        uint32 const offset = OffsetOfEra(era);
        if (!offset || baseSpellId >= ERA_SPELL_MIN)
            return 0;
        uint32 const candidate = baseSpellId + offset;
        return sSpellStore.LookupEntry(candidate) ? candidate : 0;
    }

    /// Whether this spell is a talent's own rank spell.
    ///
    /// Era talent trees still point at the SHARED WotLK spell ids (see
    /// build_era_tree.py), and the core tracks a learned talent by looking
    /// its spell up in sTalentSpellPosMap. Swapping such a spell for an era
    /// copy would leave that lookup with nothing to find and quietly break
    /// the talent's bookkeeping, so these are left alone entirely until the
    /// talent trees are rebuilt against era spell ids.
    inline bool IsTalentRankSpell(uint32 spellId)
    {
        return GetTalentSpellPos(spellId) != nullptr;
    }

    /// The WotLK gathering perks: Toughness (Mining), Master of Anatomy
    /// (Skinning) and Lifeblood (Herbalism), every rank. SkillLineAbility
    /// grants them automatically as the skill rises (AcquireMethod 1), so
    /// they bypass trainers entirely and have no era copy to swap to --
    /// Vanilla and TBC simply did not have them.
    inline bool IsWotlkOnlyProfessionPerk(uint32 spellId)
    {
        switch (spellId)
        {
            case 53120: case 53121: case 53122: case 53123: case 53124: case 53040: // Toughness
            case 53125: case 53662: case 53663: case 53664: case 53665: case 53666: // Master of Anatomy
            case 55428: case 55480: case 55500: case 55501: case 55502: case 55503: // Lifeblood
                return true;
            default:
                return false;
        }
    }

    /// The racial skill lines (Dwarven, Tauren, Orcish, Night Elf, Troll,
    /// Undead, Gnomish, Human, Blood Elf, Draenei). Must match
    /// build_era_spells.py's RACIAL_SKILL_LINES, which is what gives every
    /// racial an era copy.
    constexpr uint32 RACIAL_SKILL_LINES[] = { 101, 124, 125, 126, 220, 733, 753, 754, 756, 760 };

    inline bool IsRacialSpell(uint32 spellId)
    {
        SkillLineAbilityMapBounds const bounds = sSpellMgr->GetSkillLineAbilityMapBounds(spellId);
        for (auto it = bounds.first; it != bounds.second; ++it)
            for (uint32 line : RACIAL_SKILL_LINES)
                if (it->second->SkillLine == line)
                    return true;
        return false;
    }

    /// Race bits the era's client had: Blood Elf and Draenei came with TBC.
    inline uint32 EraRaceMask(Era era)
    {
        switch (era)
        {
            case ERA_VANILLA: return 0x0FF;
            case ERA_TBC:     return 0x6FF;
            default:          return 0;
        }
    }

    /// A racial WotLK added (Every Man for Himself, the per-class Gift of the
    /// Naaru, the Death Knight Blood Fury): the era has no copy of it, so it
    /// must not be kept. Every racial the era DID have is cloned by
    /// build_era_spells.py, so "racial with no era copy" is exactly this set.
    ///
    /// Not applied to a race the era did not have (a Blood Elf in Vanilla):
    /// their racials exist in no copy of that era, and dropping the WotLK
    /// ones would leave them with nothing.
    inline bool IsRacialAddedAfterEra(Player const* player, Era era, uint32 spellId)
    {
        if (era == ERA_WOTLK || spellId >= ERA_SPELL_MIN)
            return false;
        if (!(player->getRaceMask() & EraRaceMask(era)))
            return false;
        return IsRacialSpell(spellId) && !EraSpellFor(era, spellId);
    }

    /// Skill lines whose rewarded spells include those perks.
    constexpr uint32 PERK_SKILL_LINES[] = { 186 /*Mining*/, 393 /*Skinning*/, 182 /*Herbalism*/ };

    /// Moves every class spell the character holds onto `targetEra`'s own
    /// copies, dropping any that era does not have, and drags the action
    /// bars along. Returns how many spells changed. Defined in
    /// EraSpellSync.cpp; used both at login and on an era transition.
    uint32 ReconcileSpellsToEra(Player* player, Era targetEra);
}

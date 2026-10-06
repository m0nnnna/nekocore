/*
 * Core behaviour that keys on WotLK data an era copy does not have, put
 * back for the era copies. Each fix here is a place where AzerothCore asks
 * "is this spell X?" by a WotLK-only detail (an effect type, a skill-line
 * flag build_era_spells.py had to drop) and an era copy answers no:
 *
 *   - ranked auras and forms that should replace their lower rank;
 *   - weapon and armour proficiency copies that should teach their skill;
 *   - Seal of the Crusader's "attacks faster, but deals less damage".
 */

#include "ScriptMgr.h"
#include "DBCStores.h"
#include "Player.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellMgr.h"

#include "EraSpells.h"

namespace
{
    using namespace NekoEraSpells;

    /// Whether an era spell is a stance-bar spell whose ranks must replace
    /// one another, like WotLK's own.
    ///
    /// SpellInfo::ComputeIsStackableWithRanks finds paladin auras by
    /// SPELL_EFFECT_APPLY_AREA_AURA_RAID and forms only in the druid family.
    /// Vanilla paladin auras are APPLY_AREA_AURA_PARTY, and Vanilla Stealth
    /// is a ranked rogue form, so every rank stayed active side by side and
    /// a paladin's stance bar showed Devotion Aura rank 1 and rank 2.
    bool IsEraStanceSpell(SpellInfo const* info)
    {
        for (SpellEffectInfo const& effect : info->GetEffects())
        {
            if (info->SpellFamilyName == SPELLFAMILY_PALADIN && effect.IsEffect(SPELL_EFFECT_APPLY_AREA_AURA_PARTY))
                return true;
            if (effect.IsAura(SPELL_AURA_MOD_SHAPESHIFT))
                return true;
        }
        return false;
    }

    /// Learns the skill a proficiency spell grants, for era copies.
    ///
    /// Learning One-Handed Swords (201) teaches the Swords skill because its
    /// SkillLineAbility row is AcquireMethod 1 (Player::_addSpell).
    /// build_era_spells.py has to give every era copy's row AcquireMethod 0,
    /// or Player's skill-reward pass would hand out every era's copies, so a
    /// Vanilla character who bought 300201 got the spell and no skill --
    /// "You do not have the required proficiency for that item". The WotLK
    /// row of the spell it was copied from still says which skill it is.
    void LearnEraSpellSkill(Player* player, uint32 spellId)
    {
        if (EraOfSpell(spellId) == ERA_WOTLK)
            return;

        SkillLineAbilityMapBounds const bounds = sSpellMgr->GetSkillLineAbilityMapBounds(BaseSpellOf(spellId));
        for (auto itr = bounds.first; itr != bounds.second; ++itr)
        {
            SkillLineAbilityEntry const* ability = itr->second;
            if (ability->AcquireMethod != SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN)
                continue;
            if (!sSkillLineStore.LookupEntry(ability->SkillLine) || player->HasSkill(ability->SkillLine))
                continue;
            if (ability->RaceMask && !(ability->RaceMask & player->getRaceMask()))
                continue;
            if (ability->ClassMask && !(ability->ClassMask & player->getClassMask()))
                continue;
            player->LearnDefaultSkill(ability->SkillLine, 0);
        }
    }
}

class EraSpellFixups_World : public WorldScript
{
public:
    EraSpellFixups_World() : WorldScript("EraSpellFixups_World", { WORLDHOOK_ON_BEFORE_WORLD_INITIALIZED }) { }

    // After ObjectMgr::InitializeSpellInfoPrecomputedData, which is where
    // the core computes the flag.
    void OnBeforeWorldInitialized() override
    {
        uint32 changed = 0;
        for (uint32 id = ERA_SPELL_MIN; id <= ERA_SPELL_MAX; ++id)
        {
            SpellInfo const* info = sSpellMgr->GetSpellInfo(id);
            if (!info || !info->IsStackableWithRanks() || !info->IsRanked() || !IsEraStanceSpell(info))
                continue;
            const_cast<SpellInfo*>(info)->SetStackableWithRanks(false);
            ++changed;
        }
        LOG_INFO("module.nekocore", ">> Era spells: {} ranked aura/form spell(s) now replace their lower ranks", changed);
    }
};

class EraSpellFixups_Player : public PlayerScript
{
public:
    EraSpellFixups_Player() : PlayerScript("EraSpellFixups_Player", {
        PLAYERHOOK_ON_LEARN_SPELL,
        PLAYERHOOK_ON_LOGIN,
    }) { }

    void OnPlayerLearnSpell(Player* player, uint32 spellId) override
    {
        if (player)
            LearnEraSpellSkill(player, spellId);
    }

    // Characters who bought a proficiency before this existed hold the
    // spell without the skill; catch them up once they log in.
    void OnPlayerLogin(Player* player) override
    {
        if (!player)
            return;
        std::vector<uint32> held;
        for (auto const& [spellId, state] : player->GetSpellMap())
            if (state && state->State != PLAYERSPELL_REMOVED && EraOfSpell(spellId) != ERA_WOTLK)
                held.push_back(spellId);
        for (uint32 spellId : held)
            LearnEraSpellSkill(player, spellId);
    }
};

// Seal of the Crusader (Vanilla/TBC): "The Paladin also attacks $s2% faster,
// but deals less damage with each attack." The haste is the seal's own
// SPELL_AURA_MOD_ATTACKSPEED; the smaller hits were hardcoded by the era
// core, which cut main-hand damage by the same factor so damage per second
// stays put (vmangos: -100 * haste / (100 + haste) percent). Without it the
// seal was a free 40% damage increase.
class EraSpellFixups_Unit : public UnitScript
{
public:
    EraSpellFixups_Unit() : UnitScript("EraSpellFixups_Unit", true, { UNITHOOK_MODIFY_MELEE_DAMAGE }) { }

    void ModifyMeleeDamage(Unit* /*target*/, Unit* attacker, uint32& damage) override
    {
        if (!attacker || !attacker->IsPlayer())
            return;

        for (AuraEffect const* eff : attacker->GetAuraEffectsByType(SPELL_AURA_MOD_ATTACKSPEED))
        {
            SpellInfo const* info = eff->GetSpellInfo();
            if (EraOfSpell(info->Id) == ERA_WOTLK || info->SpellFamilyName != SPELLFAMILY_PALADIN
                || info->GetSpellSpecific() != SPELL_SPECIFIC_SEAL || eff->GetAmount() <= 0)
                continue;
            damage = uint32(damage * 100.0f / (100.0f + eff->GetAmount()));
            return;
        }
    }
};

void AddSC_era_spell_fixups()
{
    new EraSpellFixups_World();
    new EraSpellFixups_Player();
    new EraSpellFixups_Unit();
}

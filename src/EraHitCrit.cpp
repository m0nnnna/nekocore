/*
 * Vanilla-era hit / crit (issue #88).
 *
 * 1.12 items said "+1% chance to hit/crit"; WotLK data turned those into
 * equip spells granting combat RATING (7597 "Increased Critical 14",
 * 15464 "Increased Hit Rating 10", ...), sized at level 60's ratio, and
 * merged every one of them onto melee+ranged+spell (misc mask 0x700/0xe0)
 * -- the spell-only ones (18384 "Increased Critical Spell", 23727
 * "Increased Spell Hit Chance") included.
 *
 * core-patches/0007 fixes that for Vanilla-era players by:
 *   - converting CR_HIT_* / CR_CRIT_* at the level-60 ratio below 60
 *     (10 hit / 8 spell hit / 14 crit per 1%), so "+1%" is 1% at any level;
 *   - asking g_nekoVanillaExcludedRatings, installed here, which ratings of
 *     each source its 1.12 form did NOT affect, and dropping those while
 *     the player is Vanilla.
 * The core keeps that per-player tally on every apply/remove regardless of
 * era, so all that changes on an era crossing is whether it is subtracted:
 * a refresh (UpdateAllRatings) on login and progression-quest reward is all
 * the bookkeeping needed. TBC/WotLK behaviour is untouched.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "QuestDef.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "DBCStores.h"
#include "ItemTemplate.h"
#include "IndividualProgression.h"

#include <cstring>
#include <unordered_set>

namespace
{
    constexpr uint32 PROGRESSION_QUEST_BASE = 66000;

    constexpr uint32 HIT_PHYS   = (1u << CR_HIT_MELEE) | (1u << CR_HIT_RANGED);
    constexpr uint32 HIT_SPELL  = (1u << CR_HIT_SPELL);
    constexpr uint32 CRIT_PHYS  = (1u << CR_CRIT_MELEE) | (1u << CR_CRIT_RANGED);
    constexpr uint32 CRIT_SPELL = (1u << CR_CRIT_SPELL);

    // Hit/crit for everything in 1.12 too (Songflower Serenade, Rallying Cry
    // of the Dragonslayer, Sanctified Orb).
    std::unordered_set<uint32> const BothSpells = { 15366, 22888, 24865 };

    // Spell-only in 1.12 but not caught by the name/aura heuristic below.
    std::unordered_set<uint32> const SpellOnlySpells = {
        21092, // Increased Critical Holy
        24498, // Brilliant Light (Gri'lek's Charm of Valor)
        24543, // Massive Destruction (Hazza'rah's Charm of Destruction)
        24610, // Pagle's Broken Reel
    };

    // Which of the hit/crit ratings in ratingMask the source should NOT
    // give a Vanilla player. Only a mask that mixes physical and spell is
    // ever touched; single-sided masks are already correct.
    uint32 Exclusion(uint32 ratingMask, bool spellOnly)
    {
        uint32 excluded = 0;
        if ((ratingMask & HIT_PHYS) && (ratingMask & HIT_SPELL))
            excluded |= spellOnly ? (ratingMask & HIT_PHYS) : HIT_SPELL;
        if ((ratingMask & CRIT_PHYS) && (ratingMask & CRIT_SPELL))
            excluded |= spellOnly ? (ratingMask & CRIT_PHYS) : CRIT_SPELL;
        return excluded;
    }

    // A caster bonus: +spell damage to a magic school, or +healing.
    bool SpellIsCasterBonus(SpellInfo const* spell)
    {
        if (!spell)
            return false;
        for (SpellEffectInfo const& eff : spell->Effects)
        {
            if (eff.ApplyAuraName == SPELL_AURA_MOD_HEALING_DONE)
                return true;
            if (eff.ApplyAuraName == SPELL_AURA_MOD_DAMAGE_DONE && (uint32(eff.MiscValue) & SPELL_SCHOOL_MASK_MAGIC))
                return true;
        }
        return false;
    }

    bool IsCasterStat(int32 stat)
    {
        return stat == ITEM_MOD_SPELL_POWER || stat == ITEM_MOD_SPELL_HEALING_DONE || stat == ITEM_MOD_SPELL_DAMAGE_DONE;
    }

    bool ItemIsCaster(ItemTemplate const* item)
    {
        for (uint32 i = 0; i < item->StatsCount && i < MAX_ITEM_PROTO_STATS; ++i)
            if (IsCasterStat(int32(item->ItemStat[i].ItemStatType)))
                return true;

        if (item->ScalingStatDistribution)
            if (ScalingStatDistributionEntry const* ssd = sScalingStatDistributionStore.LookupEntry(item->ScalingStatDistribution))
                for (int32 stat : ssd->StatMod)
                    if (IsCasterStat(stat))
                        return true;

        for (uint8 i = 0; i < MAX_ITEM_PROTO_SPELLS; ++i)
            if (item->Spells[i].SpellId > 0 && item->Spells[i].SpellTrigger == ITEM_SPELLTRIGGER_ON_EQUIP)
                if (SpellIsCasterBonus(sSpellMgr->GetSpellInfo(uint32(item->Spells[i].SpellId))))
                    return true;
        return false;
    }

    bool EnchantIsCaster(SpellItemEnchantmentEntry const* enchant)
    {
        for (uint8 i = 0; i < MAX_SPELL_ITEM_ENCHANTMENT_EFFECTS; ++i)
        {
            if (enchant->type[i] == ITEM_ENCHANTMENT_TYPE_STAT && IsCasterStat(int32(enchant->spellid[i])))
                return true;
            if (enchant->type[i] == ITEM_ENCHANTMENT_TYPE_EQUIP_SPELL && SpellIsCasterBonus(sSpellMgr->GetSpellInfo(enchant->spellid[i])))
                return true;
        }
        return false;
    }

    bool SpellIsSpellOnly(SpellInfo const* spell)
    {
        if (SpellOnlySpells.count(spell->Id))
            return true;
        char const* name = spell->SpellName[0];
        if (name && std::strstr(name, "Spell"))
            return true;
        return SpellIsCasterBonus(spell);
    }

    uint32 VanillaExcludedRatings(SpellInfo const* spell, ItemTemplate const* item,
                                  SpellItemEnchantmentEntry const* enchant, uint32 ratingMask)
    {
        // Only the 3.0-merged hit/crit masks (0xe0, 0x700, 0x7e0). A source
        // that also adds other ratings (e.g. a -1 "all ratings" buff) is not
        // a converted 1.12 hit/crit bonus; leave it whole.
        if (!(ratingMask & (HIT_PHYS | HIT_SPELL | CRIT_PHYS | CRIT_SPELL)) ||
            (ratingMask & ~(HIT_PHYS | HIT_SPELL | CRIT_PHYS | CRIT_SPELL)))
            return 0;

        if (spell)
        {
            if (BothSpells.count(spell->Id))
                return 0;
            return Exclusion(ratingMask, SpellIsSpellOnly(spell));
        }
        if (item)
            return Exclusion(ratingMask, ItemIsCaster(item));
        if (enchant)
            return Exclusion(ratingMask, EnchantIsCaster(enchant));
        return 0;
    }

    class EraHitCrit : public PlayerScript
    {
    public:
        EraHitCrit() : PlayerScript("EraHitCrit", { PLAYERHOOK_ON_LOGIN, PLAYERHOOK_ON_PLAYER_COMPLETE_QUEST }) { }

        // Gear/auras are applied before the era is known to matter; re-run
        // the conversion once the character is fully in the world.
        void OnPlayerLogin(Player* player) override
        {
            player->UpdateAllRatings();
        }

        // Any progression-state quest (forward, or ForceUpdateProgressionState
        // re-rewarding from the bottom) may have moved the player across
        // the Vanilla boundary.
        void OnPlayerCompleteQuest(Player* player, Quest const* quest) override
        {
            uint32 questId = quest->GetQuestId();
            if (questId >= PROGRESSION_QUEST_BASE + PROGRESSION_MOLTEN_CORE &&
                questId <= PROGRESSION_QUEST_BASE + PROGRESSION_WOTLK_TIER_5)
                player->UpdateAllRatings();
        }
    };
}

void AddSC_era_hit_crit()
{
    g_nekoVanillaExcludedRatings = &VanillaExcludedRatings;
    new EraHitCrit();
}

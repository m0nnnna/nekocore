/*
 * Brings a character's existing spellbook in line with the era they are
 * actually in -- at login, and again whenever they cross an era boundary.
 *
 * EraSpellGate.cpp swaps a spell for its era copy inside
 * Player::learnSpell, which covers trainers, quest rewards and level-up
 * grants. It does NOT cover everything, and the gap is not obscure:
 *
 *   - Player::LearnCustomSpells (character creation) calls addSpell
 *     directly while the player is not yet in world. A brand new Mage
 *     therefore started with WOTLK Fireball, and could then never learn
 *     the Vanilla one, because the WotLK spell was already known and the
 *     trainer had nothing new to sell. Found in live testing, and the
 *     reason this file exists.
 *   - Player::LearnSkillRewardedSpells does the same on the !IsInWorld
 *     path, which is where the SkillLineAbility rows with AcquireMethod
 *     1 or 2 are granted.
 *   - Characters that existed before era spells did, who hold WotLK ids
 *     throughout.
 *
 * Rather than chase each of those call sites, reconcile the whole
 * spellbook once at login. It is a walk over a few hundred entries and it
 * is self-correcting: whatever put a wrong-era spell there, it gets fixed
 * the next time the character logs in.
 *
 * The same function does era transitions, because they are the same
 * operation with a different target era -- and unlike talents, spells CAN
 * be remapped one for one, since an era copy is its WotLK spell's id plus
 * a fixed offset.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Chat.h"
#include "SpellInfo.h"

#include "EraSpells.h"

#include <algorithm>
#include <cstring>
#include <iterator>
#include <unordered_map>
#include <utility>
#include <vector>

namespace
{
    // Action bars hold spell ids directly, so a spell that moves has to be
    // moved in the bars too or the slot quietly stops working. Done BEFORE
    // the spells change, while the old ids are still what the buttons
    // hold.
    void RemapActionButtons(Player* player, std::unordered_map<uint32, uint32> const& moves)
    {
        for (uint8 slot = 0; slot < MAX_ACTION_BUTTONS; ++slot)
        {
            ActionButton const* button = player->GetActionButton(slot);
            if (!button || button->GetType() != ACTION_BUTTON_SPELL)
                continue;

            auto itr = moves.find(button->GetAction());
            if (itr == moves.end() || itr->second == button->GetAction())
                continue;

            // remove + add rather than editing in place: both send the
            // client the change, so the bar updates without a relog.
            player->removeActionButton(slot);
            if (itr->second)
                player->addActionButton(slot, itr->second, ACTION_BUTTON_SPELL);
        }
    }

    // Racials the era had but WotLK replaced under a new id: Perception
    // (Human 20600; WotLK has 58985), Shadowmeld (Night Elf 20580; 58984),
    // the Troll's mana and rage Berserking (20554, 26296; WotLK keeps only
    // 26297). Moving held spells never reaches them, since a WotLK
    // character holds no spell they are a copy of, and their era rows are
    // not auto-learned (AcquireMethod 0, like every era copy). So: every
    // era racial for this race and class whose base id the core never
    // grants by itself, unless one of that name is already held (a Troll
    // already has Berserking through 26297's copy).
    bool HoldsSpellNamed(Player const* player, uint32 spellId)
    {
        SpellInfo const* wanted = sSpellMgr->GetSpellInfo(spellId);
        if (!wanted || !wanted->SpellName[0])
            return false;
        for (auto const& [heldId, state] : player->GetSpellMap())
        {
            if (!state || state->State == PLAYERSPELL_REMOVED)
                continue;
            SpellInfo const* held = sSpellMgr->GetSpellInfo(heldId);
            if (held && held->SpellName[0] && std::strcmp(held->SpellName[0], wanted->SpellName[0]) == 0)
                return true;
        }
        return false;
    }

    std::vector<uint32> EraOnlyRacials(Player const* player, NekoEraSpells::Era era)
    {
        using namespace NekoEraSpells;
        std::vector<uint32> out;
        uint32 const offset = OffsetOfEra(era);
        if (!offset)
            return out;

        for (SkillLineAbilityEntry const* ability : sSkillLineAbilityStore)
        {
            if (EraOfSpell(ability->Spell) != era || !(ability->RaceMask & player->getRaceMask())
                || (ability->ClassMask && !(ability->ClassMask & player->getClassMask())))
                continue;
            if (std::find(std::begin(RACIAL_SKILL_LINES), std::end(RACIAL_SKILL_LINES), ability->SkillLine)
                == std::end(RACIAL_SKILL_LINES))
                continue;

            bool grantedByCore = false;
            SkillLineAbilityMapBounds const bounds = sSpellMgr->GetSkillLineAbilityMapBounds(ability->Spell - offset);
            for (auto it = bounds.first; it != bounds.second && !grantedByCore; ++it)
                grantedByCore = it->second->AcquireMethod == SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN;
            if (grantedByCore || HoldsSpellNamed(player, ability->Spell))
                continue;
            out.push_back(ability->Spell);
        }
        return out;
    }
}

namespace NekoEraSpells
{
    uint32 ReconcileSpellsToEra(Player* player, Era targetEra)
    {
        if (!player)
            return 0;

        // old spell id -> what it should become (0 = drop it entirely)
        std::unordered_map<uint32, uint32> moves;
        for (auto const& [spellId, state] : player->GetSpellMap())
        {
            if (!state || state->State == PLAYERSPELL_REMOVED)
                continue;

            Era const spellEra = EraOfSpell(spellId);
            if (spellEra == targetEra)
                continue; // already right

            if (spellEra == ERA_WOTLK)
            {
                // A shared-id spell while the character is in an era that
                // has its own copy. Talent rank spells are exempt: era
                // talent trees still point at these very ids and the core
                // tracks a learned talent through sTalentSpellPosMap.
                if (IsTalentRankSpell(spellId))
                    continue;
                // Gathering perks the era never had. They have no copy to
                // move to, so drop them; the core re-adds them at login on
                // the !IsInWorld skill-load path, which is why this has to
                // run every login rather than once.
                // Racials WotLK added (Every Man for Himself, ...) go the
                // same way, and are re-added by the same login paths.
                // Profession recipes/ranks the era's client lacked go too
                // (EraRecipeGates.generated.h); skill-gain perks are
                // re-added by the core each login and stripped again here.
                if (IsWotlkOnlyProfessionPerk(spellId) || IsRecipeAfterEra(targetEra, spellId)
                    || IsRacialAddedAfterEra(player, targetEra, spellId))
                {
                    moves[spellId] = 0;
                    continue;
                }
                if (uint32 eraCopy = EraSpellFor(targetEra, spellId))
                    moves[spellId] = eraCopy;
                continue;
            }

            // An era copy belonging to some OTHER era: move it to this
            // era's equivalent, or drop it if this era has none. Dropping
            // is right -- if the ability exists here at all it exists
            // under this era's own id, which is what the map grants.
            moves[spellId] = EraSpellFor(targetEra, BaseSpellOf(spellId));
        }

        RemapActionButtons(player, moves);

        uint32 changed = 0;
        for (auto const& [oldSpell, newSpell] : moves)
        {
            player->removeSpell(oldSpell, SPEC_MASK_ALL, false);
            if (newSpell)
            {
                player->learnSpell(newSpell);
                ++changed;
            }
        }

        for (uint32 racial : EraOnlyRacials(player, targetEra))
        {
            if (player->HasSpell(racial))
                continue;
            player->learnSpell(racial);
            ++changed;
        }
        return changed;
    }
}

class EraSpellSync : public PlayerScript
{
public:
    EraSpellSync() : PlayerScript("EraSpellSync", { PLAYERHOOK_ON_LOGIN }) { }

    void OnPlayerLogin(Player* player) override
    {
        if (!player)
            return;

        using namespace NekoEraSpells;
        Era const era = NekoEraTalents::EraOfPlayer(player);
        uint32 const changed = ReconcileSpellsToEra(player, era);
        if (!changed)
            return;

        // Only worth saying anything when it actually did something, which
        // after the first login is almost never.
        ChatHandler(player->GetSession()).PSendSysMessage(
            "|cff00ff00[Era Spells]|r %u of your abilities were updated to their era versions.", changed);
    }
};

void AddSC_era_spell_sync()
{
    new EraSpellSync();
}

/*
 * Makes a character actually PLAY with their era's spells, rather than
 * merely having era spell rows exist in Spell.dbc.
 *
 * tools/build_patch/build_era_spells.py gives every class spell a Vanilla
 * copy (+300000) and a TBC copy (+400000), and build_era_spell_sql.py
 * clones the world DB rows (rank chains, coefficients, proc data, script
 * names) onto those ids. None of that does anything on its own: without
 * this file a character still learns and casts WotLK's versions, and the
 * era copies are inert data only a GM's .learn can reach.
 *
 * Two jobs here; a third (reconciling a character's existing spellbook)
 * lives in EraSpellSync.cpp.
 *
 * 1. SUBSTITUTION AND THE GATE, in Player::learnSpell. The hook fires
 *    before the spell is added and refusing it stops the add, so learning
 *    the era copy from inside the hook and then refusing the original
 *    swaps one for the other. Doing it here rather than at each grant site
 *    is deliberate: trainers, quest rewards and level-up grants all funnel
 *    through learnSpell, so one rule covers them instead of several that
 *    can drift apart. An era copy belonging to a different era is refused
 *    outright, which is the part that actually holds against a macro or a
 *    hand-built packet.
 *
 *    NOT every grant path funnels through learnSpell -- character creation
 *    and the skill-reward pass call addSpell directly while the player is
 *    not yet in world. EraSpellSync.cpp catches those at login.
 *
 * 2. TRAINERS -- now only a filter. build_era_spell_sql.py clones
 *    trainer_spell onto era ids, so a class trainer genuinely stocks all
 *    three eras' versions and the core's own machinery works unchanged:
 *    GetSpell() resolves the id the client sends back, the tooltip is
 *    rendered from the era row the list actually names, and the previous-
 *    rank checks compare era ids against era ids. All this hook does is
 *    drop the entries that do not belong to the viewer's era.
 *
 *    Two earlier attempts are worth not repeating. Rewriting the displayed
 *    id to the era copy broke buying outright -- the client sends the
 *    displayed id back in CMSG_TRAINER_BUY_SPELL and Trainer::TeachSpell
 *    looks it up with GetSpell() among the trainer's own rows, found
 *    nothing, and silently did nothing. Leaving the WotLK id displayed and
 *    patching the state instead fixed buying but left the client rendering
 *    the WOTLK tooltip (Frostbolt at 6% of base mana, 11 at low level)
 *    over a spell that actually cost a flat 25, and left the entry green
 *    after purchase because the client greys a row when it sees the id it
 *    bought get learnt -- which never happened, since it received the era
 *    id instead. Both symptoms were reported from live play.
 *
 * Deliberately NOT touched: talent rank spells (see
 * NekoEraSpells::IsTalentRankSpell -- era talent trees still point at
 * shared WotLK ids and the core tracks talents by that id), and any spell
 * with no era copy, which is every profession, item and quest spell.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "DBCStores.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "Trainer.h"
#include "NPCPackets.h"

#include "EraSpells.h"

#include <algorithm>
#include <unordered_set>
#include <vector>

namespace
{
    using namespace NekoEraSpells;

    /// Guard against re-entering the substitution while the substituted
    /// learn is itself running, so the inner learnSpell is taken at face
    /// value.
    thread_local bool inSubstitution = false;

    /// Era copies a character must not be shown: everything that is not
    /// their own era. A WotLK-era character is shown no era copies at all,
    /// and an era character is shown neither the other era's copies nor
    /// the WotLK originals of spells their era has its own version of.
    bool HiddenFromEra(Player const* /*player*/, Era playerEra, uint32 spellId)
    {
        Era const spellEra = EraOfSpell(spellId);
        if (spellEra != ERA_WOTLK)
            return spellEra != playerEra;

        // A WotLK id. Hide it only when this era stocks its own copy --
        // profession, riding and class spells that never changed have no
        // copy and must stay visible.
        return playerEra != ERA_WOTLK && !IsTalentRankSpell(spellId)
            && EraSpellFor(playerEra, spellId) != 0;
    }

    /// What a trainer "teaching" spell grants through its LEARN_SPELL
    /// effects (10321 "Judgement" -> 20271, 21084; 34768 Summon Warhorse ->
    /// 34769, 33388). Empty for an ordinary spell.
    std::vector<uint32> TaughtSpells(uint32 spellId)
    {
        std::vector<uint32> taught;
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId))
            for (SpellEffectInfo const& effect : info->GetEffects())
                if (effect.IsEffect(SPELL_EFFECT_LEARN_SPELL) && effect.TriggerSpell)
                    taught.push_back(effect.TriggerSpell);
        return taught;
    }

    /// A taught spell counts as held when the character has it or, for a
    /// spell their era has its own version of, that version -- learning the
    /// WotLK id is swapped for the era copy, so the WotLK id never arrives.
    bool HoldsTaughtSpell(Player const* player, Era playerEra, uint32 taught)
    {
        if (player->HasSpell(taught))
            return true;
        uint32 const eraCopy = EraSpellFor(playerEra, taught);
        return eraCopy && player->HasSpell(eraCopy);
    }
}

class EraSpellGate : public PlayerScript
{
public:
    EraSpellGate() : PlayerScript("EraSpellGate", {
        PLAYERHOOK_CAN_LEARN_SPELL,
        PLAYERHOOK_ON_BEFORE_RECEIVE_SPELL_LIST_FROM_TRAINER,
        PLAYERHOOK_ON_GET_TRAINER_SPELL_STATE,
    }) { }

    /// Teaching spells. Trainer::GetDefaultSpellState calls one known only
    /// when the player holds every WotLK id it teaches, which an era
    /// character never will (see HoldsTaughtSpell). So 10321 "Judgement"
    /// stayed Available after purchase, and because TeachSpell takes the
    /// money and plays the visual before the learn is swapped away, every
    /// click charged for nothing. Counting the era copies fixes the colour
    /// and, since CanTeachSpell asks this same state, blocks the purchase.
    void OnPlayerGetTrainerSpellState(Player const* player, uint32 /*trainerId*/, uint32 spellId,
                                      Trainer::SpellState& state) override
    {
        if (!player || state != Trainer::SpellState::Available || EraOfSpell(spellId) != ERA_WOTLK)
            return;

        Era const playerEra = NekoEraTalents::EraOfPlayer(player);
        if (playerEra == ERA_WOTLK)
            return;

        std::vector<uint32> const taught = TaughtSpells(spellId);
        if (taught.empty())
            return;
        for (uint32 spell : taught)
            if (!HoldsTaughtSpell(player, playerEra, spell))
                return;
        state = Trainer::SpellState::Known;
    }

    bool OnPlayerCanLearnSpell(Player* player, uint32 spellId) override
    {
        if (!player)
            return true;

        Era const playerEra = NekoEraTalents::EraOfPlayer(player);
        Era const spellEra = EraOfSpell(spellId);

        if (spellEra != ERA_WOTLK)
        {
            // An era copy: only the era that owns it may have it. No chat
            // message on the mismatch -- this fires on ordinary internal
            // grants as well as on a hand-crafted packet, and a refusal
            // that is usually correct housekeeping should not spam.
            return spellEra == playerEra;
        }

        if (playerEra != ERA_WOTLK
            && (IsWotlkOnlyProfessionPerk(spellId) || IsRacialAddedAfterEra(player, playerEra, spellId)))
            return false;

        if (inSubstitution || playerEra == ERA_WOTLK || IsTalentRankSpell(spellId))
            return true;

        uint32 const eraSpell = EraSpellFor(playerEra, spellId);
        if (!eraSpell)
            return true; // shared spell with no era version: learn it as-is

        if (player->HasSpell(eraSpell))
            return false; // already holds this era's version; nothing to do

        inSubstitution = true;
        player->learnSpell(eraSpell);
        inSubstitution = false;
        return false;
    }

    void OnPlayerBeforeReceiveSpellListFromTrainer(Player* player, Creature* /*trainer*/,
                                                   WorldPackets::NPC::TrainerList& trainerList) override
    {
        if (!player)
            return;

        Era const playerEra = NekoEraTalents::EraOfPlayer(player);
        std::unordered_set<uint32> listed;
        for (WorldPackets::NPC::TrainerListSpell const& entry : trainerList.Spells)
            listed.insert(static_cast<uint32>(entry.SpellID));

        std::vector<WorldPackets::NPC::TrainerListSpell> kept;
        kept.reserve(trainerList.Spells.size());
        for (WorldPackets::NPC::TrainerListSpell const& entry : trainerList.Spells)
        {
            uint32 const spellId = static_cast<uint32>(entry.SpellID);
            if (HiddenFromEra(player, playerEra, spellId) || DuplicatedByEraCopies(player, playerEra, spellId, listed))
                continue;
            kept.push_back(entry);
            ShowRequiredSpells(kept.back());
        }

        trainerList.Spells.swap(kept);
    }

private:
    /// A teaching spell whose era-copied lessons this same list already
    /// sells, or the character already holds, adds nothing but a second
    /// row: 10321 "Judgement" next to 320271 Judgement. One with a lesson
    /// only it can deliver stays -- 34768 Summon Warhorse is the only way a
    /// TBC paladin gets 434769, which no trainer lists on its own.
    static bool DuplicatedByEraCopies(Player const* player, Era playerEra, uint32 spellId,
                                      std::unordered_set<uint32> const& listed)
    {
        if (playerEra == ERA_WOTLK || EraOfSpell(spellId) != ERA_WOTLK)
            return false;

        bool anyCopied = false;
        for (uint32 taught : TaughtSpells(spellId))
        {
            uint32 const eraCopy = EraSpellFor(playerEra, taught);
            if (!eraCopy)
            {
                if (!player->HasSpell(taught))
                    return false; // something only this row teaches
                continue;
            }
            anyCopied = true;
            if (!listed.count(eraCopy) && !player->HasSpell(eraCopy))
                return false;
        }
        return anyCopied;
    }

    /// Puts the spells the server requires but the list does not name into
    /// the entry's ReqAbility slots, which is the only way the client learns
    /// of them: the previous rank in the chain (Frenzied Regeneration r2
    /// needs r1) and `spell_required` prerequisites (Bear Form for
    /// Demoralizing Roar, Bash, Swipe, ...). Trainer::GetDefaultSpellState
    /// already marks such an entry Unavailable, but the client re-colours
    /// the list itself after every purchase from level and ReqAbility alone,
    /// so a druid without Bear Form, or without the talent that is Faerie
    /// Fire (Feral) rank 1 in Vanilla, saw those rows turn green after
    /// buying anything, then could not train them. Only fills empty slots.
    static void ShowRequiredSpells(WorldPackets::NPC::TrainerListSpell& entry)
    {
        auto add = [&entry](uint32 required)
        {
            int32 const req = static_cast<int32>(required);
            if (!req || std::find(entry.ReqAbility.begin(), entry.ReqAbility.end(), req) != entry.ReqAbility.end())
                return;
            auto const slot = std::find(entry.ReqAbility.begin(), entry.ReqAbility.end(), 0);
            if (slot != entry.ReqAbility.end())
                *slot = req;
        };

        add(sSpellMgr->GetPrevSpellInChain(entry.SpellID));
        for (auto const& [spellId, required] : sSpellMgr->GetSpellsRequiredForSpellBounds(entry.SpellID))
            add(required);
    }
};

void AddSC_era_spell_gate()
{
    new EraSpellGate();
}

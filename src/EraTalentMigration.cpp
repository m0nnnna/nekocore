/*
 * Brings every stored talent in line with the era its character is in,
 * once, at world startup -- BEFORE anyone can log in.
 *
 * Why this has to exist: era talent trees used to point at the SHARED spell
 * ids (Vanilla Ice Block's talent at 11958, which on this realm is WotLK
 * Cold Snap). build_era_tree.py now points them at each era's own spell
 * copies (+300000 Vanilla, +400000 TBC), so a talent a character learned
 * before that is stored under an id that no longer means their talent:
 *
 *   - most resolve to a WotLK-tree talent instead, so the character would
 *     silently hold points in a tree their era cannot use;
 *   - a Vanilla/TBC-only talent (one WotLK deleted) resolves to nothing at
 *     all, and Player::_LoadTalents ASSERTs on exactly that -- the
 *     worldserver would crash the moment such a character logged in.
 *
 * Hence startup rather than login: the crash happens inside the load.
 *
 * The rule enforced is the invariant the era talent system already relies
 * on (EraTalentGate.cpp blocks learning outside it, EraProgressionSync.cpp
 * resets on every era change): a stored talent must resolve to a tab of
 * the character's CURRENT era. A row that does not is deleted, together
 * with the spells that talent put in the spellbook. Talent points need no
 * handling -- the core computes free points from level minus talents held
 * at load, so they come back on their own. The character is told on their
 * next login.
 *
 * Idempotent: once every row satisfies the rule there is nothing to do, so
 * this is a single cheap scan on every later startup, and it also repairs
 * any row that ever breaks the rule again for some other reason.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Chat.h"
#include "DatabaseEnv.h"
#include "DBCStores.h"
#include "Log.h"
#include "SpellInfo.h"
#include "SpellMgr.h"

#include "IndividualProgression.h"

#include "EraTalents.h"

#include <mutex>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace
{
    using namespace NekoEraTalents;

    constexpr uint32 PROGRESSION_QUEST_BASE = 66000;

    // Characters whose talents this pass reset, so their next login can
    // say why. Only ever written at startup, before the first login.
    std::unordered_set<uint32> resetThisStartup;
    std::mutex resetMutex;

    /// Same boundaries as NekoEraTalents::EraOfPlayer, from the rewarded
    /// progression quests alone -- the character is not loaded here.
    Era EraOfRewardedStates(std::set<uint32> const& states)
    {
        for (uint32 s = PROGRESSION_TBC_TIER_5; s <= PROGRESSION_WOTLK_TIER_5; ++s)
            if (states.count(s))
                return ERA_WOTLK;
        for (uint32 s = PROGRESSION_PRE_TBC; s < PROGRESSION_TBC_TIER_5; ++s)
            if (states.count(s))
                return ERA_TBC;
        return ERA_VANILLA;
    }

    /// The talent's own rank spell plus whatever it teaches (a talent such
    /// as Ice Block puts a castable spell in the spellbook through a
    /// LEARN_SPELL effect). Both have to go with the talent, or the
    /// character keeps a spell no talent backs.
    std::vector<uint32> SpellsOfTalentRank(uint32 spellId)
    {
        std::vector<uint32> out{ spellId };
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId))
            for (SpellEffectInfo const& effect : info->GetEffects())
                if (effect.Effect == SPELL_EFFECT_LEARN_SPELL && effect.TriggerSpell)
                    out.push_back(effect.TriggerSpell);
        return out;
    }
}

class EraTalentMigration : public WorldScript
{
public:
    EraTalentMigration() : WorldScript("EraTalentMigration", { WORLDHOOK_ON_STARTUP }) { }

    void OnStartup() override
    {
        std::unordered_map<uint32, std::set<uint32>> statesByGuid;
        if (QueryResult result = CharacterDatabase.Query(
                "SELECT guid, quest FROM character_queststatus_rewarded WHERE quest BETWEEN {} AND {}",
                PROGRESSION_QUEST_BASE, PROGRESSION_QUEST_BASE + PROGRESSION_WOTLK_TIER_5))
        {
            do
            {
                Field* fields = result->Fetch();
                statesByGuid[fields[0].Get<uint32>()].insert(fields[1].Get<uint32>() - PROGRESSION_QUEST_BASE);
            } while (result->NextRow());
        }

        QueryResult talents = CharacterDatabase.Query("SELECT guid, spell FROM character_talent");
        if (!talents)
            return;

        std::unordered_map<uint32, std::vector<uint32>> badByGuid;
        do
        {
            Field* fields = talents->Fetch();
            uint32 const guid = fields[0].Get<uint32>();
            uint32 const spell = fields[1].Get<uint32>();

            Era const charEra = EraOfRewardedStates(statesByGuid[guid]);
            TalentSpellPos const* pos = GetTalentSpellPos(spell);
            TalentEntry const* talent = pos ? sTalentStore.LookupEntry(pos->talent_id) : nullptr;
            if (!talent || EraOfTab(talent->TalentTab) != charEra)
                badByGuid[guid].push_back(spell);
        } while (talents->NextRow());

        if (badByGuid.empty())
            return;

        uint32 rows = 0;
        CharacterDatabaseTransaction trans = CharacterDatabase.BeginTransaction();
        for (auto const& [guid, spells] : badByGuid)
        {
            for (uint32 spell : spells)
            {
                trans->Append("DELETE FROM character_talent WHERE guid = {} AND spell = {}", guid, spell);
                for (uint32 taught : SpellsOfTalentRank(spell))
                    trans->Append("DELETE FROM character_spell WHERE guid = {} AND spell = {}", guid, taught);
                ++rows;
            }
        }
        CharacterDatabase.CommitTransaction(trans);

        {
            std::lock_guard<std::mutex> lock(resetMutex);
            for (auto const& [guid, spells] : badByGuid)
                resetThisStartup.insert(guid);
        }

        LOG_INFO("module", "[EraTalentMigration] removed {} talent row(s) from {} character(s) that did not "
            "belong to the character's current era; their points are refunded on load.", rows, badByGuid.size());
    }
};

class EraTalentMigrationNotice : public PlayerScript
{
public:
    EraTalentMigrationNotice() : PlayerScript("EraTalentMigrationNotice", { PLAYERHOOK_ON_LOGIN }) { }

    void OnPlayerLogin(Player* player) override
    {
        if (!player)
            return;

        {
            std::lock_guard<std::mutex> lock(resetMutex);
            if (!resetThisStartup.erase(player->GetGUID().GetCounter()))
                return;
        }

        ChatHandler(player->GetSession()).PSendSysMessage(
            "|cff00ff00[Era Talents]|r Your era's talents now use that era's own spells, so your talents "
            "have been reset for free. Your points are waiting to be spent again.");
    }
};

void AddSC_era_talent_migration()
{
    new EraTalentMigration();
    new EraTalentMigrationNotice();
}

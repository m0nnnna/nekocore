/*
 * Challenge runs -- a reason to go back into a dungeon you have outgrown.
 *
 * The problem this solves: on a mod-individual-progression realm a character
 * sits at their era's cap (60 Vanilla, 70 TBC, 80 WotLK) for a long time, and
 * every dungeon below that cap is dead content. mod-autobalance CAN scale a
 * dungeon up to the party's level, but it is one global switch for the whole
 * realm (AutoBalance.LevelScaling) -- turning it on would mean a level-22
 * character levelling through Wailing Caverns finds it scaled too, which is
 * not what anyone wanted. What was wanted is an opt-in: walk up to an NPC, say
 * "challenge run", and go do Wailing Caverns at 60 -- and have it get harder
 * every time you clear it.
 *
 * How a run happens, start to finish:
 *
 *   1. The Challenge Keeper (entry 9000101, data/sql/db-world/base/
 *      challenge_keeper.sql, next to Dungeon Dan in both capitals) lists the
 *      dungeons this character may challenge, each with the tier it is
 *      currently at for them and what that tier works out to. Picking one ARMS
 *      the challenge -- it deliberately does not teleport: Dungeon Dan is three
 *      yards away and already does that for every dungeon in the game, and a
 *      second copy of his coordinate table here would be a second thing to
 *      keep right.
 *
 *   2. Entering the instance FLAGS it (OnPlayerEnterAll). The flag carries the
 *      bracket and the tier, and from that moment ChallengeScaling.cpp pins
 *      every creature on the map to the bracket level and multiplies its
 *      health and its outgoing damage.
 *
 *   3. Killing the dungeon's final boss CLEARS it: +1 tier for everyone
 *      recorded in the run. Everyone in the instance being dead at once WIPES
 *      it: -1 tier (floor 0) and the flag is spent -- the run has to be armed
 *      again. Leaving without either is abandoned, and costs nothing.
 *
 * Who may start one, and the level rule. The bracket is the character's era
 * cap, read from mod-individual-progression exactly the way EraTalentGate.cpp
 * and NekoLog.cpp read it (GetPlayerProgressionFromQuests -- whose value is
 * what that module's own isBeforeProgression/hasPassedProgression compare
 * against, confirmed in IndividualProgression.cpp): state <
 * PROGRESSION_PRE_TBC is Vanilla/60, state < PROGRESSION_TBC_TIER_5 is TBC/70,
 * anything above is WotLK/80. A character must be AT that cap to arm or to
 * enter a challenge, which is the "60, if not 60 then 70, if not 70 then 80,
 * or it blocks access" rule. It costs nothing to enforce because
 * mod-individual-progression already stops XP at each era's cap
 * (IndividualProgressionPlayer.cpp's OnPlayerGiveXP), so "at the cap" and "in
 * that era" are the same characters in practice.
 *
 * Which dungeons are listed is NOT a hardcoded map list -- it is built at
 * startup from the client's own LFGDungeon.dbc (normal-difficulty, type
 * dungeon), intersected with:
 *   - MapEntry::IsNonRaidDungeon(), so raids and battlegrounds can't appear;
 *   - `instance_encounters` having at least one row for the map, which is both
 *     how a clear gets detected AND a free filter for the unused and
 *     development maps that sit in Map.dbc and LFGDungeon.dbc with no content
 *     behind them;
 *   - the entry's expansion being at or below the character's era, so a
 *     Vanilla character is never offered a TBC dungeon (mod-individual-
 *     progression would block the entry anyway -- this simply doesn't offer
 *     it).
 * A map with several LFG rows (Blackrock Spire's two) is listed once, under
 * its lowest-level row.
 *
 * Tier storage: nekocore_challenge_tier, one row per (character, map,
 * bracket), held entirely in memory. The whole table is loaded once at startup
 * -- it is small (characters x dungeons they have actually challenged) and it
 * has to be readable synchronously from inside a gossip hook, where an async
 * query has nowhere to land. Writes go out through CharacterDatabase's async
 * queue, so nothing here blocks a map thread.
 *
 * A clear raises `tier`, a wipe lowers it, and `best_tier` only ever goes up
 * -- so the website's ladder shows the hardest run a character has actually
 * beaten and one bad night can't take it away from them.
 *
 * Lock order, since two mutexes are involved: runsMutex then tiersMutex, never
 * the other way. NekoLog::RunIdFor is called with runsMutex held, which is
 * safe because NekoLog knows nothing about challenge runs and so can never
 * call back into here.
 *
 * Config: Nekocore.Challenge.* (conf/nekocore.conf.dist), live-reloadable. The
 * multipliers are DERIVED from the tier whenever they are needed rather than
 * stored per row, so retuning HealthStep/DamageStep retunes every existing
 * tier instead of leaving old characters on old numbers. The numbers a run
 * actually used are recorded on its own run row, so history stays honest.
 */

#include "ScriptMgr.h"
#include "ScriptedGossip.h"
#include "Player.h"
#include "Creature.h"
#include "Group.h"
#include "Map.h"
#include "MapMgr.h"
#include "InstanceScript.h"
#include "ObjectMgr.h"
#include "DBCStores.h"
#include "DatabaseEnv.h"
#include "GameTime.h"
#include "Config.h"
#include "Chat.h"
#include "WorldSession.h"
#include "StringFormat.h"

#include "IndividualProgression.h"

#include "ChallengeRun.h"
#include "NekoLog.h"

#include <algorithm>
#include <atomic>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace
{
    // ---------------------------------------------------------------- config
    bool   cfgEnable          = true;
    float  cfgHealthStep      = 0.15f;
    float  cfgDamageStep      = 0.10f;
    uint16 cfgMaxTier         = 0;       // 0 = no ceiling
    bool   cfgWipePenalty     = true;
    uint32 cfgArmedMinutes    = 30;
    bool   cfgSuppressOutside = true;
    uint8  cfgCeiling         = 1;
    uint8  cfgFloor           = 5;
    bool   cfgAnnounce        = true;

    void LoadConfig()
    {
        cfgEnable          = sConfigMgr->GetOption<bool>("Nekocore.Challenge.Enable", true);
        cfgHealthStep      = sConfigMgr->GetOption<float>("Nekocore.Challenge.HealthStep", 0.15f);
        cfgDamageStep      = sConfigMgr->GetOption<float>("Nekocore.Challenge.DamageStep", 0.10f);
        cfgMaxTier         = uint16(sConfigMgr->GetOption<uint32>("Nekocore.Challenge.MaxTier", 0));
        cfgWipePenalty     = sConfigMgr->GetOption<bool>("Nekocore.Challenge.WipePenalty", true);
        cfgArmedMinutes    = sConfigMgr->GetOption<uint32>("Nekocore.Challenge.ArmedMinutes", 30);
        cfgSuppressOutside = sConfigMgr->GetOption<bool>("Nekocore.Challenge.SuppressLevelScalingOutsideChallenges", true);
        cfgCeiling         = uint8(sConfigMgr->GetOption<uint32>("Nekocore.Challenge.DynamicLevelCeiling", 1));
        cfgFloor           = uint8(sConfigMgr->GetOption<uint32>("Nekocore.Challenge.DynamicLevelFloor", 5));
        cfgAnnounce        = sConfigMgr->GetOption<bool>("Nekocore.Challenge.Announce", true);
    }

    float HealthMultFor(uint16 tier) { return 1.0f + cfgHealthStep * float(tier); }
    float DamageMultFor(uint16 tier) { return 1.0f + cfgDamageStep * float(tier); }
    uint32 Pct(float mult) { return uint32((mult - 1.0f) * 100.0f + 0.5f); }

    // ------------------------------------------------------------ era/bracket
    constexpr uint8 BRACKET_VANILLA = 60;
    constexpr uint8 BRACKET_TBC     = 70;
    constexpr uint8 BRACKET_WOTLK   = 80;

    // LFGMgr.h's LfgType enum, which lives in `namespace lfg` and would drag
    // the whole dungeon finder header in for one integer.
    constexpr uint32 LFG_TYPE_FIVE_MAN_DUNGEON = 1;

    uint8 BracketForEra(uint8 era)
    {
        if (era < uint8(PROGRESSION_PRE_TBC))
            return BRACKET_VANILLA;
        if (era < uint8(PROGRESSION_TBC_TIER_5))
            return BRACKET_TBC;
        return BRACKET_WOTLK;
    }

    /** 0 Vanilla, 1 TBC, 2 WotLK -- the same numbering MapEntry::Expansion() uses. */
    uint8 ExpansionForEra(uint8 era)
    {
        if (era < uint8(PROGRESSION_PRE_TBC))
            return 0;
        if (era < uint8(PROGRESSION_TBC_TIER_5))
            return 1;
        return 2;
    }

    char const* BracketName(uint8 bracket)
    {
        switch (bracket)
        {
            case BRACKET_TBC:   return "TBC";
            case BRACKET_WOTLK: return "WotLK";
            default:            return "Vanilla";
        }
    }

    // ------------------------------------------------------------- catalogue
    struct Dungeon
    {
        uint32      mapId             = 0;
        std::string name;
        uint8       expansion         = 0;
        uint8       minLevel          = 0;
        bool        hasFinalEncounter = false;  // an instance_encounters row with lastEncounterDungeon set
        uint32      encounterCount    = 0;
    };

    std::vector<Dungeon> catalogue;             // sorted by (expansion, minLevel, name); built once at startup

    Dungeon const* FindDungeon(uint32 mapId)
    {
        for (Dungeon const& d : catalogue)
            if (d.mapId == mapId)
                return &d;
        return nullptr;
    }

    void BuildCatalogue()
    {
        catalogue.clear();

        std::unordered_map<uint32, Dungeon> byMap;
        for (uint32 i = 0; i < sLFGDungeonStore.GetNumRows(); ++i)
        {
            LFGDungeonEntry const* lfg = sLFGDungeonStore.LookupEntry(i);
            if (!lfg || lfg->TypeID != LFG_TYPE_FIVE_MAN_DUNGEON ||
                lfg->Difficulty != uint32(DUNGEON_DIFFICULTY_NORMAL))
                continue;

            MapEntry const* mapEntry = sMapStore.LookupEntry(lfg->MapID);
            if (!mapEntry || !mapEntry->IsNonRaidDungeon())
                continue;

            // No encounters recorded for the map means a clear could never be
            // told apart from a stroll -- and it is exactly what the unused
            // and development maps look like.
            DungeonEncounterList const* encounters =
                sObjectMgr->GetDungeonEncounterList(lfg->MapID, DUNGEON_DIFFICULTY_NORMAL);
            if (!encounters || encounters->empty())
                continue;

            auto it = byMap.find(lfg->MapID);
            if (it != byMap.end())
            {
                // Several LFG rows can point at one map (Blackrock Spire).
                // List it once, under the lowest-level of them.
                it->second.minLevel = std::min<uint8>(it->second.minLevel, uint8(lfg->MinLevel));
                continue;
            }

            Dungeon d;
            d.mapId          = lfg->MapID;
            d.name           = (mapEntry->name[0] && *mapEntry->name[0]) ? mapEntry->name[0] : lfg->Name[0];
            d.expansion      = uint8(mapEntry->Expansion());
            d.minLevel       = uint8(lfg->MinLevel);
            d.encounterCount = uint32(encounters->size());
            for (DungeonEncounter const* enc : *encounters)
                if (enc && enc->lastEncounterDungeon)
                    d.hasFinalEncounter = true;
            byMap[d.mapId] = d;
        }

        catalogue.reserve(byMap.size());
        for (auto const& kv : byMap)
            catalogue.push_back(kv.second);

        std::sort(catalogue.begin(), catalogue.end(), [](Dungeon const& a, Dungeon const& b)
        {
            if (a.expansion != b.expansion) return a.expansion < b.expansion;
            if (a.minLevel  != b.minLevel)  return a.minLevel  < b.minLevel;
            return a.name < b.name;
        });

        uint32 noFinal = 0;
        for (Dungeon const& d : catalogue)
            if (!d.hasFinalEncounter)
                ++noFinal;

        LOG_INFO("module.nekocore", "Challenge: {} dungeon(s) available ({} with no `lastEncounterDungeon` row, "
            "where a clear means every encounter done instead)", uint32(catalogue.size()), noFinal);
    }

    bool DungeonAllowedForEra(Dungeon const& d, uint8 era)
    {
        return d.expansion <= ExpansionForEra(era);
    }

    // ------------------------------------------------------------ tier store
    struct TierKey
    {
        uint32 charGuid;
        uint32 mapId;
        uint8  bracket;

        bool operator<(TierKey const& o) const
        {
            if (charGuid != o.charGuid) return charGuid < o.charGuid;
            if (mapId    != o.mapId)    return mapId    < o.mapId;
            return bracket < o.bracket;
        }
    };

    struct TierRow
    {
        uint16 tier     = 0;
        uint16 bestTier = 0;
        uint32 clears   = 0;
        uint32 fails    = 0;
    };

    std::mutex tiersMutex;
    std::map<TierKey, TierRow> tiers;

    void LoadTiers()
    {
        std::lock_guard<std::mutex> guard(tiersMutex);
        tiers.clear();

        QueryResult result = CharacterDatabase.Query(
            "SELECT char_guid, map_id, bracket, tier, best_tier, clears, fails FROM nekocore_challenge_tier");
        if (!result)
        {
            LOG_INFO("module.nekocore", "Challenge: no stored tiers yet");
            return;
        }

        do
        {
            Field* f = result->Fetch();
            TierKey key{ f[0].Get<uint32>(), f[1].Get<uint32>(), f[2].Get<uint8>() };
            TierRow row;
            row.tier     = f[3].Get<uint16>();
            row.bestTier = f[4].Get<uint16>();
            row.clears   = f[5].Get<uint32>();
            row.fails    = f[6].Get<uint32>();
            tiers[key] = row;
        } while (result->NextRow());

        LOG_INFO("module.nekocore", "Challenge: loaded {} stored tier row(s)", uint32(tiers.size()));
    }

    uint16 GetTier(uint32 charGuid, uint32 mapId, uint8 bracket)
    {
        std::lock_guard<std::mutex> guard(tiersMutex);
        auto it = tiers.find(TierKey{ charGuid, mapId, bracket });
        return it == tiers.end() ? 0 : it->second.tier;
    }

    /** Applies `delta` to one character's tier, persists it, returns the new value. */
    uint16 AdjustTier(uint32 charGuid, uint32 mapId, uint8 bracket, int32 delta, bool cleared)
    {
        TierRow row;
        {
            std::lock_guard<std::mutex> guard(tiersMutex);
            TierRow& stored = tiers[TierKey{ charGuid, mapId, bracket }];

            int32 next = int32(stored.tier) + delta;
            if (next < 0)
                next = 0;
            if (cfgMaxTier && next > int32(cfgMaxTier))
                next = int32(cfgMaxTier);
            stored.tier = uint16(next);

            if (cleared)
            {
                ++stored.clears;
                stored.bestTier = std::max<uint16>(stored.bestTier, stored.tier);
            }
            else
                ++stored.fails;

            row = stored;
        }

        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT INTO nekocore_challenge_tier (char_guid, map_id, bracket, tier, best_tier, clears, fails, updated_at) "
            "VALUES ({},{},{},{},{},{},{},{}) "
            "ON DUPLICATE KEY UPDATE tier = VALUES(tier), best_tier = VALUES(best_tier), "
            "clears = VALUES(clears), fails = VALUES(fails), updated_at = VALUES(updated_at)",
            charGuid, mapId, uint32(bracket), uint32(row.tier), uint32(row.bestTier),
            row.clears, row.fails, uint32(GameTime::GetGameTime().count())));

        return row.tier;
    }

    // ----------------------------------------------------------- armed state
    struct Armed
    {
        uint32 mapId   = 0;
        uint8  bracket = 0;
        uint16 tier    = 0;
        uint8  era     = 0;
        uint32 atMs    = 0;
    };

    std::mutex armedMutex;
    std::unordered_map<ObjectGuid, Armed> armed;

    uint32 NowMs() { return uint32(GameTime::GetGameTimeMS().count()); }

    bool ArmedFor(Player* player, Armed& out)
    {
        std::lock_guard<std::mutex> guard(armedMutex);
        auto it = armed.find(player->GetGUID());
        if (it == armed.end())
            return false;

        if (cfgArmedMinutes && NowMs() - it->second.atMs > cfgArmedMinutes * 60 * 1000)
        {
            armed.erase(it);
            return false;
        }
        out = it->second;
        return true;
    }

    void ClearArmed(ObjectGuid guid)
    {
        std::lock_guard<std::mutex> guard(armedMutex);
        armed.erase(guid);
    }

    // ------------------------------------------------------------ active runs
    struct RunState
    {
        NekocoreChallenge::ActiveRun info;
        uint32 instanceId = 0;
        uint8  era        = 0;
        uint32 leaderGuid = 0;
        uint16 bosses     = 0;
        uint16 deaths     = 0;
        bool   finished   = false;
        uint64 logRunId   = 0;
        std::unordered_map<uint32, uint16> members;   // char guid -> their tier on entry
    };

    std::mutex runsMutex;
    std::unordered_map<uint64, RunState> activeRuns;   // key: map id << 32 | instance id
    std::atomic<uint32> activeRunCount{ 0 };           // lock-free early out for the damage path
    uint64 nextRunId = 1;

    uint64 RunKey(Map const* map)
    {
        return (uint64(map->GetId()) << 32) | map->GetInstanceId();
    }

    void SeedRunIds()
    {
        if (QueryResult result = CharacterDatabase.Query("SELECT COALESCE(MAX(id), 0) FROM nekocore_challenge_run"))
            nextRunId = result->Fetch()[0].Get<uint64>() + 1;
    }

    std::string Escaped(std::string s)
    {
        CharacterDatabase.EscapeString(s);
        return s;
    }

    void Announce(Map* map, std::string const& message)
    {
        if (!cfgAnnounce)
            return;
        for (auto const& ref : map->GetPlayers())
            if (Player* p = ref.GetSource())
                ChatHandler(p->GetSession()).SendSysMessage(message.c_str());
    }

    /** Must hold runsMutex. Records a participant, once, with the tier they walked in on. */
    void RecordMember(RunState& run, Player* player)
    {
        uint32 charGuid = player->GetGUID().GetCounter();
        if (run.members.find(charGuid) != run.members.end())
            return;

        uint16 tier = GetTier(charGuid, run.info.mapId, run.info.bracket);
        run.members[charGuid] = tier;

        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT IGNORE INTO nekocore_challenge_member (run_id, char_guid, name, class, race, level, spec, tier_before) "
            "VALUES ({},{},'{}',{},{},{},{},{})",
            run.info.id, charGuid, Escaped(player->GetName()),
            uint32(player->getClass()), uint32(player->getRace()), uint32(player->GetLevel()),
            uint32(player->GetMostPointsTalentTree()), uint32(tier)));
    }

    /** Must hold runsMutex. Closes the run row and applies the tier change to every member. */
    void CloseRun(RunState& run, uint8 result)
    {
        if (run.finished)
            return;
        run.finished = true;

        bool cleared = result == 1;
        int32 delta = 0;
        if (cleared)
            delta = 1;
        else if (result == 2 && cfgWipePenalty)
            delta = -1;

        for (auto const& member : run.members)
        {
            uint16 after = member.second;
            if (delta)
                after = AdjustTier(member.first, run.info.mapId, run.info.bracket, delta, cleared);

            CharacterDatabase.Execute(Acore::StringFormat(
                "UPDATE nekocore_challenge_member SET tier_after = {} WHERE run_id = {} AND char_guid = {}",
                uint32(after), run.info.id, member.first));
        }

        CharacterDatabase.Execute(Acore::StringFormat(
            "UPDATE nekocore_challenge_run SET result = {}, ended_at = {}, bosses = {}, deaths = {}, log_run_id = {} "
            "WHERE id = {}",
            uint32(result), uint32(GameTime::GetGameTime().count()), uint32(run.bosses), uint32(run.deaths),
            run.logRunId, run.info.id));
    }

    /** Must hold runsMutex. Drops the flag: scaling stops and the instance is spent. */
    void Unflag(uint64 key)
    {
        if (!activeRuns.erase(key))
            return;
        activeRunCount.store(uint32(activeRuns.size()), std::memory_order_relaxed);
    }

    bool AnyAlivePlayer(Map* map)
    {
        for (auto const& ref : map->GetPlayers())
        {
            Player* p = ref.GetSource();
            if (p && p->IsAlive() && !p->IsGameMaster())
                return true;
        }
        return false;
    }

    /**
     * Has the dungeon just been finished?
     *
     * Primary signal is `instance_encounters.lastEncounterDungeon`, which is
     * AzerothCore's own record of which encounter completes a dungeon (it is
     * what hands out LFG completion credit) -- when a map has one, the run is
     * cleared by killing exactly that creature and nothing else counts.
     *
     * Some instances have no row with it set. For those the fallback is "every
     * encounter the instance script knows about is DONE", which is why
     * BuildCatalogue() counts and logs how many dungeons fall in that second
     * group. `doneBossId` is for the OnBeforeSetBossState caller: the state
     * being set hasn't landed on the instance script yet at that point, so the
     * check has to treat that one id as already DONE.
     */
    bool DungeonIsComplete(Map* map, Creature* deadBoss, int32 doneBossId)
    {
        DungeonEncounterList const* encounters =
            sObjectMgr->GetDungeonEncounterList(map->GetId(), map->GetDifficulty());
        if (!encounters || encounters->empty())
            return false;

        bool anyFinalFlagged = false;
        for (DungeonEncounter const* enc : *encounters)
        {
            if (!enc || !enc->lastEncounterDungeon)
                continue;
            anyFinalFlagged = true;
            if (deadBoss && enc->creditType == ENCOUNTER_CREDIT_KILL_CREATURE &&
                enc->creditEntry == deadBoss->GetEntry())
                return true;
        }

        if (anyFinalFlagged)
            return false;

        InstanceMap* instanceMap = map->ToInstanceMap();
        InstanceScript* instance = instanceMap ? instanceMap->GetInstanceScript() : nullptr;
        if (!instance || !instance->GetEncounterCount())
            return false;

        for (uint32 i = 0; i < instance->GetEncounterCount(); ++i)
            if (int32(i) != doneBossId && instance->GetBossState(i) != DONE)
                return false;
        return true;
    }

    /**
     * Shared tail of both clear paths (final boss died / last encounter set to
     * DONE). Returns the tier the dungeon will be at next time, or 0 if this
     * wasn't a live challenge instance after all.
     */
    uint16 FinishAsCleared(Map* map)
    {
        uint64 key = RunKey(map);
        uint16 newTier = 0;
        uint64 runId = 0;

        {
            std::lock_guard<std::mutex> guard(runsMutex);
            auto it = activeRuns.find(key);
            if (it == activeRuns.end() || it->second.finished)
                return 0;

            it->second.logRunId = NekoLog::RunIdFor(map);
            runId   = it->second.info.id;
            newTier = uint16(it->second.info.tier + 1);
            if (cfgMaxTier && newTier > cfgMaxTier)
                newTier = cfgMaxTier;
            CloseRun(it->second, 1);
            Unflag(key);
        }

        Announce(map, Acore::StringFormat(
            "|cff00ff00[Challenge]|r Cleared. Next time this place comes back at tier {} -- "
            "+{}% health, +{}% damage.",
            uint32(newTier), Pct(HealthMultFor(newTier)), Pct(DamageMultFor(newTier))));

        LOG_INFO("module.nekocore", "Challenge: run {} cleared on {}-{}, next tier {}",
            runId, map->GetId(), map->GetInstanceId(), uint32(newTier));
        return newTier;
    }
}

// ---------------------------------------------------------------- public API
namespace NekocoreChallenge
{
    bool Enabled() { return cfgEnable; }
    bool SuppressOutsideChallenges() { return cfgSuppressOutside; }
    uint8 DynamicLevelCeiling() { return cfgCeiling; }
    uint8 DynamicLevelFloor() { return cfgFloor; }

    bool ActiveRunFor(Map const* map, ActiveRun& out)
    {
        if (!cfgEnable || !map || !activeRunCount.load(std::memory_order_relaxed))
            return false;

        std::lock_guard<std::mutex> guard(runsMutex);
        auto it = activeRuns.find(RunKey(map));
        if (it == activeRuns.end())
            return false;
        out = it->second.info;
        return true;
    }
}

// ------------------------------------------------------------- Keeper gossip
namespace
{
    // Gossip action space. Dungeon picks are an offset plus the index into the
    // list the player was last shown, which is kept per player because the
    // list depends on their era.
    constexpr uint32 ACTION_STATUS  = 1;
    constexpr uint32 ACTION_CANCEL  = 2;
    constexpr uint32 ACTION_PAGE    = 100;    // + page number
    constexpr uint32 ACTION_DUNGEON = 1000;   // + index into `shown`
    constexpr uint32 PER_PAGE       = 12;
    constexpr uint32 KEEPER_TEXT_ID = 9000101;

    std::unordered_map<ObjectGuid, std::vector<uint32>> shown;   // player -> map ids, in menu order

    void SendKeeperMenu(Player* player, Creature* creature, uint32 page)
    {
        ClearGossipMenuFor(player);

        uint8  era      = sIndividualProgression->GetPlayerProgressionFromQuests(player);
        uint8  bracket  = BracketForEra(era);
        uint32 charGuid = player->GetGUID().GetCounter();

        if (player->GetLevel() < bracket)
        {
            AddGossipItemFor(player, GOSSIP_ICON_CHAT, Acore::StringFormat(
                "You are level {}. Come back at {} -- that is where the challenges are fought.",
                uint32(player->GetLevel()), uint32(bracket)),
                GOSSIP_SENDER_MAIN, ACTION_STATUS);
            SendGossipMenuFor(player, KEEPER_TEXT_ID, creature->GetGUID());
            return;
        }

        Armed current;
        if (ArmedFor(player, current))
        {
            Dungeon const* d = FindDungeon(current.mapId);
            AddGossipItemFor(player, GOSSIP_ICON_INTERACT_1, Acore::StringFormat(
                "Armed: {} at tier {}. Walk in and it begins.",
                d ? d->name : "that dungeon", uint32(current.tier)),
                GOSSIP_SENDER_MAIN, ACTION_STATUS);
            AddGossipItemFor(player, GOSSIP_ICON_INTERACT_2, "Call it off.", GOSSIP_SENDER_MAIN, ACTION_CANCEL);
            SendGossipMenuFor(player, KEEPER_TEXT_ID, creature->GetGUID());
            return;
        }

        std::vector<uint32> list;
        for (Dungeon const& d : catalogue)
            if (DungeonAllowedForEra(d, era))
                list.push_back(d.mapId);
        shown[player->GetGUID()] = list;

        AddGossipItemFor(player, GOSSIP_ICON_CHAT, Acore::StringFormat(
            "-- {} era: challenges fought at level {} --", BracketName(bracket), uint32(bracket)),
            GOSSIP_SENDER_MAIN, ACTION_STATUS);

        uint32 pages = list.empty() ? 1 : (uint32(list.size()) + PER_PAGE - 1) / PER_PAGE;
        if (page >= pages)
            page = 0;

        for (uint32 i = page * PER_PAGE; i < list.size() && i < (page + 1) * PER_PAGE; ++i)
        {
            Dungeon const* d = FindDungeon(list[i]);
            if (!d)
                continue;

            uint16 tier = GetTier(charGuid, d->mapId, bracket);
            std::string label = tier
                ? Acore::StringFormat("{} -- tier {} (+{}% health, +{}% damage)", d->name, uint32(tier),
                      Pct(HealthMultFor(tier)), Pct(DamageMultFor(tier)))
                : Acore::StringFormat("{} -- tier 0 (level {}, no bonus yet)", d->name, uint32(bracket));

            AddGossipItemFor(player, GOSSIP_ICON_BATTLE, label, GOSSIP_SENDER_MAIN, ACTION_DUNGEON + i);
        }

        if (pages > 1)
        {
            if (page > 0)
                AddGossipItemFor(player, GOSSIP_ICON_CHAT, "<- Back a page", GOSSIP_SENDER_MAIN, ACTION_PAGE + page - 1);
            if (page + 1 < pages)
                AddGossipItemFor(player, GOSSIP_ICON_CHAT, "More ->", GOSSIP_SENDER_MAIN, ACTION_PAGE + page + 1);
        }

        SendGossipMenuFor(player, KEEPER_TEXT_ID, creature->GetGUID());
    }
}

class ChallengeKeeper : public CreatureScript
{
public:
    ChallengeKeeper() : CreatureScript("npc_nekocore_challenge_keeper") { }

    bool OnGossipHello(Player* player, Creature* creature) override
    {
        if (!cfgEnable)
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cffff0000[Challenge]|r Challenge runs are switched off right now.");
            CloseGossipMenuFor(player);
            return true;
        }

        SendKeeperMenu(player, creature, 0);
        return true;
    }

    bool OnGossipSelect(Player* player, Creature* creature, uint32 /*sender*/, uint32 action) override
    {
        if (action == ACTION_STATUS)
        {
            SendKeeperMenu(player, creature, 0);
            return true;
        }

        if (action == ACTION_CANCEL)
        {
            ClearArmed(player->GetGUID());
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cff00ff00[Challenge]|r Called off -- nothing is armed.");
            SendKeeperMenu(player, creature, 0);
            return true;
        }

        if (action >= ACTION_PAGE && action < ACTION_DUNGEON)
        {
            SendKeeperMenu(player, creature, action - ACTION_PAGE);
            return true;
        }

        if (action < ACTION_DUNGEON)
            return true;

        uint32 index = action - ACTION_DUNGEON;
        auto it = shown.find(player->GetGUID());
        if (it == shown.end() || index >= it->second.size())
        {
            SendKeeperMenu(player, creature, 0);
            return true;
        }

        Dungeon const* dungeon = FindDungeon(it->second[index]);
        if (!dungeon)
        {
            SendKeeperMenu(player, creature, 0);
            return true;
        }

        uint8 era     = sIndividualProgression->GetPlayerProgressionFromQuests(player);
        uint8 bracket = BracketForEra(era);

        if (player->GetLevel() < bracket)
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cffff0000[Challenge]|r A challenge is fought at your era's cap -- come back at level %u.",
                uint32(bracket));
            CloseGossipMenuFor(player);
            return true;
        }

        if (!DungeonAllowedForEra(*dungeon, era))
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cffff0000[Challenge]|r That place isn't open to your era yet.");
            CloseGossipMenuFor(player);
            return true;
        }

        // Whoever leads the group sets its difficulty.
        if (Group* group = player->GetGroup())
        {
            if (!group->IsLeader(player->GetGUID()))
            {
                ChatHandler(player->GetSession()).PSendSysMessage(
                    "|cffff0000[Challenge]|r Your group leader sets the challenge -- ask them.");
                CloseGossipMenuFor(player);
                return true;
            }
        }

        uint16 tier = GetTier(player->GetGUID().GetCounter(), dungeon->mapId, bracket);

        {
            std::lock_guard<std::mutex> guard(armedMutex);
            Armed a;
            a.mapId   = dungeon->mapId;
            a.bracket = bracket;
            a.tier    = tier;
            a.era     = era;
            a.atMs    = NowMs();
            armed[player->GetGUID()] = a;
        }

        ChatHandler(player->GetSession()).PSendSysMessage(
            "|cff00ff00[Challenge]|r %s is armed at tier %u -- everything there at level %u, "
            "+%u%% health, +%u%% damage. Walk in (Dungeon Dan will take you) and it begins.",
            dungeon->name.c_str(), uint32(tier), uint32(bracket),
            Pct(HealthMultFor(tier)), Pct(DamageMultFor(tier)));

        CloseGossipMenuFor(player);
        return true;
    }
};

// -------------------------------------------------------- flagging / results
class ChallengeRun_MapScript : public AllMapScript
{
public:
    ChallengeRun_MapScript()
        : AllMapScript("ChallengeRun_MapScript", {
            ALLMAPHOOK_ON_PLAYER_ENTER_ALL,
            ALLMAPHOOK_ON_PLAYER_LEAVE_ALL,
            ALLMAPHOOK_ON_DESTROY_INSTANCE
        })
    {
    }

    void OnPlayerEnterAll(Map* map, Player* player) override
    {
        if (!cfgEnable || !player || !map || !map->IsDungeon() || map->IsRaid())
            return;

        uint64 key = RunKey(map);

        // Already a challenge instance: whoever comes in has to belong in the
        // bracket, and gets recorded as a participant.
        {
            std::lock_guard<std::mutex> guard(runsMutex);
            auto it = activeRuns.find(key);
            if (it != activeRuns.end())
            {
                RunState& run = it->second;
                if (player->IsGameMaster())
                    return;

                if (player->GetLevel() < run.info.bracket)
                {
                    ChatHandler(player->GetSession()).PSendSysMessage(
                        "|cffff0000[Challenge]|r This is a level %u challenge run -- you are level %u.",
                        uint32(run.info.bracket), uint32(player->GetLevel()));
                    player->TeleportTo(player->m_homebindMapId, player->m_homebindX, player->m_homebindY,
                        player->m_homebindZ, player->GetOrientation());
                    return;
                }

                RecordMember(run, player);
                ChatHandler(player->GetSession()).PSendSysMessage(
                    "|cff00ff00[Challenge]|r Tier %u: everything at level %u, +%u%% health, +%u%% damage.",
                    uint32(run.info.tier), uint32(run.info.bracket),
                    Pct(run.info.healthMult), Pct(run.info.damageMult));
                return;
            }
        }

        // Not flagged: does this player have a challenge armed for this map?
        Armed a;
        if (!ArmedFor(player, a) || a.mapId != map->GetId())
            return;

        if (player->GetLevel() < a.bracket)
            return;

        if (Group* group = player->GetGroup())
            if (!group->IsLeader(player->GetGUID()))
                return;   // the leader's entry is what starts it

        // A challenge starts at the door, not halfway through an instance
        // something has already been killed in.
        if (InstanceMap* instanceMap = map->ToInstanceMap())
            if (InstanceScript* instance = instanceMap->GetInstanceScript())
                for (uint32 i = 0; i < instance->GetEncounterCount(); ++i)
                    if (instance->GetBossState(i) == DONE)
                    {
                        ChatHandler(player->GetSession()).PSendSysMessage(
                            "|cffff0000[Challenge]|r Something has already died in here. "
                            "Reset the instance and come back in.");
                        return;
                    }

        ClearArmed(player->GetGUID());

        MapEntry const* entry = sMapStore.LookupEntry(map->GetId());
        std::string mapName = entry && entry->name[0] ? entry->name[0] : "";

        RunState run;
        run.info.mapId      = map->GetId();
        run.info.bracket    = a.bracket;
        run.info.tier       = a.tier;
        run.info.healthMult = HealthMultFor(a.tier);
        run.info.damageMult = DamageMultFor(a.tier);
        run.instanceId      = map->GetInstanceId();
        run.era             = a.era;
        run.leaderGuid      = player->GetGUID().GetCounter();

        {
            std::lock_guard<std::mutex> guard(runsMutex);
            run.info.id = nextRunId++;

            CharacterDatabase.Execute(Acore::StringFormat(
                "INSERT INTO nekocore_challenge_run (id, map_id, instance_id, map_name, bracket, tier, "
                "health_mult, damage_mult, era, leader_guid, leader_name, started_at) "
                "VALUES ({},{},{},'{}',{},{},{},{},{},{},'{}',{})",
                run.info.id, run.info.mapId, run.instanceId, Escaped(mapName),
                uint32(run.info.bracket), uint32(run.info.tier), run.info.healthMult, run.info.damageMult,
                uint32(run.era), run.leaderGuid, Escaped(player->GetName()),
                uint32(GameTime::GetGameTime().count())));

            RunState& stored = activeRuns[key];
            stored = run;
            activeRunCount.store(uint32(activeRuns.size()), std::memory_order_relaxed);

            // Anyone already standing inside is in the run too.
            for (auto const& ref : map->GetPlayers())
                if (Player* p = ref.GetSource())
                    if (!p->IsGameMaster() && p->GetLevel() >= stored.info.bracket)
                        RecordMember(stored, p);
        }

        NekocoreChallenge::ForceAutoBalanceRefresh(map);

        Announce(map, Acore::StringFormat(
            "|cff00ff00[Challenge]|r {} -- tier {}. Everything here fights at level {}, with +{}% health "
            "and +{}% damage. Clear it and the next one is harder.",
            mapName, uint32(run.info.tier), uint32(run.info.bracket),
            Pct(run.info.healthMult), Pct(run.info.damageMult)));

        LOG_INFO("module.nekocore", "Challenge: run {} flagged on {} ({}-{}) at tier {}, bracket {}, by {}",
            run.info.id, mapName, map->GetId(), map->GetInstanceId(), uint32(run.info.tier),
            uint32(run.info.bracket), player->GetName());
    }

    void OnPlayerLeaveAll(Map* map, Player* /*player*/) override
    {
        if (!cfgEnable || !map || !map->IsDungeon())
            return;

        std::lock_guard<std::mutex> guard(runsMutex);
        auto it = activeRuns.find(RunKey(map));
        if (it == activeRuns.end() || it->second.finished)
            return;

        // The flag deliberately survives an empty instance: walking back into
        // the SAME instance continues the same run rather than quietly
        // dropping everyone to unscaled mobs. It goes away with the instance
        // (OnDestroyInstance), which is also where an abandoned run is closed.
        if (map->GetPlayersCountExceptGMs())
            return;

        it->second.logRunId = NekoLog::RunIdFor(map);
        CharacterDatabase.Execute(Acore::StringFormat(
            "UPDATE nekocore_challenge_run SET log_run_id = {}, bosses = {}, deaths = {} WHERE id = {}",
            it->second.logRunId, uint32(it->second.bosses), uint32(it->second.deaths), it->second.info.id));
    }

    void OnDestroyInstance(MapInstanced* /*mapInstanced*/, Map* map) override
    {
        if (!map)
            return;

        std::lock_guard<std::mutex> guard(runsMutex);
        uint64 key = RunKey(map);
        auto it = activeRuns.find(key);
        if (it == activeRuns.end())
            return;

        if (!it->second.finished)
        {
            it->second.logRunId = NekoLog::RunIdFor(map);
            CloseRun(it->second, 3);   // abandoned -- no tier change either way
        }
        Unflag(key);
    }
};

class ChallengeRun_UnitScript : public UnitScript
{
public:
    ChallengeRun_UnitScript()
        : UnitScript("ChallengeRun_UnitScript", true, { UNITHOOK_ON_UNIT_DEATH })
    {
    }

    void OnUnitDeath(Unit* unit, Unit* /*killer*/) override
    {
        if (!cfgEnable || !unit)
            return;

        Map* map = unit->GetMap();
        if (!map || !map->IsDungeon() || !activeRunCount.load(std::memory_order_relaxed))
            return;

        uint64 key = RunKey(map);

        // Unit::Kill sets the victim's death state well before it fires this
        // hook (Unit.cpp: setDeathState(JustDied) then OnUnitDeath), so the
        // player who just died is already not alive to AnyAlivePlayer.
        if (Player* player = unit->ToPlayer())
        {
            bool wiped = false;
            uint64 runId = 0;
            {
                std::lock_guard<std::mutex> guard(runsMutex);
                auto it = activeRuns.find(key);
                if (it == activeRuns.end() || it->second.finished)
                    return;

                ++it->second.deaths;
                if (player->IsGameMaster() || AnyAlivePlayer(map))
                    return;

                it->second.logRunId = NekoLog::RunIdFor(map);
                runId = it->second.info.id;
                CloseRun(it->second, 2);   // wipe
                Unflag(key);
                wiped = true;
            }

            if (wiped)
            {
                Announce(map, cfgWipePenalty
                    ? "|cffff0000[Challenge]|r Wiped. That is a tier lost -- see the Keeper to arm another run."
                    : "|cffff0000[Challenge]|r Wiped. See the Keeper to arm another run.");
                LOG_INFO("module.nekocore", "Challenge: run {} wiped on {}-{}",
                    runId, map->GetId(), map->GetInstanceId());
            }
            return;
        }

        Creature* creature = unit->ToCreature();
        if (!creature || !creature->IsDungeonBoss())
            return;

        bool complete = false;
        {
            std::lock_guard<std::mutex> guard(runsMutex);
            auto it = activeRuns.find(key);
            if (it == activeRuns.end() || it->second.finished)
                return;

            ++it->second.bosses;
            // The log run certainly exists by the time a boss has died, so
            // link it now -- an abandoned run still points at its combat log.
            it->second.logRunId = NekoLog::RunIdFor(map);
            complete = DungeonIsComplete(map, creature, -1);
        }

        if (complete)
            FinishAsCleared(map);
    }
};

/*
 * The second clear path. For an instance whose `instance_encounters` rows have
 * no lastEncounterDungeon set, a clear is "every encounter DONE" -- and the
 * last one of those is not DONE yet while OnUnitDeath is running, because the
 * instance script sets the state afterwards. This hook is where that state
 * change is visible.
 */
class ChallengeRun_GlobalScript : public GlobalScript
{
public:
    ChallengeRun_GlobalScript()
        : GlobalScript("ChallengeRun_GlobalScript", { GLOBALHOOK_ON_BEFORE_SET_BOSS_STATE })
    {
    }

    void OnBeforeSetBossState(uint32 id, EncounterState newState, EncounterState oldState, Map* map) override
    {
        if (!cfgEnable || newState != DONE || oldState == DONE || !map || !map->IsDungeon())
            return;

        if (!activeRunCount.load(std::memory_order_relaxed))
            return;

        bool complete = false;
        {
            std::lock_guard<std::mutex> guard(runsMutex);
            auto it = activeRuns.find(RunKey(map));
            if (it == activeRuns.end() || it->second.finished)
                return;
            complete = DungeonIsComplete(map, nullptr, int32(id));
        }

        if (complete)
            FinishAsCleared(map);
    }
};

class ChallengeRun_WorldScript : public WorldScript
{
public:
    ChallengeRun_WorldScript() : WorldScript("ChallengeRun_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        LoadConfig();
    }

    void OnStartup() override
    {
        if (!cfgEnable)
        {
            LOG_INFO("module.nekocore", "Challenge: disabled (Nekocore.Challenge.Enable = 0)");
            return;
        }

        BuildCatalogue();
        LoadTiers();
        SeedRunIds();
    }
};

class ChallengeRun_PlayerScript : public PlayerScript
{
public:
    ChallengeRun_PlayerScript() : PlayerScript("ChallengeRun_PlayerScript") { }

    void OnPlayerLogout(Player* player) override
    {
        ClearArmed(player->GetGUID());
        shown.erase(player->GetGUID());
    }
};

void AddSC_nekocore_challenge_run()
{
    new ChallengeKeeper();
    new ChallengeRun_MapScript();
    new ChallengeRun_UnitScript();
    new ChallengeRun_GlobalScript();
    new ChallengeRun_WorldScript();
    new ChallengeRun_PlayerScript();
}

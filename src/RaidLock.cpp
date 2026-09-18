/*
 * Live-toggleable per-map entry lock. Built for a specific need: block
 * every player from entering a raid (Molten Core first, map id 409) while
 * its fights are still being tuned, without anyone able to charge in and
 * see a half-balanced encounter -- then reopen it live, no restart, once
 * it's ready. This is deliberately generic (any map id, not just MC) so
 * the same config covers whichever raid is currently being worked on as
 * that work moves on to the next one.
 *
 * mod-individual-progression's own IndividualProgression.ProgressionLimit
 * looked like the natural fit at first, but it doesn't do this: it only
 * gates ADVANCING to a new progression stage (rewarding the next hidden
 * quest in the chain), not entry into a specific instance. Molten Core in
 * particular has no progression gate on it at all in that module's own
 * scripts (checked instance_molten_core.cpp directly -- it's available
 * from PROGRESSION_START, being the very first raid), so there was no
 * existing "lock this raid" switch to reuse.
 *
 * Hook: PlayerScript::OnPlayerBeforeTeleport, called from inside
 * Player::TeleportTo itself (confirmed at the actual call site,
 * Player.cpp: `if (!sScriptMgr->OnPlayerBeforeTeleport(...)) return false;`)
 * -- returning false here aborts the teleport before anything happens, for
 * EVERY way a player can end up on a map (portal, hearthstone, GM
 * teleport, and group summons all funnel through TeleportTo), not just
 * walking through a specific entrance.
 *
 * GMs always pass through regardless of lock state (WorldSession::
 * IsGMAccount(), same check the core itself uses) -- the whole point is
 * being able to keep testing/tuning a raid while it's locked to everyone
 * else.
 *
 * Config: Nekocore.LockedMaps, a comma-separated list of map ids, reloaded
 * live via WorldScript::OnBeforeConfigLoad (fires on `.reload config`, no
 * restart needed) -- see conf/nekocore.conf.dist.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "WorldSession.h"
#include "Chat.h"
#include "Config.h"

#include <set>
#include <sstream>

namespace
{
    std::set<uint32> lockedMaps;

    void LoadLockedMaps()
    {
        lockedMaps.clear();
        std::string raw = sConfigMgr->GetOption<std::string>("Nekocore.LockedMaps", "");
        std::stringstream ss(raw);
        std::string token;
        while (std::getline(ss, token, ','))
        {
            if (token.empty())
                continue;
            try
            {
                lockedMaps.insert(uint32(std::stoul(token)));
            }
            catch (std::exception const&)
            {
                LOG_ERROR("module.nekocore", "Nekocore.LockedMaps: '{}' is not a valid map id, ignoring", token);
            }
        }
    }
}

class RaidLock_WorldScript : public WorldScript
{
public:
    RaidLock_WorldScript() : WorldScript("RaidLock_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        LoadLockedMaps();
    }
};

class RaidLock_PlayerScript : public PlayerScript
{
public:
    RaidLock_PlayerScript() : PlayerScript("RaidLock_PlayerScript") { }

    bool OnPlayerBeforeTeleport(Player* player, uint32 mapid, float /*x*/, float /*y*/, float /*z*/, float /*orientation*/, uint32 /*options*/, Unit* /*target*/) override
    {
        if (!player || lockedMaps.find(mapid) == lockedMaps.end())
            return true;

        if (player->GetSession() && player->GetSession()->IsGMAccount())
            return true;

        ChatHandler(player->GetSession()).PSendSysMessage(
            "|cffff0000[Raid Lock]|r This raid is closed for maintenance -- come back soon.");
        return false;
    }
};

void AddSC_raid_lock()
{
    new RaidLock_WorldScript();
    new RaidLock_PlayerScript();
}

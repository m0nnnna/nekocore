/*
 * Boss Teleporter -- an item that teleports its holder to any boss in any
 * dungeon or raid.
 *
 * Item entry 9000102 (data/sql/db-world/base/boss_teleporter.sql), ScriptName
 * item_nekocore_boss_teleporter. Using it opens a gossip menu: pick an
 * instance, pick a boss, land on that boss's spawn point.
 *
 * The list is not a hand-kept coordinate table. It is built once, on first
 * use, from the world database: every creature that is an instance_encounters
 * credit entry (what the core itself treats as "a boss of this map") joined to
 * where it is spawned. So it follows the DB -- a boss added, moved or removed
 * there shows up here after the next worldserver start -- and Dungeon Dan's
 * dungeon table and this one cannot drift apart because neither is the other.
 *
 * It teleports straight onto the map, so the normal entry rules still apply:
 * a raid refuses a player who is not in a raid group, and nothing here
 * touches lockouts or the raid-lock script (RaidLock.cpp), which sees an
 * ordinary teleport.
 */

#include "ScriptMgr.h"
#include "ScriptedGossip.h"
#include "Player.h"
#include "Item.h"
#include "DBCStores.h"
#include "DatabaseEnv.h"
#include "Chat.h"
#include "WorldSession.h"
#include "StringFormat.h"

#include <algorithm>
#include <iterator>
#include <mutex>
#include <set>
#include <string>
#include <vector>

namespace
{
    constexpr uint32 TELEPORTER_TEXT_ID = 9000102;
    constexpr uint32 PER_PAGE           = 14;

    // Gossip sender space. MAIN's action is a page of the instance list;
    // SENDER_BOSSES + i's action is a page of instance i's boss list;
    // SENDER_GO + i's action is the index of the boss to go to.
    constexpr uint32 SENDER_BOSSES = 0x1000;
    constexpr uint32 SENDER_GO     = 0x2000;

    struct Boss
    {
        std::string name;
        float x, y, z, o;
    };

    struct Instance
    {
        uint32 mapId;
        std::string name;
        std::vector<Boss> bosses;
    };

    std::vector<Instance> instances;
    std::once_flag loaded;

    void Load()
    {
        QueryResult result = WorldDatabase.Query(
            "SELECT c.`map`, t.`name`, c.`position_x`, c.`position_y`, c.`position_z`, c.`orientation` "
            "FROM `instance_encounters` e "
            "JOIN `creature` c ON c.`id` = e.`creditEntry` "
            "JOIN `creature_template` t ON t.`entry` = c.`id` "
            "WHERE e.`creditType` = 0 "
            "ORDER BY c.`map`, e.`entry`, c.`guid`");
        if (!result)
            return;

        std::set<std::pair<uint32, std::string>> seen;   // the same boss is often listed once per difficulty
        do
        {
            Field* f = result->Fetch();
            uint32 mapId = f[0].Get<uint32>();
            std::string name = f[1].Get<std::string>();

            MapEntry const* entry = sMapStore.LookupEntry(mapId);
            if (!entry || !entry->IsDungeon())
                continue;
            if (!seen.insert({ mapId, name }).second)
                continue;

            auto it = std::find_if(instances.begin(), instances.end(),
                [mapId](Instance const& i) { return i.mapId == mapId; });
            if (it == instances.end())
            {
                instances.push_back({ mapId, entry->name[0] ? entry->name[0] : Acore::StringFormat("Map {}", mapId), {} });
                it = std::prev(instances.end());
            }
            it->bosses.push_back({ name, f[2].Get<float>(), f[3].Get<float>(), f[4].Get<float>(), f[5].Get<float>() });
        } while (result->NextRow());

        std::sort(instances.begin(), instances.end(),
            [](Instance const& a, Instance const& b) { return a.name < b.name; });
    }

    // Adds the "back a page / more" rows; returns the page actually shown.
    uint32 AddPaging(Player* player, uint32 sender, uint32 page, size_t count)
    {
        uint32 pages = count ? uint32((count + PER_PAGE - 1) / PER_PAGE) : 1;
        if (page >= pages)
            page = 0;
        if (page > 0)
            AddGossipItemFor(player, GOSSIP_ICON_CHAT, "<- Back a page", sender, page - 1);
        if (page + 1 < pages)
            AddGossipItemFor(player, GOSSIP_ICON_CHAT, "More ->", sender, page + 1);
        return page;
    }

    void SendInstances(Player* player, Item* item, uint32 page)
    {
        ClearGossipMenuFor(player);
        uint32 pages = instances.empty() ? 1 : uint32((instances.size() + PER_PAGE - 1) / PER_PAGE);
        if (page >= pages)
            page = 0;

        for (size_t i = page * PER_PAGE; i < instances.size() && i < (page + 1) * PER_PAGE; ++i)
            AddGossipItemFor(player, GOSSIP_ICON_BATTLE, instances[i].name, SENDER_BOSSES + uint32(i), 0);

        AddPaging(player, GOSSIP_SENDER_MAIN, page, instances.size());
        SendGossipMenuFor(player, TELEPORTER_TEXT_ID, item->GetGUID());
    }

    void SendBosses(Player* player, Item* item, uint32 index, uint32 page)
    {
        ClearGossipMenuFor(player);
        Instance const& inst = instances[index];
        uint32 pages = uint32((inst.bosses.size() + PER_PAGE - 1) / PER_PAGE);
        if (page >= pages)
            page = 0;

        for (size_t i = page * PER_PAGE; i < inst.bosses.size() && i < (page + 1) * PER_PAGE; ++i)
            AddGossipItemFor(player, GOSSIP_ICON_TAXI, inst.bosses[i].name, SENDER_GO + index, uint32(i));

        AddPaging(player, SENDER_BOSSES + index, page, inst.bosses.size());
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "<- All dungeons", GOSSIP_SENDER_MAIN, 0);
        SendGossipMenuFor(player, TELEPORTER_TEXT_ID, item->GetGUID());
    }
}

class item_nekocore_boss_teleporter : public ItemScript
{
public:
    item_nekocore_boss_teleporter() : ItemScript("item_nekocore_boss_teleporter") { }

    bool OnUse(Player* player, Item* item, SpellCastTargets const& /*targets*/) override
    {
        std::call_once(loaded, Load);

        if (player->IsInCombat() || player->InBattleground() || player->InArena())
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cffff0000[Boss Teleporter]|r You can't use that right now.");
            return true;
        }

        SendInstances(player, item, 0);
        return true;   // handled: don't cast the item's placeholder spell
    }

    void OnGossipSelect(Player* player, Item* item, uint32 sender, uint32 action) override
    {
        if (sender == GOSSIP_SENDER_MAIN)
        {
            SendInstances(player, item, action);
        }
        else if (sender >= SENDER_GO && sender - SENDER_GO < instances.size())
        {
            Instance const& inst = instances[sender - SENDER_GO];
            CloseGossipMenuFor(player);
            if (action >= inst.bosses.size() || player->IsInCombat())
                return;

            Boss const& b = inst.bosses[action];
            ChatHandler(player->GetSession()).PSendSysMessage(
                "|cff00ff00[Boss Teleporter]|r {} -- {}.", inst.name, b.name);
            player->TeleportTo(inst.mapId, b.x, b.y, b.z + 0.5f, b.o);
        }
        else if (sender >= SENDER_BOSSES && sender - SENDER_BOSSES < instances.size())
        {
            SendBosses(player, item, sender - SENDER_BOSSES, action);
        }
        else
        {
            CloseGossipMenuFor(player);
        }
    }
};

void AddSC_nekocore_boss_teleporter()
{
    new item_nekocore_boss_teleporter();
}

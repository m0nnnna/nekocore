/*
 * mod-live-reload
 *
 * Live reload of world data without restarting the worldserver.
 * Covers all systems that normally require a full restart.
 *
 * Commands (SEC_ADMINISTRATOR, usable from console and in-game):
 *
 *   .rlive vendor   [entry]   Reload npc_vendor. Vendor data is read on next window open.
 *   .rlive trainer  [entry]   Reload npc_trainer.
 *   .rlive item               Reload item_template (prices, stats, flags, etc).
 *   .rlive quest              Reload quest_template + relations.
 *   .rlive creature <entry>   Reload creature_template entry + respawn all live instances.
 *   .rlive gobject  <entry>   Reload gameobject_template (full) + respawn live instances of entry.
 *   .rlive script             Reload smart_scripts.
 *   .rlive gossip             Reload gossip_menu + gossip_menu_option + conditions.
 *   .rlive loot <type>        Reload a loot table.
 *                             Types: creature fishing gameobject skinning
 *                                    pickpocketing mail disenchant prospecting milling
 *   .rlive pool               Reload spawn pool templates.
 *   .rlive condition          Reload conditions.
 *   .rlive access             Reload instance/dungeon access requirements.
 *   .rlive spell              Reload all SpellMgr modifier tables (bonus_data, linked_spell,
 *                             proc, threats, group, area, etc). Global — no respawn needed.
 *   .rlive spells <entry>     Reload creature_template spell slots for <entry> and hot-patch
 *                             every currently live instance in memory — no despawn, safe during
 *                             combat. Use this to change which spells a boss casts mid-fight.
 *   .rlive all                Reload every system above in one shot.
 */

#include "AI/SmartScripts/SmartScriptMgr.h"
#include "Chat.h"
#include "ChatCommand.h"
#include "Conditions/ConditionMgr.h"
#include "Creature.h"
#include "DatabaseEnv.h"
#include "GameObject.h"
#include "Log.h"
#include "Loot/LootMgr.h"
#include "Map.h"
#include "MapMgr.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "Pools/PoolMgr.h"
#include "ScriptMgr.h"
#include "SpellMgr.h"

using namespace Acore::ChatCommands;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Patch m_spells[] on every live creature instance with the given entry.
// Does NOT despawn — safe to call on an engaged raid boss.
static uint32 PatchSpellsOnLiveCreatures(uint32 entry, CreatureTemplate const* cInfo)
{
    uint32 count = 0;

    QueryResult result = WorldDatabase.Query(
        "SELECT guid, map FROM creature WHERE id = {}", entry);

    if (!result)
        return 0;

    do
    {
        Field* fields = result->Fetch();
        ObjectGuid::LowType spawnId = fields[0].Get<uint32>();
        uint32 mapId = fields[1].Get<uint16>();

        sMapMgr->DoForAllMapsWithMapId(mapId, [spawnId, cInfo, &count](Map* map)
        {
            auto& spawnStore = map->GetCreatureBySpawnIdStore();
            auto itr = spawnStore.find(spawnId);
            if (itr == spawnStore.end())
                return;

            Creature* creature = itr->second;
            if (!creature || !creature->IsInWorld())
                return;

            // Hot-patch the spell slots directly — no despawn, no AI reset
            for (uint8 i = 0; i < MAX_CREATURE_SPELLS; ++i)
                creature->m_spells[i] = cInfo->spells[i];

            ++count;
        });

    } while (result->NextRow());

    return count;
}

static uint32 RespawnCreaturesByEntry(uint32 entry)
{
    uint32 count = 0;

    QueryResult result = WorldDatabase.Query(
        "SELECT guid, map FROM creature WHERE id = {}", entry);

    if (!result)
        return 0;

    do
    {
        Field* fields = result->Fetch();
        ObjectGuid::LowType spawnId = fields[0].Get<uint32>();
        uint32 mapId = fields[1].Get<uint16>();

        sMapMgr->DoForAllMapsWithMapId(mapId, [spawnId, &count](Map* map)
        {
            auto& spawnStore = map->GetCreatureBySpawnIdStore();
            auto itr = spawnStore.find(spawnId);
            if (itr == spawnStore.end())
                return;

            Creature* creature = itr->second;
            if (creature && creature->IsInWorld())
            {
                creature->DespawnOrUnsummon(0ms, 3s);
                ++count;
            }
        });

    } while (result->NextRow());

    return count;
}

static uint32 RespawnGobjectsByEntry(uint32 entry)
{
    uint32 count = 0;

    QueryResult result = WorldDatabase.Query(
        "SELECT guid, map FROM gameobject WHERE id = {}", entry);

    if (!result)
        return 0;

    do
    {
        Field* fields = result->Fetch();
        ObjectGuid::LowType spawnId = fields[0].Get<uint32>();
        uint32 mapId = fields[1].Get<uint16>();

        sMapMgr->DoForAllMapsWithMapId(mapId, [spawnId, &count](Map* map)
        {
            auto& spawnStore = map->GetGameObjectBySpawnIdStore();
            auto itr = spawnStore.find(spawnId);
            if (itr == spawnStore.end())
                return;

            GameObject* go = itr->second;
            if (go && go->IsInWorld())
            {
                go->SetRespawnTime(0);
                go->Delete();
                ++count;
            }
        });

    } while (result->NextRow());

    return count;
}

// ---------------------------------------------------------------------------
// Command script
// ---------------------------------------------------------------------------

class mod_live_reload_commandscript : public CommandScript
{
public:
    mod_live_reload_commandscript() : CommandScript("mod_live_reload_commandscript") {}

    ChatCommandTable GetCommands() const override
    {
        static ChatCommandTable liveTable =
        {
            { "vendor",    HandleVendorCommand,    SEC_ADMINISTRATOR, Console::Yes },
            { "trainer",   HandleTrainerCommand,   SEC_ADMINISTRATOR, Console::Yes },
            { "item",      HandleItemCommand,      SEC_ADMINISTRATOR, Console::Yes },
            { "quest",     HandleQuestCommand,     SEC_ADMINISTRATOR, Console::Yes },
            { "creature",  HandleCreatureCommand,  SEC_ADMINISTRATOR, Console::Yes },
            { "gobject",   HandleGobjectCommand,   SEC_ADMINISTRATOR, Console::Yes },
            { "script",    HandleScriptCommand,    SEC_ADMINISTRATOR, Console::Yes },
            { "gossip",    HandleGossipCommand,    SEC_ADMINISTRATOR, Console::Yes },
            { "loot",      HandleLootCommand,      SEC_ADMINISTRATOR, Console::Yes },
            { "pool",      HandlePoolCommand,      SEC_ADMINISTRATOR, Console::Yes },
            { "condition", HandleConditionCommand, SEC_ADMINISTRATOR, Console::Yes },
            { "access",    HandleAccessCommand,    SEC_ADMINISTRATOR, Console::Yes },
            { "spell",     HandleSpellCommand,     SEC_ADMINISTRATOR, Console::Yes },
            { "spells",    HandleSpellsCommand,    SEC_ADMINISTRATOR, Console::Yes },
            { "all",       HandleAllCommand,       SEC_ADMINISTRATOR, Console::Yes },
        };

        static ChatCommandTable commandTable =
        {
            { "rlive", liveTable },
        };

        return commandTable;
    }

    // -----------------------------------------------------------------------
    // .rlive vendor [entry]
    // Vendor lists are read from ObjectMgr on each window open — no respawn needed.
    // -----------------------------------------------------------------------
    static bool HandleVendorCommand(ChatHandler* handler, Optional<uint32> entry)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading npc_vendor...");
        sObjectMgr->LoadVendors();

        if (entry)
        {
            QueryResult result = WorldDatabase.Query(
                "SELECT COUNT(*) FROM creature WHERE id = {}", *entry);
            uint32 spawnCount = result ? result->Fetch()[0].Get<uint32>() : 0;
            handler->PSendSysMessage(
                "[live-reload] npc_vendor reloaded. Entry %u has %u world spawn(s). "
                "Updated inventory visible on next vendor open.", *entry, spawnCount);
        }
        else
        {
            handler->SendGlobalGMSysMessage("[live-reload] npc_vendor reloaded.");
        }

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive trainer [entry]
    // -----------------------------------------------------------------------
    static bool HandleTrainerCommand(ChatHandler* handler, Optional<uint32> /*entry*/)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading npc_trainer...");
        sObjectMgr->LoadTrainers();
        handler->SendGlobalGMSysMessage("[live-reload] npc_trainer reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive item
    // -----------------------------------------------------------------------
    static bool HandleItemCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading item_template...");
        sObjectMgr->LoadItemTemplates();
        handler->SendGlobalGMSysMessage("[live-reload] item_template reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive quest
    // -----------------------------------------------------------------------
    static bool HandleQuestCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading quest_template...");
        sObjectMgr->LoadQuests();
        sObjectMgr->LoadQuestStartersAndEnders();
        handler->SendGlobalGMSysMessage("[live-reload] quest_template + starters/enders reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive creature <entry>
    // Reloads the creature_template row for <entry>, then respawns every live
    // instance so new stats/faction/flags take effect immediately.
    // -----------------------------------------------------------------------
    static bool HandleCreatureCommand(ChatHandler* handler, uint32 entry)
    {
        CreatureTemplate const* cTemplate = sObjectMgr->GetCreatureTemplate(entry);
        if (!cTemplate)
        {
            handler->PSendSysMessage("[live-reload] Entry %u not found in creature_template.", entry);
            return true;
        }

        WorldDatabasePreparedStatement* stmt =
            WorldDatabase.GetPreparedStatement(WORLD_SEL_CREATURE_TEMPLATE);
        stmt->SetData(0, entry);
        PreparedQueryResult result = WorldDatabase.Query(stmt);

        if (!result)
        {
            handler->PSendSysMessage("[live-reload] No DB row found for creature entry %u.", entry);
            return true;
        }

        CreatureTemplate* cInfo = const_cast<CreatureTemplate*>(cTemplate);
        sObjectMgr->LoadCreatureTemplate(result->Fetch(), true);
        sObjectMgr->CheckCreatureTemplate(cInfo);

        uint32 respawned = RespawnCreaturesByEntry(entry);

        handler->PSendSysMessage(
            "[live-reload] creature_template entry %u reloaded. "
            "%u live instance(s) queued for respawn in 3s.", entry, respawned);

        LOG_INFO("server.loading",
            "mod-live-reload: creature_template {} reloaded ({} respawns)", entry, respawned);

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive gobject <entry>
    // Reloads the full gameobject_template table (no per-entry API exists), then
    // respawns every live instance of the specified entry.
    // -----------------------------------------------------------------------
    static bool HandleGobjectCommand(ChatHandler* handler, uint32 entry)
    {
        if (!sObjectMgr->GetGameObjectTemplate(entry))
        {
            handler->PSendSysMessage("[live-reload] Entry %u not found in gameobject_template.", entry);
            return true;
        }

        LOG_INFO("server.loading", "mod-live-reload: Reloading gameobject_template...");
        sObjectMgr->LoadGameObjectTemplate();
        sObjectMgr->LoadGameObjectTemplateAddons();

        uint32 respawned = RespawnGobjectsByEntry(entry);

        handler->PSendSysMessage(
            "[live-reload] gameobject_template reloaded. "
            "%u live instance(s) of entry %u queued for respawn.", respawned, entry);

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive script
    // -----------------------------------------------------------------------
    static bool HandleScriptCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading smart_scripts...");
        sSmartScriptMgr->LoadSmartAIFromDB();
        handler->SendGlobalGMSysMessage("[live-reload] smart_scripts reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive gossip
    // -----------------------------------------------------------------------
    static bool HandleGossipCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading gossip tables...");
        sObjectMgr->LoadGossipMenu();
        sObjectMgr->LoadGossipMenuItems();
        sConditionMgr->LoadConditions(true);
        handler->SendGlobalGMSysMessage("[live-reload] gossip_menu + gossip_menu_option + conditions reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive loot <type>
    // -----------------------------------------------------------------------
    static bool HandleLootCommand(ChatHandler* handler, std::string_view lootType)
    {
        std::string type(lootType);

        if (type == "creature")
        {
            LootTemplates_Creature.ResetConditions();
            LoadLootTemplates_Creature();
            LootTemplates_Creature.CheckLootRefs();
            handler->SendGlobalGMSysMessage("[live-reload] creature_loot_template reloaded.");
        }
        else if (type == "fishing")
        {
            LootTemplates_Fishing.ResetConditions();
            LoadLootTemplates_Fishing();
            handler->SendGlobalGMSysMessage("[live-reload] fishing_loot_template reloaded.");
        }
        else if (type == "gameobject")
        {
            LootTemplates_Gameobject.ResetConditions();
            LoadLootTemplates_Gameobject();
            LootTemplates_Gameobject.CheckLootRefs();
            handler->SendGlobalGMSysMessage("[live-reload] gameobject_loot_template reloaded.");
        }
        else if (type == "skinning")
        {
            LootTemplates_Skinning.ResetConditions();
            LoadLootTemplates_Skinning();
            LootTemplates_Skinning.CheckLootRefs();
            handler->SendGlobalGMSysMessage("[live-reload] skinning_loot_template reloaded.");
        }
        else if (type == "pickpocketing")
        {
            LootTemplates_Pickpocketing.ResetConditions();
            LoadLootTemplates_Pickpocketing();
            LootTemplates_Pickpocketing.CheckLootRefs();
            handler->SendGlobalGMSysMessage("[live-reload] pickpocketing_loot_template reloaded.");
        }
        else if (type == "mail")
        {
            LootTemplates_Mail.ResetConditions();
            LoadLootTemplates_Mail();
            LootTemplates_Mail.CheckLootRefs();
            handler->SendGlobalGMSysMessage("[live-reload] mail_loot_template reloaded.");
        }
        else if (type == "disenchant")
        {
            LootTemplates_Disenchant.ResetConditions();
            LoadLootTemplates_Disenchant();
            handler->SendGlobalGMSysMessage("[live-reload] disenchant_loot_template reloaded.");
        }
        else if (type == "prospecting")
        {
            LootTemplates_Prospecting.ResetConditions();
            LoadLootTemplates_Prospecting();
            handler->SendGlobalGMSysMessage("[live-reload] prospecting_loot_template reloaded.");
        }
        else if (type == "milling")
        {
            LootTemplates_Milling.ResetConditions();
            LoadLootTemplates_Milling();
            handler->SendGlobalGMSysMessage("[live-reload] milling_loot_template reloaded.");
        }
        else
        {
            handler->PSendSysMessage(
                "[live-reload] Unknown loot type '%s'. Valid types: "
                "creature fishing gameobject skinning pickpocketing mail disenchant prospecting milling",
                type.c_str());
        }

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive pool
    // -----------------------------------------------------------------------
    static bool HandlePoolCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading pool templates...");
        sPoolMgr->LoadFromDB();
        handler->SendGlobalGMSysMessage("[live-reload] pool_template reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive condition
    // -----------------------------------------------------------------------
    static bool HandleConditionCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading conditions...");
        sConditionMgr->LoadConditions(true);
        handler->SendGlobalGMSysMessage("[live-reload] conditions reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive access
    // -----------------------------------------------------------------------
    static bool HandleAccessCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading access_requirement...");
        sObjectMgr->LoadAccessRequirements();
        handler->SendGlobalGMSysMessage("[live-reload] access_requirement reloaded.");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive spell
    // Reloads all SpellMgr modifier tables: bonus_data, linked_spell, proc,
    // threats, group, group_stack_rules, area, pet_auras, spell_required.
    // These are global lookups — effect is immediate on all future casts.
    // -----------------------------------------------------------------------
    static bool HandleSpellCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading SpellMgr tables...");

        sSpellMgr->LoadSpellRequired();
        sSpellMgr->LoadSpellGroups();
        sSpellMgr->LoadSpellGroupStackRules();
        sSpellMgr->LoadSpellProcs();
        sSpellMgr->LoadSpellBonuses();
        sSpellMgr->LoadSpellThreats();
        sSpellMgr->LoadSpellLinked();
        sSpellMgr->LoadSpellPetAuras();
        sSpellMgr->LoadSpellAreas();

        handler->SendGlobalGMSysMessage(
            "[live-reload] SpellMgr tables reloaded "
            "(bonus_data, linked_spell, proc, threats, group, area, pet_auras, required). "
            "Takes effect on all future casts.");

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive spells <entry>
    // Reloads creature_template for <entry> then hot-patches m_spells[] on
    // every currently live instance — no despawn, no AI reset, safe mid-combat.
    // Use this to change which spells a boss casts without resetting the fight.
    //
    // Note: this only affects the spell SLOTS (spell1-spell8 in creature_template).
    // Hardcoded casts inside C++ boss scripts are not affected.
    // -----------------------------------------------------------------------
    static bool HandleSpellsCommand(ChatHandler* handler, uint32 entry)
    {
        CreatureTemplate const* cTemplate = sObjectMgr->GetCreatureTemplate(entry);
        if (!cTemplate)
        {
            handler->PSendSysMessage("[live-reload] Entry %u not found in creature_template.", entry);
            return true;
        }

        // Reload this entry's template row from DB
        WorldDatabasePreparedStatement* stmt =
            WorldDatabase.GetPreparedStatement(WORLD_SEL_CREATURE_TEMPLATE);
        stmt->SetData(0, entry);
        PreparedQueryResult result = WorldDatabase.Query(stmt);

        if (!result)
        {
            handler->PSendSysMessage("[live-reload] No DB row found for creature entry %u.", entry);
            return true;
        }

        CreatureTemplate* cInfo = const_cast<CreatureTemplate*>(cTemplate);
        sObjectMgr->LoadCreatureTemplate(result->Fetch(), true);
        sObjectMgr->CheckCreatureTemplate(cInfo);

        // Hot-patch live instances in-place — no despawn
        uint32 patched = PatchSpellsOnLiveCreatures(entry, cInfo);

        handler->PSendSysMessage(
            "[live-reload] creature_template entry %u spell slots reloaded. "
            "%u live instance(s) patched in memory (no despawn).", entry, patched);

        LOG_INFO("server.loading",
            "mod-live-reload: spell slots for creature {} patched on {} live instance(s)", entry, patched);

        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive all
    // Reload every managed system. Does NOT force creature/gobject respawns —
    // use the targeted subcommands for that.
    // -----------------------------------------------------------------------
    static bool HandleAllCommand(ChatHandler* handler)
    {
        handler->SendGlobalGMSysMessage("[live-reload] Reloading all systems...");

        sObjectMgr->LoadVendors();
        sObjectMgr->LoadTrainers();
        sObjectMgr->LoadItemTemplates();
        sObjectMgr->LoadQuests();
        sObjectMgr->LoadQuestStartersAndEnders();
        sObjectMgr->LoadGossipMenu();
        sObjectMgr->LoadGossipMenuItems();
        sObjectMgr->LoadAccessRequirements();
        sObjectMgr->LoadCreatureTemplateAddons();
        sObjectMgr->LoadGameObjectTemplate();
        sObjectMgr->LoadGameObjectTemplateAddons();
        sSmartScriptMgr->LoadSmartAIFromDB();
        sConditionMgr->LoadConditions(true);
        sPoolMgr->LoadFromDB();

        sSpellMgr->LoadSpellRequired();
        sSpellMgr->LoadSpellGroups();
        sSpellMgr->LoadSpellGroupStackRules();
        sSpellMgr->LoadSpellProcs();
        sSpellMgr->LoadSpellBonuses();
        sSpellMgr->LoadSpellThreats();
        sSpellMgr->LoadSpellLinked();
        sSpellMgr->LoadSpellPetAuras();
        sSpellMgr->LoadSpellAreas();

        LootTemplates_Creature.ResetConditions();      LoadLootTemplates_Creature();      LootTemplates_Creature.CheckLootRefs();
        LootTemplates_Fishing.ResetConditions();       LoadLootTemplates_Fishing();
        LootTemplates_Gameobject.ResetConditions();    LoadLootTemplates_Gameobject();    LootTemplates_Gameobject.CheckLootRefs();
        LootTemplates_Skinning.ResetConditions();      LoadLootTemplates_Skinning();      LootTemplates_Skinning.CheckLootRefs();
        LootTemplates_Pickpocketing.ResetConditions(); LoadLootTemplates_Pickpocketing(); LootTemplates_Pickpocketing.CheckLootRefs();
        LootTemplates_Mail.ResetConditions();          LoadLootTemplates_Mail();          LootTemplates_Mail.CheckLootRefs();
        LootTemplates_Disenchant.ResetConditions();    LoadLootTemplates_Disenchant();
        LootTemplates_Prospecting.ResetConditions();   LoadLootTemplates_Prospecting();
        LootTemplates_Milling.ResetConditions();       LoadLootTemplates_Milling();

        handler->SendGlobalGMSysMessage(
            "[live-reload] Done. Use '.rlive creature <entry>' or '.rlive gobject <entry>' "
            "to also respawn live world instances.");

        return true;
    }
};

void AddSC_mod_live_reload()
{
    new mod_live_reload_commandscript();
}

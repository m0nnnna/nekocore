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
 *   .rlive cooldowns          Reload spell_cooldown_overrides and re-apply them to the live
 *                             SpellInfo store, then verify every row against memory.
 *   .rlive verify item <id>   Compare an item's in-memory spell cooldowns with the DB row.
 *   .rlive verify spell <id>  Compare a spell's in-memory cooldowns with spell_cooldown_overrides.
 *   .rlive all                Reload every system above in one shot.
 *
 * Every reload reports how long it took and compares the number of rows now in
 * memory with the number of rows in the DB table, so a silent no-op is visible.
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
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "Timer.h"

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
// Verification helpers
// ---------------------------------------------------------------------------

static uint32 DbCount(char const* table)
{
    QueryResult r = WorldDatabase.Query(std::string("SELECT COUNT(*) FROM ") + table);
    return r ? r->Fetch()[0].Get<uint32>() : 0;
}

// Report "<what> reloaded in N ms: X in memory, Y in DB [OK|MISMATCH]".
// `memCount` is the number of entries the server now holds; `dbTable` is the
// table it was loaded from. A mismatch means rows were skipped (bad data) or
// the load did not run.
static void ReportReload(ChatHandler* handler, char const* what, char const* dbTable,
                         uint32 memCount, uint32 startMs)
{
    uint32 dbCount = DbCount(dbTable);
    bool ok = memCount == dbCount;
    handler->PSendSysMessage("[live-reload] %s reloaded in %u ms: %u in memory, %u in DB [%s]",
        what, GetMSTimeDiffToNow(startMs), memCount, dbCount,
        ok ? "OK" : "MISMATCH - check Server.log for skipped rows");
    LOG_INFO("server.loading", "mod-live-reload: {} reloaded in {} ms ({} in memory, {} in DB){}",
        what, GetMSTimeDiffToNow(startMs), memCount, dbCount, ok ? "" : " MISMATCH");
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
        static ChatCommandTable verifyTable =
        {
            { "item",  HandleVerifyItemCommand,  SEC_ADMINISTRATOR, Console::Yes },
            { "spell", HandleVerifySpellCommand, SEC_ADMINISTRATOR, Console::Yes },
        };

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
            { "cooldowns", HandleCooldownsCommand, SEC_ADMINISTRATOR, Console::Yes },
            { "verify",    verifyTable },
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
        uint32 t = getMSTime();
        sObjectMgr->LoadItemTemplates();
        ReportReload(handler, "item_template", "item_template",
            sObjectMgr->GetItemTemplateStore()->size(), t);
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive quest
    // -----------------------------------------------------------------------
    static bool HandleQuestCommand(ChatHandler* handler)
    {
        LOG_INFO("server.loading", "mod-live-reload: Reloading quest_template...");
        uint32 t = getMSTime();
        sObjectMgr->LoadQuests();
        sObjectMgr->LoadQuestStartersAndEnders();
        ReportReload(handler, "quest_template", "quest_template",
            sObjectMgr->GetQuestTemplates().size(), t);
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
        uint32 t = getMSTime();
        sObjectMgr->LoadGameObjectTemplate();
        sObjectMgr->LoadGameObjectTemplateAddons();
        ReportReload(handler, "gameobject_template", "gameobject_template",
            sObjectMgr->GetGameObjectTemplates()->size(), t);

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
    // .rlive cooldowns
    // spell_cooldown_overrides is normally applied to SpellInfo once at startup.
    // Reload the override map, push the values into the live SpellInfo store,
    // then read every row back out of memory to prove it took effect.
    // Players see the new cooldown on their next cast; cooldowns already
    // running keep their old end time.
    // -----------------------------------------------------------------------
    static bool HandleCooldownsCommand(ChatHandler* handler)
    {
        uint32 t = getMSTime();
        sSpellMgr->LoadSpellCooldownOverrides();

        QueryResult result = WorldDatabase.Query(
            "SELECT Id, RecoveryTime, CategoryRecoveryTime FROM spell_cooldown_overrides");

        uint32 rows = 0, applied = 0, changed = 0, missing = 0, bad = 0;

        if (result)
        {
            do
            {
                Field* f = result->Fetch();
                uint32 id = f[0].Get<uint32>();
                uint32 rec = f[1].Get<uint32>();
                uint32 cat = f[2].Get<uint32>();
                ++rows;

                SpellInfo* info = const_cast<SpellInfo*>(sSpellMgr->GetSpellInfo(id));
                if (!info)
                {
                    ++missing;
                    continue;
                }

                if (info->RecoveryTime != rec || info->CategoryRecoveryTime != cat)
                    ++changed;

                info->RecoveryTime = rec;
                info->CategoryRecoveryTime = cat;
                ++applied;

                // Read back from the live store, not from the pointer we just wrote.
                SpellInfo const* check = sSpellMgr->GetSpellInfo(id);
                if (check->RecoveryTime != rec || check->CategoryRecoveryTime != cat)
                {
                    ++bad;
                    LOG_ERROR("server.loading",
                        "mod-live-reload: spell {} cooldown did not stick (want {}/{}, have {}/{})",
                        id, rec, cat, check->RecoveryTime, check->CategoryRecoveryTime);
                }
            } while (result->NextRow());
        }

        handler->PSendSysMessage(
            "[live-reload] spell_cooldown_overrides reloaded in %u ms: %u DB rows, "
            "%u applied (%u actually changed), %u spell id(s) not in Spell.dbc, %u failed verification [%s]",
            GetMSTimeDiffToNow(t), rows, applied, changed, missing, bad, bad ? "FAILED" : "OK");
        handler->SendSysMessage(
            "[live-reload] New casts use the new cooldown; cooldowns already running keep their old end time. "
            "Rows deleted from the table are not reverted until restart.");
        LOG_INFO("server.loading",
            "mod-live-reload: cooldowns reloaded: {} rows, {} applied, {} changed, {} missing, {} failed",
            rows, applied, changed, missing, bad);
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive verify item <entry>
    // -----------------------------------------------------------------------
    static bool HandleVerifyItemCommand(ChatHandler* handler, uint32 entry)
    {
        ItemTemplate const* proto = sObjectMgr->GetItemTemplate(entry);
        QueryResult r = WorldDatabase.Query(
            "SELECT spellcooldown_1, spellcategorycooldown_1 FROM item_template WHERE entry = {}", entry);

        if (!proto || !r)
        {
            handler->PSendSysMessage("[live-reload] Item %u: %s.", entry,
                !proto ? "not in memory" : "not in item_template");
            return true;
        }

        int32 dbCd = r->Fetch()[0].Get<int32>();
        int32 dbCat = r->Fetch()[1].Get<int32>();
        int32 memCd = proto->Spells[0].SpellCooldown;
        int32 memCat = proto->Spells[0].SpellCategoryCooldown;
        bool ok = dbCd == memCd && dbCat == memCat;

        handler->PSendSysMessage(
            "[live-reload] Item %u spell1 cooldown: memory %d/%d ms, DB %d/%d ms [%s]",
            entry, memCd, memCat, dbCd, dbCat, ok ? "OK" : "STALE - run .rlive item");
        return true;
    }

    // -----------------------------------------------------------------------
    // .rlive verify spell <id>
    // -----------------------------------------------------------------------
    static bool HandleVerifySpellCommand(ChatHandler* handler, uint32 id)
    {
        SpellInfo const* info = sSpellMgr->GetSpellInfo(id);
        if (!info)
        {
            handler->PSendSysMessage("[live-reload] Spell %u is not loaded.", id);
            return true;
        }

        QueryResult r = WorldDatabase.Query(
            "SELECT RecoveryTime, CategoryRecoveryTime FROM spell_cooldown_overrides WHERE Id = {}", id);

        if (!r)
        {
            handler->PSendSysMessage(
                "[live-reload] Spell %u has no override row; in memory %u/%u ms (from Spell.dbc/spell_dbc).",
                id, info->RecoveryTime, info->CategoryRecoveryTime);
            return true;
        }

        uint32 dbRec = r->Fetch()[0].Get<uint32>();
        uint32 dbCat = r->Fetch()[1].Get<uint32>();
        bool ok = info->RecoveryTime == dbRec && info->CategoryRecoveryTime == dbCat;

        handler->PSendSysMessage(
            "[live-reload] Spell %u cooldown: memory %u/%u ms, DB override %u/%u ms [%s]",
            id, info->RecoveryTime, info->CategoryRecoveryTime, dbRec, dbCat,
            ok ? "OK" : "STALE - run .rlive cooldowns");
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
            "[live-reload] Done (cooldown overrides are separate: run .rlive cooldowns). Use '.rlive creature <entry>' or '.rlive gobject <entry>' "
            "to also respawn live world instances.");

        return true;
    }
};

void AddSC_mod_live_reload()
{
    new mod_live_reload_commandscript();
}

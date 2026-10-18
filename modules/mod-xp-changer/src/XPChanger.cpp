/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 *
 * Era-aware baseline added on top of the original personal slider (see
 * nekocore's own README for the "right XP rate per era" reasoning this
 * came out of). Previously "1.0x Normal" always meant the same flat
 * multiplier regardless of what content the player was actually in --
 * now it means "your current era's own baseline", and the personal
 * slider (0.2x-2.0x) multiplies on top of THAT instead of on top of a
 * flat 1.0.
 *
 * Era is read via mod-individual-progression's own
 * hasPassedProgression/isBeforeProgression against PROGRESSION_PRE_TBC
 * (Vanilla->TBC boundary) and PROGRESSION_TBC_TIER_5 ("WotLK Naxx/EoE/OS",
 * the point the module's own enum comments mark as the start of WotLK
 * content) -- the exact same two boundaries EraTalentGate.cpp and
 * EraProgressionSync.cpp already key off, so a character's "era" here
 * always agrees with what those already decided for talents. Cross-module
 * include of IndividualProgression.h works the same way
 * AutoBalanceManaBurnFix.cpp already includes ABCreatureInfo.h from a
 * different module -- confirmed supported by modules/CMakeLists.txt's
 * shared include paths, not a hack.
 *
 * Per-era baseline values are deliberately NOT hardcoded here: there's no
 * verified historical "Vanilla was Nx slower" number to encode (Blizzard's
 * only documented catch-up-era XP change was to quest REWARD VALUES,
 * already corrected by mod-individual-progression's own QuestXPFix/
 * custom_quest_xp -- the base creature-kill XP formula was never
 * similarly boosted, so there's no analogous "authentic" ratio to derive
 * for it). So these are exposed as plain config
 * (Nekocore.EraXPRate.Vanilla/TBC/WotLK in nekocore.conf.dist, all
 * default 1.0 -- a no-op until deliberately tuned) rather than baked-in
 * "researched" constants -- the actual numbers are a tuning call for
 * whoever runs this realm to make and adjust live, not something to
 * invent here.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Chat.h"
#include "GossipDef.h"
#include "ScriptedGossip.h"
#include "DatabaseEnv.h"
#include "Config.h"
#include <unordered_map>

#include "IndividualProgression.h"

static std::unordered_map<uint32, float> playerXPRates;

namespace
{
    float EraXPRateVanilla = 1.0f;
    float EraXPRateTBC     = 1.0f;
    float EraXPRateWotLK   = 1.0f;

    void LoadEraXPRateConfig()
    {
        EraXPRateVanilla = sConfigMgr->GetOption<float>("Nekocore.EraXPRate.Vanilla", 1.0f);
        EraXPRateTBC     = sConfigMgr->GetOption<float>("Nekocore.EraXPRate.TBC", 1.0f);
        EraXPRateWotLK   = sConfigMgr->GetOption<float>("Nekocore.EraXPRate.WotLK", 1.0f);
    }

    // Same two boundaries EraTalentGate.cpp/EraProgressionSync.cpp already
    // use -- kept in sync with those on purpose, not re-derived.
    char const* CurrentEraLabel(Player* player)
    {
        if (sIndividualProgression->isBeforeProgression(player, PROGRESSION_PRE_TBC))
            return "Vanilla";
        if (sIndividualProgression->isBeforeProgression(player, PROGRESSION_TBC_TIER_5))
            return "TBC";
        return "WotLK";
    }

    float EraBaselineRate(Player* player)
    {
        if (!sIndividualProgression->enabled)
            return 1.0f; // progression tracking off -- no era concept to key off, stay neutral

        if (sIndividualProgression->isBeforeProgression(player, PROGRESSION_PRE_TBC))
            return EraXPRateVanilla;
        if (sIndividualProgression->isBeforeProgression(player, PROGRESSION_TBC_TIER_5))
            return EraXPRateTBC;
        return EraXPRateWotLK;
    }
}

enum XPRateAction
{
    XP_ACTION_02 = 1,
    XP_ACTION_05 = 2,
    XP_ACTION_07 = 3,
    XP_ACTION_10 = 4,
    XP_ACTION_15 = 5,
    XP_ACTION_20 = 6,
};

class XPChanger_WorldScript : public WorldScript
{
public:
    XPChanger_WorldScript() : WorldScript("XPChanger_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        LoadEraXPRateConfig();
    }
};

class XPChangerNPC : public CreatureScript
{
public:
    XPChangerNPC() : CreatureScript("npc_xp_changer") { }

    bool OnGossipHello(Player* player, Creature* creature) override
    {
        player->PlayerTalkClass->ClearMenus();

        float personalRate = 1.0f;
        auto it = playerXPRates.find(player->GetGUID().GetCounter());
        if (it != playerXPRates.end())
            personalRate = it->second;

        char const* eraLabel = CurrentEraLabel(player);
        float eraRate = EraBaselineRate(player);

        ChatHandler(player->GetSession()).PSendSysMessage(
            "Your era: %s (era baseline %.2fx). Personal preference: %.1fx. Effective rate: %.2fx",
            eraLabel, eraRate, personalRate, eraRate * personalRate);

        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "0.2x - Slowpoke (20%)",             GOSSIP_SENDER_MAIN, XP_ACTION_02);
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "0.5x - Taking it easy (50%)",       GOSSIP_SENDER_MAIN, XP_ACTION_05);
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "0.7x - Steady pace (70%)",          GOSSIP_SENDER_MAIN, XP_ACTION_07);
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "1.0x - Normal (your era baseline)", GOSSIP_SENDER_MAIN, XP_ACTION_10);
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "1.5x - Fast learner (150%)",        GOSSIP_SENDER_MAIN, XP_ACTION_15);
        AddGossipItemFor(player, GOSSIP_ICON_CHAT, "2.0x - Speed run (200%)",           GOSSIP_SENDER_MAIN, XP_ACTION_20);

        SendGossipMenuFor(player, 68, creature->GetGUID());
        return true;
    }

    bool OnGossipSelect(Player* player, Creature* /*creature*/, uint32 /*sender*/, uint32 action) override
    {
        CloseGossipMenuFor(player);

        float rate;
        const char* rateName;

        switch (action)
        {
            case XP_ACTION_02: rate = 0.2f; rateName = "0.2x (20%)";    break;
            case XP_ACTION_05: rate = 0.5f; rateName = "0.5x (50%)";    break;
            case XP_ACTION_07: rate = 0.7f; rateName = "0.7x (70%)";    break;
            case XP_ACTION_10: rate = 1.0f; rateName = "1.0x (Normal)"; break;
            case XP_ACTION_15: rate = 1.5f; rateName = "1.5x (150%)";   break;
            case XP_ACTION_20: rate = 2.0f; rateName = "2.0x (200%)";   break;
            default: return true;
        }

        uint32 guid = player->GetGUID().GetCounter();
        playerXPRates[guid] = rate;

        CharacterDatabase.Execute("REPLACE INTO character_xp_rate (guid, rate) VALUES ({}, {})", guid, rate);

        ChatHandler(player->GetSession()).PSendSysMessage("XP rate set to %s.", rateName);
        return true;
    }
};

class XPChangerPlayerScript : public PlayerScript
{
public:
    XPChangerPlayerScript() : PlayerScript("XPChangerPlayerScript") { }

    void OnPlayerLogin(Player* player) override
    {
        uint32 guid = player->GetGUID().GetCounter();
        QueryResult result = CharacterDatabase.Query("SELECT rate FROM character_xp_rate WHERE guid = {}", guid);
        if (result)
        {
            Field* fields = result->Fetch();
            playerXPRates[guid] = fields[0].Get<float>();
        }
    }

    void OnPlayerLogout(Player* player) override
    {
        playerXPRates.erase(player->GetGUID().GetCounter());
    }

    void OnPlayerGiveXP(Player* player, uint32& amount, Unit* /*victim*/, uint8 /*xpSource*/) override
    {
        float personalRate = 1.0f;
        auto it = playerXPRates.find(player->GetGUID().GetCounter());
        if (it != playerXPRates.end())
            personalRate = it->second;

        float multiplier = personalRate * EraBaselineRate(player);
        if (multiplier != 1.0f)
            amount = uint32(float(amount) * multiplier);
    }
};

void AddXPChangerScripts()
{
    new XPChanger_WorldScript();
    new XPChangerNPC();
    new XPChangerPlayerScript();
}

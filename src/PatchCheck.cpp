/*
 * Tells players when their NekoCore client patch is out of date.
 *
 * The patch carries the NekoPatchCheck addon, whose Version.lua holds the
 * version install_client.py stamped on it (a hash of the MPQ and addons).
 * The same build writes data/generated/patch-version.txt, which the
 * override bind-mounts at Nekocore.PatchVersionFile. On login the addon
 * whispers itself "NEKOPATCH" "HELLO <version>"; this swallows that
 * whisper and answers "OK" or "OUTDATED <realm's version>", and the addon
 * shows a popup for the latter.
 *
 * A client that never says hello has no patch, or one older than the
 * check itself (Drop 7 and before) -- those players are told once per
 * login where to get it. No patch-version.txt turns the whole check off.
 *
 * The file is read at startup and on `.reload config`, so a patch shipped
 * without a worldserver change only needs that reload.
 */

#include "Chat.h"
#include "Config.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "WorldPacket.h"

#include <cctype>
#include <fstream>
#include <unordered_set>

namespace
{
    constexpr char const* PREFIX = "NEKOPATCH";
    constexpr Milliseconds HELLO_GRACE = 60s;

    std::string expectedVersion;
    std::unordered_set<ObjectGuid::LowType> saidHello;

    void LoadExpectedVersion()
    {
        std::string const path = sConfigMgr->GetOption<std::string>(
            "Nekocore.PatchVersionFile", "/azerothcore/nekocore/patch-version.txt");

        expectedVersion.clear();
        std::ifstream in(path);
        if (in)
            std::getline(in, expectedVersion);
        while (!expectedVersion.empty() && std::isspace(static_cast<unsigned char>(expectedVersion.back())))
            expectedVersion.pop_back();

        if (expectedVersion.empty())
            LOG_INFO("module.nekocore", ">> Patch check: no {} -- players are not told about outdated patches", path);
        else
            LOG_INFO("module.nekocore", ">> Patch check: realm expects client patch {}", expectedVersion);
    }

    void SendAddonWhisper(Player* player, std::string const& body)
    {
        WorldPacket data;
        ChatHandler::BuildChatPacket(data, CHAT_MSG_WHISPER, LANG_ADDON, player, player, std::string(PREFIX) + '\t' + body);
        player->SendDirectMessage(&data);
    }
}

class PatchCheck_World : public WorldScript
{
public:
    PatchCheck_World() : WorldScript("PatchCheck_World", { WORLDHOOK_ON_AFTER_CONFIG_LOAD }) { }

    void OnAfterConfigLoad(bool /*reload*/) override
    {
        LoadExpectedVersion();
    }
};

class PatchCheck_Player : public PlayerScript
{
public:
    PatchCheck_Player() : PlayerScript("PatchCheck_Player", {
        PLAYERHOOK_ON_LOGIN, PLAYERHOOK_ON_LOGOUT, PLAYERHOOK_CAN_PLAYER_USE_PRIVATE_CHAT }) { }

    void OnPlayerLogin(Player* player) override
    {
        if (expectedVersion.empty())
            return;

        ObjectGuid::LowType const guid = player->GetGUID().GetCounter();
        saidHello.erase(guid);
        // The player's own event queue: it dies with the Player, so the
        // pointer cannot outlive it.
        player->m_Events.AddEventAtOffset([player, guid]
        {
            if (expectedVersion.empty() || saidHello.count(guid))
                return;
            ChatHandler(player->GetSession()).SendSysMessage(
                "|cffff8000[NekoCore]|r Your client patch could not be detected, so spells and talents may not "
                "match the realm. Get the NekoCore Launcher from the website: it installs and updates the patch.");
        }, HELLO_GRACE);
    }

    void OnPlayerLogout(Player* player) override
    {
        saidHello.erase(player->GetGUID().GetCounter());
    }

    bool OnPlayerCanUseChat(Player* player, uint32 /*type*/, uint32 language, std::string& msg, Player* receiver) override
    {
        if (language != LANG_ADDON || receiver != player)
            return true;

        std::string const hello = std::string(PREFIX) + "\tHELLO ";
        if (msg.compare(0, hello.size(), hello) != 0)
            return true;

        saidHello.insert(player->GetGUID().GetCounter());
        if (expectedVersion.empty())
            return false;

        std::string const theirs = msg.substr(hello.size());
        if (theirs == expectedVersion)
            SendAddonWhisper(player, "OK");
        else
        {
            SendAddonWhisper(player, "OUTDATED " + expectedVersion);
            LOG_INFO("module.nekocore", "Patch check: {} has client patch {}, realm expects {}",
                player->GetName(), theirs, expectedVersion);
        }
        return false;
    }
};

void AddSC_nekocore_patch_check()
{
    new PatchCheck_World();
    new PatchCheck_Player();
}

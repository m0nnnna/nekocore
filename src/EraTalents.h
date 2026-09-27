/*
 * Shared era-talent definitions for EraTalentGate.cpp / EraTalentInfoRemap.cpp.
 *
 * Tab id ranges must stay in sync with tools/build_patch/build_era_tree.py's
 * ERA_CONFIG (tab_base 8000/9000 + class_id*10 + tree_index for Vanilla/TBC).
 * Talent id ranges likewise mirror its id_offset (classic id + 10000 for
 * Vanilla, + 20000 for TBC); stock WotLK talents are all far below 10000.
 */
#pragma once

#include "Define.h"
#include "Player.h"

#include "IndividualProgression.h"

namespace NekoEraTalents
{
    constexpr uint32 VANILLA_TAB_ID_MIN = 8000;
    constexpr uint32 VANILLA_TAB_ID_MAX = 8999;
    constexpr uint32 TBC_TAB_ID_MIN = 9000;
    constexpr uint32 TBC_TAB_ID_MAX = 9999;

    enum Era : uint8
    {
        ERA_WOTLK = 0,
        ERA_VANILLA = 1,
        ERA_TBC = 2,
        ERA_COUNT = 3,
    };

    inline Era EraOfTab(uint32 tabId)
    {
        if (tabId >= VANILLA_TAB_ID_MIN && tabId <= VANILLA_TAB_ID_MAX)
            return ERA_VANILLA;
        if (tabId >= TBC_TAB_ID_MIN && tabId <= TBC_TAB_ID_MAX)
            return ERA_TBC;
        return ERA_WOTLK;
    }

    // The era whose talent tabs this character is currently entitled to,
    // per mod-individual-progression. Same boundaries EraTalentGate.cpp
    // enforces and NekoTalentUI.lua's DetectEra() displays: Vanilla until
    // PRE_TBC is reached, TBC until TBC_TIER_5 (the first WotLK content),
    // WotLK after that.
    //
    // Deliberately NOT sIndividualProgression->isBeforeProgression(): that
    // (and GetPlayerProgressionFromQuests, which it wraps) returns a fixed
    // answer whenever !player->IsInWorld(), and the login-time
    // SMSG_TALENTS_INFO goes out from SendInitialPacketsBeforeAddToMap,
    // i.e. before the player is in world. Quest status is already loaded
    // by then, so read the same rewarded-quest state directly (66000 +
    // ProgressionState, exactly what that module's own
    // GetPlayerProgressionFromQuests scans).
    inline Era EraOfPlayer(Player const* player)
    {
        constexpr uint32 PROGRESSION_QUEST_BASE = 66000;
        auto reached = [&](ProgressionState state)
        {
            return player->GetQuestStatus(PROGRESSION_QUEST_BASE + state) == QUEST_STATUS_REWARDED;
        };
        // Any state at or past the boundary counts as having crossed it --
        // mod-individual-progression rewards each state's quest as it is
        // reached, so scanning upward mirrors its own "highest rewarded"
        // logic without assuming every intermediate quest is present.
        for (uint8 s = PROGRESSION_TBC_TIER_5; s <= PROGRESSION_WOTLK_TIER_5; ++s)
            if (reached(static_cast<ProgressionState>(s)))
                return ERA_WOTLK;
        for (uint8 s = PROGRESSION_PRE_TBC; s < PROGRESSION_TBC_TIER_5; ++s)
            if (reached(static_cast<ProgressionState>(s)))
                return ERA_TBC;
        return ERA_VANILLA;
    }
}

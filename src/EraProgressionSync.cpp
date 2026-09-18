/*
 * Auto-resets a character's talents the moment mod-individual-progression
 * carries them across an era boundary this repo cares about (Vanilla ->
 * TBC, TBC -> WotLK) -- otherwise a character would keep whatever points
 * they'd sunk into the era they just left (which EraTalentGate.cpp now
 * locks them out of re-spending, but doesn't retroactively refund), and
 * have no points free to spend in the era they just unlocked.
 *
 * No 1:1 remapping of old points onto the new era's tree is attempted --
 * that's not generally even possible (different trees, different talent
 * counts/prereqs across eras) and isn't what a real Blizzard expansion
 * launch did either: a full free respec, same as this.
 *
 * Detecting the crossing: mod-individual-progression tracks a character's
 * progression state entirely via hidden REWARDED QUESTS (id 66000 + state,
 * see IndividualProgression.cpp's GetPlayerProgressionFromQuests/
 * UpdateProgressionState/ForceUpdateProgressionState -- confirmed by
 * reading that module's actual source, not assumed; there is no separate
 * "progression changed" signal it fires for other modules to hook). So
 * rather than forking that module to add one, this hooks the standard
 * PlayerScript::OnPlayerCompleteQuest (fired from Player::RewardQuest,
 * confirmed via the actual call site in PlayerQuest.cpp) and checks for
 * the two specific quest ids that correspond to the boundaries we care
 * about -- PROGRESSION_PRE_TBC (Vanilla -> TBC) and PROGRESSION_TBC_TIER_5
 * (TBC -> WotLK, the point the module's own enum comments mark as "WotLK
 * Naxx, EoE, OS" -- the first WotLK content unlocking). Every other
 * progression-quest reward (there are 19, one per ProgressionState value)
 * is ignored.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "QuestDef.h"
#include "Chat.h"

#include "IndividualProgression.h"

namespace
{
    constexpr uint32 PROGRESSION_QUEST_BASE = 66000;

    void ResetTalentsForEraChange(Player* player, char const* newEraLabel)
    {
        player->resetTalents(true); // true = no gold cost -- this is a forced transition, not the player's own choice to respec
        ChatHandler(player->GetSession()).PSendSysMessage(
            "|cff00ff00[Era Talents]|r Your character has reached the %s era -- "
            "your talents have been reset. Press N to choose your new talents.",
            newEraLabel);
    }
}

class EraProgressionSync : public PlayerScript
{
public:
    EraProgressionSync() : PlayerScript("EraProgressionSync") { }

    void OnPlayerCompleteQuest(Player* player, Quest const* quest) override
    {
        if (!player || !quest)
            return;

        uint32 questId = quest->GetQuestId();
        if (questId == PROGRESSION_QUEST_BASE + PROGRESSION_PRE_TBC)
            ResetTalentsForEraChange(player, "TBC");
        else if (questId == PROGRESSION_QUEST_BASE + PROGRESSION_TBC_TIER_5)
            ResetTalentsForEraChange(player, "WotLK");
    }
};

void AddSC_era_progression_sync()
{
    new EraProgressionSync();
}

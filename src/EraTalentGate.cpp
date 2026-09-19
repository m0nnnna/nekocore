/*
 * Era-lock enforcement for the dedicated era talent tabs build_era_tree.py
 * builds (tools/build_patch/build_era_tree.py -- see that file's doc
 * comment for the full tab-id allocation scheme).
 *
 * Without this, nothing stops a character from spending points in an era's
 * tabs regardless of their actual mod-individual-progression state -- the
 * custom client UI (NekoTalentUI) only controls what's easy to reach, not
 * what's actually possible, and a determined player could still send
 * CMSG_LEARN_TALENT directly (e.g. via a macro/addon) for any talent id
 * whose tab exists in the client's Talent.dbc, regardless of era.
 *
 * Hook point: ServerScript::CanPacketReceive, which AzerothCore calls
 * BEFORE the opcode's real handler runs (WorldSession.cpp) -- confirmed by
 * reading the actual call sites, not assumed. The packet object passed in
 * is documented (ServerScript.h) as a COPY of the original, so reading it
 * here doesn't disturb what HandleLearnTalentOpcode reads afterward -- no
 * rpos() save/restore needed, unlike a typical packet-peek pattern.
 * Current core's signature takes it as `WorldPacket const&` (changed at
 * some point after this repo's original core reference -- confirmed
 * against this exact checkout's ServerScript.h, not assumed), so reading
 * still needs a local mutable copy first (operator>> mutates read position).
 *
 * No core patch needed for this feature: this hook already exists in
 * stock AzerothCore, exactly as nekocore's own original README predicted
 * ("AzerothCore supports this without patching core source -- confirm the
 * exact hook point against its source before relying on it") before this
 * was actually verified against the real source.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "WorldSession.h"
#include "WorldPacket.h"
#include "Opcodes.h"
#include "DBCStores.h"
#include "Chat.h"
#include "Language.h"

#include "IndividualProgression.h"

namespace
{
    // Dedicated era-tab id ranges -- must stay in sync with
    // tools/build_patch/build_era_tree.py's ERA_CONFIG (tab_base 8000/9000
    // + class_id*10 + tree_index for Vanilla/TBC respectively -- Vanilla
    // deliberately sits BELOW TBC numerically now; see that script's
    // ERA_CONFIG comment for why the order matters, not just the ranges).
    constexpr uint32 VANILLA_TAB_ID_MIN = 8000;
    constexpr uint32 VANILLA_TAB_ID_MAX = 8999;
    constexpr uint32 TBC_TAB_ID_MIN = 9000;
    constexpr uint32 TBC_TAB_ID_MAX = 9999;
}

namespace
{
    // Shared by both opcode paths below. Returns true if `player` is allowed
    // to spend a point in `talentId` right now; sends the era-mismatch chat
    // message itself before returning false, same message either opcode
    // would have produced.
    bool IsTalentAllowed(Player* player, WorldSession* session, uint32 talentId)
    {
        TalentEntry const* talentInfo = sTalentStore.LookupEntry(talentId);
        if (!talentInfo)
            return true; // unknown id -- let the real handler's own validation reject it

        if (talentInfo->TalentTab >= VANILLA_TAB_ID_MIN && talentInfo->TalentTab <= VANILLA_TAB_ID_MAX)
        {
            if (sIndividualProgression->isBeforeProgression(player, PROGRESSION_PRE_TBC))
                return true; // still Vanilla-era per their own progression -- allowed

            ChatHandler(session).PSendSysMessage(
                "|cffff0000[Era Talents]|r That talent belongs to the Vanilla era -- your character has already progressed past it.");
            return false;
        }

        if (talentInfo->TalentTab >= TBC_TAB_ID_MIN && talentInfo->TalentTab <= TBC_TAB_ID_MAX)
        {
            // TBC talents are only learnable during the TBC window: after
            // leaving Vanilla (PRE_TBC reached) and before reaching WotLK
            // content (TBC_TIER_5 -- "WotLK Naxx/EoE/OS", the point that
            // ends the TBC tier progression per the module's own enum
            // comments). Same reasoning as the Vanilla gate above, just
            // bounded on both sides instead of one.
            bool inTbcWindow = sIndividualProgression->hasPassedProgression(player, PROGRESSION_PRE_TBC)
                && sIndividualProgression->isBeforeProgression(player, PROGRESSION_TBC_TIER_5);
            if (inTbcWindow)
                return true;

            ChatHandler(session).PSendSysMessage(
                "|cffff0000[Era Talents]|r That talent belongs to the TBC era -- it's not available to your character right now.");
            return false;
        }

        return true; // not one of our era tabs, nothing to gate
    }
}

class EraTalentGate : public ServerScript
{
public:
    EraTalentGate() : ServerScript("EraTalentGate") { }

    bool CanPacketReceive(WorldSession* session, WorldPacket const& packet) override
    {
        Player* player = session ? session->GetPlayer() : nullptr;
        if (!player)
            return true;

        if (packet.GetOpcode() == CMSG_LEARN_TALENT)
        {
            WorldPacket local(packet); // operator>> mutates read position -- can't read from a const&
            uint32 talentId, requestedRank;
            local >> talentId >> requestedRank;
            return IsTalentAllowed(player, session, talentId);
        }

        // WotLK's "preview talents" commit path -- the client queues one or
        // more selections locally, then sends them ALL in a single packet
        // here instead of one CMSG_LEARN_TALENT per point. Live-confirmed
        // this is genuinely what a plain (non-shift, single-point) click
        // sends too, not just an explicit multi-select preview: the
        // CMSG_LEARN_TALENT-only check above let a Vanilla-progression
        // character (Progression Level 0, confirmed via `.ip get`) spend
        // points in a TBC-range tab with zero rejection message, because
        // this opcode was never being inspected at all. Packet layout
        // confirmed against HandleLearnPreviewTalents's own read order
        // (SkillHandler.cpp): count, then that many (talentId, rank) pairs.
        // Rejecting the whole batch if ANY entry fails era gating -- the
        // same all-or-nothing shape CanPacketReceive already forces on a
        // single-talent request, and simplest to reason about correctly.
        if (packet.GetOpcode() == CMSG_LEARN_PREVIEW_TALENTS)
        {
            WorldPacket local(packet);
            uint32 talentsCount;
            local >> talentsCount;

            uint32 const MaxTalentsCount = 150; // matches HandleLearnPreviewTalents's own cap
            for (uint32 i = 0; i < talentsCount && i < MaxTalentsCount; ++i)
            {
                uint32 talentId, requestedRank;
                local >> talentId >> requestedRank;
                if (!IsTalentAllowed(player, session, talentId))
                    return false;
            }
            return true;
        }

        return true;
    }
};

void AddSC_era_talent_gate()
{
    new EraTalentGate();
}

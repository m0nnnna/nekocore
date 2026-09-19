/*
 * Fixes the "spend a point in a Vanilla tab, it shows up in the TBC tab"
 * bug (docs/era-talent-wrong-tab-bug.md) at its actual source, which is
 * server-side, not the client's LearnTalent as that doc first assumed.
 *
 * Mechanism: build_era_tree.py reuses each era's REAL spell ids (a talent
 * is only ported if its rank spells already exist in WotLK's Spell.dbc),
 * so the stock WotLK, Vanilla and TBC copies of e.g. Malice all point at
 * the same spell 14162. The core, however, only knows a character's
 * talents by SPELL id (PlayerTalentMap / character_talent.spell) and
 * translates back to a Talent.dbc id through sTalentSpellPosMap, which
 * DBCStores.cpp fills last-writer-wins in talent-ID order:
 *
 *     sTalentSpellPosMap[talentInfo->RankID[j]] = TalentSpellPos(talentInfo->TalentID, j);
 *
 * TBC talent ids (classic + 20000) are the highest, so every shared spell
 * resolves to its TBC twin. Player::BuildPlayerTalentsInfoData (the body
 * of SMSG_TALENTS_INFO and SMSG_INSPECT_TALENT) walks the spell map and
 * emits that twin's id -- so the client is TOLD its Vanilla (or stock
 * WotLK) point lives in the TBC tab, and faithfully draws it there. The
 * client sent the right id; the learn itself was correct; only the
 * report back is wrong. (Verified against data/generated/Talent.dbc:
 * 314 of 319 Vanilla talents share at least one rank spell with a TBC or
 * stock talent.)
 *
 * Fix: rewrite the (talentId, rank) pairs in those two packets, in place,
 * to the same-spell talent in the tab block the character's era actually
 * owns. Hook point is ServerScript::CanPacketSend, which WorldSession::
 * SendPacket calls with a const& to the REAL packet immediately before
 * handing it to the socket (WorldSession.cpp -- confirmed at the call
 * site, not assumed). Both packets are built fresh per recipient, never
 * shared, and every rewrite is same-size (uint32 + uint8 over the same
 * bytes), so a const_cast + put() is safe and avoids re-entering
 * SendPacket with a replacement packet.
 *
 * Nothing else in the core needs the talent id to be era-correct: the
 * other GetTalentSpellPos() callers (_LoadTalents, addTalent,
 * ActivateSpec) only use it for null-ness and the rank, and the rank of a
 * shared spell is the same across its twins. The remap is display-side
 * only, which is also why it needs no core patch.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "ObjectAccessor.h"
#include "WorldSession.h"
#include "WorldPacket.h"
#include "Opcodes.h"
#include "DBCStores.h"

#include "EraTalents.h"

#include <array>
#include <unordered_map>

namespace
{
    using namespace NekoEraTalents;

    struct TalentRank
    {
        uint32 talentId;
        uint8 rank;
    };

    // spell id -> (talent id, rank) for each era's own tab block. Built
    // once from sTalentStore on first use (DBCs are fully loaded long
    // before any session exists).
    std::unordered_map<uint32, TalentRank> const& SpellToTalentForEra(Era era)
    {
        static std::array<std::unordered_map<uint32, TalentRank>, ERA_COUNT> maps;
        static bool built = false;
        if (!built)
        {
            for (TalentEntry const* talent : sTalentStore)
            {
                auto& map = maps[EraOfTab(talent->TalentTab)];
                for (uint8 rank = 0; rank < MAX_TALENT_RANK; ++rank)
                    if (talent->RankID[rank])
                        map[talent->RankID[rank]] = { talent->TalentID, rank };
            }
            built = true;
        }
        return maps[era];
    }

    // Rewrites one BuildPlayerTalentsInfoData() block starting at `pos`
    // (unspentTalentPoints onward). Layout, from Player.cpp:
    //   uint32 unspent, uint8 specsCount, uint8 activeSpec,
    //   per spec: uint8 talentCount, talentCount x (uint32 talentId, uint8 rank),
    //             uint8 glyphCount, glyphCount x uint16
    // Reads through a copy (operator>> mutates rpos) and writes through the
    // original. A packet shorter than the layout says throws
    // ByteBufferException from the read, before that entry's write -- the
    // caller catches it and sends the packet as-is.
    void RemapTalentsInfo(WorldPacket& out, std::size_t pos, Era era)
    {
        auto const& spellToTalent = SpellToTalentForEra(era);

        WorldPacket in(out);
        in.rpos(pos);
        uint32 unspent;
        uint8 specsCount, activeSpec;
        in >> unspent >> specsCount >> activeSpec;

        for (uint8 spec = 0; spec < specsCount; ++spec)
        {
            uint8 talentCount;
            in >> talentCount;
            for (uint8 i = 0; i < talentCount; ++i)
            {
                std::size_t entryPos = in.rpos();
                uint32 talentId;
                uint8 rank;
                in >> talentId >> rank;

                TalentEntry const* talent = sTalentStore.LookupEntry(talentId);
                if (!talent || rank >= MAX_TALENT_RANK || EraOfTab(talent->TalentTab) == era)
                    continue; // unknown, or already the right era's id

                auto itr = spellToTalent.find(talent->RankID[rank]);
                if (itr == spellToTalent.end())
                    continue; // this era's tree has no talent with that spell -- leave the server's answer alone

                out.put<uint32>(entryPos, itr->second.talentId);
                out.put<uint8>(entryPos + sizeof(uint32), itr->second.rank);
            }

            uint8 glyphCount;
            in >> glyphCount;
            in.read_skip(glyphCount * sizeof(uint16));
        }
    }
}

class EraTalentInfoRemap : public ServerScript
{
public:
    EraTalentInfoRemap() : ServerScript("EraTalentInfoRemap") { }

    bool CanPacketSend(WorldSession* session, WorldPacket const& packet) override
    {
        uint16 opcode = packet.GetOpcode();
        if (opcode != SMSG_TALENTS_INFO && opcode != SMSG_INSPECT_TALENT)
            return true;

        try
        {
            if (opcode == SMSG_TALENTS_INFO)
            {
                // uint8 isPet, then the player block. Pet talents aren't era-split.
                if (packet.read<uint8>(0) != 0)
                    return true;
                Player* player = session ? session->GetPlayer() : nullptr;
                if (!player)
                    return true;
                RemapTalentsInfo(const_cast<WorldPacket&>(packet), sizeof(uint8), EraOfPlayer(player));
            }
            else
            {
                // Packed guid of the INSPECTED player (MiscHandler.cpp), then
                // the same block -- the era that matters is theirs, not the
                // viewer's.
                WorldPacket in(packet);
                uint64 rawGuid;
                in.readPackGUID(rawGuid);
                Player* target = ObjectAccessor::FindPlayer(ObjectGuid(rawGuid));
                if (!target)
                    return true;
                RemapTalentsInfo(const_cast<WorldPacket&>(packet), in.rpos(), EraOfPlayer(target));
            }
        }
        catch (ByteBufferException const&)
        {
            // Malformed/short packet -- not ours to fix; send it untouched.
        }
        return true;
    }
};

void AddSC_era_talent_info_remap()
{
    new EraTalentInfoRemap();
}

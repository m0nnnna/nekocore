/*
 * Stops a pack of dungeon mobs from landing all their crowd control at once.
 *
 * Classic dungeon mobs were tuned for a full group of five, where a stun, a
 * silence and a fear arriving together is survivable because someone else
 * can answer it. mod-autobalance already shortens CC duration for a smaller
 * party (AutoBalance.StatModifier*.CCDuration), but that only shortens each
 * one: a pack of Defias casters can still open with four CC spells inside
 * the same second, and a duo has no one left to act.
 *
 * Rule: in a five-man dungeon, once one creature has started a crowd control
 * spell, no OTHER creature of that instance may start one for a short
 * window. The window shrinks as the group grows and is zero at a full group,
 * so a normal five-player run plays exactly as it did. The blocked cast fails
 * as "not ready"; SmartAI simply skips that use and the mob keeps fighting.
 *
 * Bosses are left alone unless Nekocore.CcStagger.Bosses is set: their CC is
 * scripted as part of the fight.
 *
 * What counts as crowd control is the same list AutoBalance uses for its
 * CCDuration modifier, plus root.
 */

#include "ScriptMgr.h"
#include "Config.h"
#include "Creature.h"
#include "Map.h"
#include "Spell.h"
#include "SpellInfo.h"
#include "Timer.h"

#include <mutex>
#include <unordered_map>

namespace
{
    uint32 staggerMs = 3000;
    uint32 fullGroup = 5;
    bool includeBosses = false;

    struct LastCc
    {
        ObjectGuid caster;
        uint32 atMs = 0;
    };

    std::mutex lock;
    std::unordered_map<uint64, LastCc> lastCc; // (map id, instance id) -> most recent CC cast

    bool IsCrowdControlMechanic(uint32 mechanic)
    {
        switch (mechanic)
        {
            case MECHANIC_CHARM: case MECHANIC_DISORIENTED: case MECHANIC_DISARM: case MECHANIC_FEAR:
            case MECHANIC_SLEEP: case MECHANIC_SILENCE: case MECHANIC_ROOT: case MECHANIC_STUN:
            case MECHANIC_FREEZE: case MECHANIC_KNOCKOUT: case MECHANIC_POLYMORPH: case MECHANIC_HORROR:
                return true;
            default:
                return false;
        }
    }

    bool IsCrowdControl(SpellInfo const* info)
    {
        // By aura first (the list AutoBalance uses, plus root)...
        if (info->HasAura(SPELL_AURA_MOD_CHARM) || info->HasAura(SPELL_AURA_MOD_CONFUSE) ||
            info->HasAura(SPELL_AURA_MOD_DISARM) || info->HasAura(SPELL_AURA_MOD_FEAR) ||
            info->HasAura(SPELL_AURA_MOD_PACIFY) || info->HasAura(SPELL_AURA_MOD_POSSESS) ||
            info->HasAura(SPELL_AURA_MOD_SILENCE) || info->HasAura(SPELL_AURA_MOD_STUN) ||
            info->HasAura(SPELL_AURA_MOD_ROOT) || info->HasAura(SPELL_AURA_MOD_SPEED_SLOW_ALL))
            return true;

        // ...then by mechanic. Screams of the Past (the Shadowfang Keep guards'
        // chain silence) is a persistent area aura whose silence is only its
        // MECHANIC, so no aura check sees it. AutoBalance's CCDuration does not
        // either; the stagger is what covers it.
        if (IsCrowdControlMechanic(info->Mechanic))
            return true;
        for (SpellEffectInfo const& effect : info->GetEffects())
            if (effect.IsEffect() && IsCrowdControlMechanic(effect.Mechanic))
                return true;
        return false;
    }
}

class CcStagger_WorldScript : public WorldScript
{
public:
    CcStagger_WorldScript() : WorldScript("CcStagger_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        staggerMs = sConfigMgr->GetOption<uint32>("Nekocore.CcStagger.Ms", 3000);
        fullGroup = sConfigMgr->GetOption<uint32>("Nekocore.CcStagger.FullGroup", 5);
        includeBosses = sConfigMgr->GetOption<bool>("Nekocore.CcStagger.Bosses", false);
    }
};

class CcStagger_SpellScript : public AllSpellScript
{
public:
    CcStagger_SpellScript() : AllSpellScript("CcStagger_SpellScript", { ALLSPELLHOOK_ON_SPELL_CHECK_CAST }) { }

    void OnSpellCheckCast(Spell* spell, bool /*strict*/, SpellCastResult& res) override
    {
        if (res != SPELL_CAST_OK || staggerMs == 0 || fullGroup < 2 || !spell || spell->IsTriggered())
            return;

        Creature* caster = spell->GetCaster() ? spell->GetCaster()->ToCreature() : nullptr;
        if (!caster || caster->IsControlledByPlayer() || !IsCrowdControl(spell->GetSpellInfo()))
            return;

        Map* map = caster->GetMap();
        if (!map || !map->IsNonRaidDungeon() || (!includeBosses && caster->IsDungeonBoss()))
            return;

        uint32 players = map->GetPlayersCountExceptGMs();
        if (players == 0 || players >= fullGroup)
            return;

        // Full window for one player, none at a full group.
        uint32 window = staggerMs * (fullGroup - players) / (fullGroup - 1);

        uint64 key = (uint64(map->GetId()) << 32) | map->GetInstanceId();
        uint32 now = getMSTime();

        std::lock_guard<std::mutex> guard(lock);
        LastCc& last = lastCc[key];
        if (last.caster && last.caster != caster->GetGUID() && getMSTimeDiff(last.atMs, now) < window)
        {
            res = SPELL_FAILED_NOT_READY;
            return;
        }

        last.caster = caster->GetGUID();
        last.atMs = now;
    }
};

void AddSC_cc_stagger()
{
    new CcStagger_WorldScript();
    new CcStagger_SpellScript();
}

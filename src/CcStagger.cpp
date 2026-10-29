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
 * Rule: in a five-man dungeon, once a creature has started a crowd control
 * spell, no creature of that instance -- the same one included -- may start
 * another until that CC has had time to run out, plus a short breather. Both
 * shrink as the group grows and are zero at a full group, so a normal
 * five-player run plays exactly as it did. Counting only OTHER casters let a
 * Sunken Temple pack of Atal'ai Deathwalkers (Fear every 12-18 sec each)
 * line up one Fear every 3 sec, which a solo player never got out of. The
 * blocked cast fails as "not ready"; SmartAI simply skips that use and the
 * mob keeps fighting.
 *
 * Bosses are left alone unless Nekocore.CcStagger.Bosses is set: their CC is
 * scripted as part of the fight. Interrupts (kicks) count as crowd control,
 * and boss kicks are staggered too unless Nekocore.CcStagger.BossInterrupts
 * is off: the lockout can be 8-10 sec and bosses chain them.
 *
 * Except mind control on the only player in the instance, boss or not and
 * triggered or not: nobody is left to break it, so the fight just stops
 * (Jammal'an's Hex in Sunken Temple, whose charm is a triggered 12483).
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

#include <algorithm>
#include <mutex>
#include <unordered_map>

namespace
{
    uint32 staggerMs = 3000;
    uint32 fullGroup = 5;
    bool includeBosses = false;
    bool bossInterrupts = true;

    // The longest a CC counts as still running: a long one (a 20 sec
    // sleep) should not shut every other CC out for its whole length.
    constexpr uint32 MAX_CC_HOLD_MS = 10000;

    struct LastCc
    {
        uint32 atMs = 0;
        uint32 blockMs = 0; // how long after atMs no new CC may start
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

    bool IsMindControl(SpellInfo const* info)
    {
        return info->HasAura(SPELL_AURA_MOD_CHARM) || info->HasAura(SPELL_AURA_MOD_POSSESS) ||
            info->HasAura(SPELL_AURA_AOE_CHARM);
    }

    // A kick: no aura on the player, it just locks one spell school for the
    // spell's duration (8-10 sec on some bosses). AutoBalance's CCDuration never
    // sees it, so a solo healer got locked out again as soon as it ended.
    bool IsInterrupt(SpellInfo const* info)
    {
        for (SpellEffectInfo const& effect : info->GetEffects())
            if (effect.IsEffect(SPELL_EFFECT_INTERRUPT_CAST))
                return true;
        return false;
    }

    bool IsCrowdControl(SpellInfo const* info)
    {
        if (IsInterrupt(info))
            return true;

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
        bossInterrupts = sConfigMgr->GetOption<bool>("Nekocore.CcStagger.BossInterrupts", true);
    }
};

class CcStagger_SpellScript : public AllSpellScript
{
public:
    CcStagger_SpellScript() : AllSpellScript("CcStagger_SpellScript", { ALLSPELLHOOK_ON_SPELL_CHECK_CAST }) { }

    void OnSpellCheckCast(Spell* spell, bool /*strict*/, SpellCastResult& res) override
    {
        if (res != SPELL_CAST_OK || !spell)
            return;

        Creature* caster = spell->GetCaster() ? spell->GetCaster()->ToCreature() : nullptr;
        if (!caster || caster->IsControlledByPlayer())
            return;

        SpellInfo const* info = spell->GetSpellInfo();
        Map* map = caster->GetMap();
        if (!map || !map->IsNonRaidDungeon())
            return;

        uint32 players = map->GetPlayersCountExceptGMs();
        if (players == 0)
            return;

        if (players == 1 && IsMindControl(info))
        {
            Unit* target = spell->m_targets.GetUnitTarget();
            if (!target || target->IsPlayer())
            {
                res = SPELL_FAILED_NOT_READY;
                return;
            }
        }

        if (staggerMs == 0 || fullGroup < 2 || players >= fullGroup || spell->IsTriggered()
            || !IsCrowdControl(info))
            return;

        // Boss CC is scripted into the fight, but a boss kick is not: it only
        // matters that two of them never land back to back.
        if (!includeBosses && caster->IsDungeonBoss() && !(bossInterrupts && IsInterrupt(info)))
            return;

        // Full length for one player, none at a full group.
        uint32 const hold = std::min<uint32>(std::max(0, info->GetMaxDuration()), MAX_CC_HOLD_MS);
        uint32 const block = (staggerMs + hold) * (fullGroup - players) / (fullGroup - 1);

        uint64 key = (uint64(map->GetId()) << 32) | map->GetInstanceId();
        uint32 now = getMSTime();

        std::lock_guard<std::mutex> guard(lock);
        LastCc& last = lastCc[key];
        if (last.atMs && getMSTimeDiff(last.atMs, now) < last.blockMs)
        {
            res = SPELL_FAILED_NOT_READY;
            return;
        }

        last.atMs = now;
        last.blockMs = block;
    }
};

void AddSC_cc_stagger()
{
    new CcStagger_WorldScript();
    new CcStagger_SpellScript();
}

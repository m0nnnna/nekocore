/*
 * The half of the challenge-run system that actually makes a flagged instance
 * harder. ChallengeRun.cpp decides WHICH instances are challenge runs and at
 * what tier; this file turns that into numbers, by riding along inside
 * mod-autobalance's own pipeline rather than fighting it.
 *
 * Three levers, and a different mechanism for each, because AutoBalance
 * exposes them in three different places:
 *
 * 1. LEVEL -- "it sets the dungeon mobs to scale at that level".
 *
 *    AutoBalance can already do this, but only realm-wide: ABConfig's
 *    `LevelScaling` is a single global read from AutoBalance.LevelScaling, and
 *    on this realm it is deliberately 0 -- a character levelling through
 *    Wailing Caverns at 20 must find it at its real level. Every level-scaling
 *    branch in AutoBalance is behind that one global (ABAllCreatureScript.cpp's
 *    ModifyCreatureAttributes and ABUtils.cpp's UpdateMapDataIfNeeded both test
 *    `LevelScaling &&` first), so there is no way to scale ONE instance while
 *    it is off.
 *
 *    What IS per-map is the skip range. Both of those gates decide "don't
 *    scale" from `mapABInfo->levelScalingSkipHigherLevels` and
 *    `...SkipLowerLevels`, runtime fields on the map's own
 *    AutoBalanceMapInfo -- and a skip value of 0 means "never skip, always
 *    scale" (read the gate: `skipHigher == 0` makes its own clause true).
 *
 *    So: AutoBalance.LevelScaling goes to 1 to arm the machinery, with the
 *    skip ranges wide enough that nothing scales by default, and this module
 *    zeroes the skip fields on challenge instances only. The hook it does that
 *    from is ABModuleScript::OnBeforeModifyAttributes, which AutoBalance calls
 *    per creature at ABAllCreatureScript.cpp:543 -- four lines above the
 *    level-scaling gate at 547. Nothing can get between them, so the fields
 *    cannot be stale and no config reload or map update can undo it mid-run.
 *
 *    Suppressing it everywhere else takes more than that hook, though, and
 *    this is the part the first version of this file got wrong: arming the
 *    global opens THREE copies of the same gate, and the hook can only stand
 *    in front of one of them.
 *
 *      ABAllCreatureScript.cpp:551   sets creature LEVELS        <- the hook
 *      ABUtils.cpp:779               getWorldMultiplier          <- not reachable
 *      ABUtils.cpp:2869              mapLevel/isLevelScalingEnabled <- not reachable
 *
 *    The last two run inside UpdateMapDataIfNeeded right after LoadMapSettings
 *    has reloaded the skip values from config, with no seam between them for a
 *    script hook. Left alone, the getWorldMultiplier one would retarget the
 *    "world" damage/healing multiplier -- damage whose source is not an enemy
 *    creature, i.e. traps and environment -- at the player's level in EVERY
 *    dungeon. That is the "all dungeons got scaled" outcome this module exists
 *    to avoid, and it is invisible from the creature side.
 *
 *    So with Nekocore.Challenge.SuppressLevelScalingOutsideChallenges on (the
 *    default) this module instead owns the values all three gates are fed
 *    from: OnAfterConfigLoad forces AutoBalance's global skip range wide
 *    enough that no level in the game can exceed it, so all three take their
 *    "do not scale" branch exactly as they did while the global was off. The
 *    per-creature hook narrowing that to 0 on a flagged instance is then the
 *    one and only way level scaling ever happens. It also clears AutoBalance's
 *    per-instance skip overrides, because the shipped default
 *    `LevelScaling.DynamicLevel.PerInstance = "229 -1 -1 1, 230 0 0"` carries
 *    a `0 0` that would force scaling on in Blackrock Depths for everybody
 *    regardless of the global.
 *
 *    The level each creature lands on is AutoBalance's own dynamic calculation
 *    from `mapABInfo->highestPlayerLevel`, which this module pins to the run's
 *    bracket so the answer is the bracket and not "whoever is highest". With
 *    Nekocore.Challenge.DynamicLevelCeiling/Floor at their 1/5 defaults the
 *    relative spread inside the dungeon survives -- its own trash sits a few
 *    levels under its own bosses, exactly as it always did, just moved up
 *    wholesale. AutoBalance recomputes highestPlayerLevel from the real players
 *    on its next map update; since a challenge run's players are all at the
 *    bracket (ChallengeRun.cpp blocks entry otherwise), the pinned value and
 *    the real one are the same number in every case but a GM-boosted
 *    character.
 *
 * 2. HEALTH -- ABModuleScript::OnBeforeUpdateStats, whose `scaledHealth` is
 *    the value AutoBalance is about to hand to SetMaxHealth
 *    (ABAllCreatureScript.cpp:1186, then :1202). Multiplying it there means
 *    the tier bonus composes with AutoBalance's own player-count and level
 *    scaling instead of replacing it, and it survives every recalculation
 *    because it happens inside the recalculation.
 *
 * 3. DAMAGE -- this module's own UnitScript, not that same hook. The
 *    `damageMultiplier` reference OnBeforeUpdateStats is handed is a dead end:
 *    by the time it is passed, AutoBalance has already stored
 *    creatureABInfo->DamageMultiplier and computed the scaledDamageMultiplier
 *    it will actually use, and it never reads the parameter again
 *    (ABAllCreatureScript.cpp:1047-1132 vs :1186). Writing to it changes
 *    nothing. So damage is applied the same way WorldEliteScaling.cpp does it,
 *    on the three Modify*Damage* hooks, multiplying whatever AutoBalance's own
 *    ABUnitScript has already produced.
 *
 * Not scaled, deliberately: armor, crowd-control duration, creature healing,
 * and the "world" damage multiplier AutoBalance uses for damage whose source
 * isn't an enemy creature (traps, environment). The first three are AutoBalance
 * struct fields that would each become another thing to keep in sync for a
 * second-order effect. The last one is a direct consequence of how the
 * suppression above works: forcing the global skip range wide makes
 * getWorldMultiplier target avgCreatureLevel on EVERY map, challenge instances
 * included, so a challenge dungeon's traps keep hitting for their own level's
 * amount. That is the right trade -- the alternative leaks scaling into every
 * normal dungeon, and trap damage is a rounding error next to what the
 * creatures do. Health and outgoing damage are the two levers the tiers were
 * asked to move.
 */

#include "ScriptMgr.h"
#include "Creature.h"
#include "Map.h"
#include "Player.h"
#include "Unit.h"

#include "ABConfig.h"
#include "ABCreatureInfo.h"
#include "ABMapInfo.h"
#include "ABModuleScript.h"
#include "ABUtils.h"

#include "ChallengeRun.h"

namespace
{
    // Wide enough that no level in the game can fall outside it, so both of
    // AutoBalance's skip-range tests pass and the creature is left at its own
    // level. (The fields are uint8, and the comparisons promote to int, so
    // `avgCreatureLevel >= highestPlayerLevel - 127` can't wrap.)
    constexpr uint8 SKIP_EVERYTHING = 127;
    constexpr uint8 SKIP_NOTHING    = 0;
}

namespace NekocoreChallenge
{
    void ForceAutoBalanceRefresh(Map* map)
    {
        if (!map)
            return;

        // AutoBalance only revisits a map when its recorded config time has
        // fallen behind, and only revisits a creature when the creature's
        // recorded time has fallen behind the map's. Zeroing the map's makes
        // the first true, and the forced update ends by stamping the map with
        // a fresh time, which makes the second true for every creature already
        // standing in the instance.
        AutoBalanceMapInfo* mapABInfo = GetMapInfo(map);
        mapABInfo->globalConfigTime = 0;
        UpdateMapDataIfNeeded(map, true);
    }
}

class ChallengeScaling_ABModuleScript : public ABModuleScript
{
public:
    ChallengeScaling_ABModuleScript() : ABModuleScript("ChallengeScaling_ABModuleScript") { }

    bool OnBeforeModifyAttributes(Creature* creature, uint32& /*instancePlayerCount*/) override
    {
        if (!NekocoreChallenge::Enabled() || !creature)
            return true;

        Map* map = creature->GetMap();
        if (!map || !map->IsDungeon())
            return true;

        AutoBalanceMapInfo* mapABInfo = GetMapInfo(map);

        NekocoreChallenge::ActiveRun run;
        if (NekocoreChallenge::ActiveRunFor(map, run))
        {
            mapABInfo->levelScalingSkipHigherLevels = SKIP_NOTHING;
            mapABInfo->levelScalingSkipLowerLevels  = SKIP_NOTHING;
            mapABInfo->levelScalingDynamicCeiling   = NekocoreChallenge::DynamicLevelCeiling();
            mapABInfo->levelScalingDynamicFloor     = NekocoreChallenge::DynamicLevelFloor();
            mapABInfo->highestPlayerLevel           = run.bracket;
            return true;
        }

        if (NekocoreChallenge::SuppressOutsideChallenges())
        {
            mapABInfo->levelScalingSkipHigherLevels = SKIP_EVERYTHING;
            mapABInfo->levelScalingSkipLowerLevels  = SKIP_EVERYTHING;
        }
        return true;
    }

    bool OnBeforeUpdateStats(Creature* creature, uint32& scaledHealth, uint32& /*scaledMana*/,
        float& /*damageMultiplier*/, uint32& /*newBaseArmor*/) override
    {
        if (!NekocoreChallenge::Enabled() || !creature)
            return true;

        NekocoreChallenge::ActiveRun run;
        if (!NekocoreChallenge::ActiveRunFor(creature->GetMap(), run) || run.healthMult == 1.0f)
            return true;

        scaledHealth = uint32(float(scaledHealth) * run.healthMult);
        return true;
    }
};

class ChallengeScaling_UnitScript : public UnitScript
{
public:
    ChallengeScaling_UnitScript()
        : UnitScript("ChallengeScaling_UnitScript", true, {
            UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN,
            UNITHOOK_MODIFY_MELEE_DAMAGE,
            UNITHOOK_MODIFY_PERIODIC_DAMAGE_AURAS_TICK
        })
    {
    }

    void ModifySpellDamageTaken(Unit* target, Unit* source, int32& amount, SpellInfo const* /*spellInfo*/) override
    {
        Scale(target, source, amount);
    }

    void ModifyMeleeDamage(Unit* target, Unit* source, uint32& amount) override
    {
        int32 signedAmount = int32(amount);
        Scale(target, source, signedAmount);
        amount = uint32(signedAmount);
    }

    void ModifyPeriodicDamageAurasTick(Unit* target, Unit* source, uint32& amount, SpellInfo const* /*spellInfo*/) override
    {
        int32 signedAmount = int32(amount);
        Scale(target, source, signedAmount);
        amount = uint32(signedAmount);
    }

private:
    // Only what a creature in a challenge instance deals TO a player. The
    // reverse direction is left alone on purpose -- a tier makes the dungeon
    // tougher, it doesn't blunt the party.
    void Scale(Unit* target, Unit* source, int32& amount)
    {
        if (!target || !source || !target->IsPlayer() || !source->ToCreature())
            return;

        NekocoreChallenge::ActiveRun run;
        if (!NekocoreChallenge::ActiveRunFor(source->GetMap(), run) || run.damageMult == 1.0f)
            return;

        amount = int32(float(amount) * run.damageMult);
    }
};

class ChallengeScaling_WorldScript : public WorldScript
{
public:
    ChallengeScaling_WorldScript() : WorldScript("ChallengeScaling_WorldScript") { }

    void OnAfterConfigLoad(bool /*reload*/) override
    {
        if (!NekocoreChallenge::Enabled())
            return;

        // Without AutoBalance's own global armed, every level-scaling branch in
        // it returns before it would read the per-map fields this module sets,
        // and a challenge run would silently be "same mobs, more health" --
        // which is exactly the kind of quietly-half-working state this repo has
        // been bitten by before. Say so loudly instead.
        if (!LevelScaling)
            LOG_ERROR("module.nekocore",
                "Challenge: AutoBalance.LevelScaling is 0, so challenge runs CANNOT pin dungeons to your "
                "level -- they will only get the health and damage bonuses. Set AutoBalance.LevelScaling = 1 "
                "in etc/modules/AutoBalance.conf (normal dungeons stay unscaled: see "
                "Nekocore.Challenge.SuppressLevelScalingOutsideChallenges).");

        if (!NekocoreChallenge::SuppressOutsideChallenges())
            return;

        // Arming AutoBalance's global opens THREE separate copies of the same
        // level gate, not one, and OnBeforeModifyAttributes can only stand in
        // front of the first:
        //
        //   ABAllCreatureScript.cpp:551  sets creature LEVELS      <- our hook
        //   ABUtils.cpp:779              getWorldMultiplier        <- not ours
        //   ABUtils.cpp:2869             mapLevel / isLevelScaling <- not ours
        //
        // The second and third run inside UpdateMapDataIfNeeded, immediately
        // after LoadMapSettings has (re)loaded the skip values from config --
        // there is no seam between them for a script hook, so a per-map fixup
        // cannot reach them. Left alone, the second one would retarget the
        // "world" damage/healing multiplier (damage whose source is not an enemy
        // creature: traps, environment) at the player's level in EVERY dungeon,
        // which is precisely the "all dungeons got scaled" outcome this module
        // exists to avoid.
        //
        // So own the values the three gates are all fed from instead. A skip
        // range this wide can never be exceeded by any level in the game, so
        // all three gates take their "do not scale" branch, exactly as they did
        // while the global was off -- and OnBeforeModifyAttributes narrowing it
        // to 0 per creature on a flagged instance stays the one and only way
        // level scaling ever happens.
        LevelScalingSkipHigherLevels = int8(SKIP_EVERYTHING);
        LevelScalingSkipLowerLevels  = int8(SKIP_EVERYTHING);

        // AutoBalance's own LevelScaling.DynamicLevel.PerInstance default is
        // "229 -1 -1 1, 230 0 0", and that `0 0` is a per-map skip override
        // (applied in LoadMapSettings after the globals) that would force
        // scaling on in Blackrock Depths for everyone regardless of the above.
        // -1 is that parser's "leave the global alone" value. Ceiling/floor
        // overrides are deliberately left intact: they only matter once scaling
        // is enabled, which now only happens on challenge instances, where this
        // module sets its own ceiling and floor anyway.
        uint32 cleared = 0;
        for (auto& entry : levelScalingDynamicLevelOverrides)
        {
            if (entry.second.skipHigher != -1 || entry.second.skipLower != -1)
            {
                entry.second.skipHigher = -1;
                entry.second.skipLower  = -1;
                ++cleared;
            }
        }

        LOG_INFO("module.nekocore", "Challenge: level scaling suppressed outside challenge runs "
            "(AutoBalance skip range forced to {}/{}, {} per-instance skip override(s) cleared)",
            uint32(SKIP_EVERYTHING), uint32(SKIP_EVERYTHING), cleared);
    }
};

void AddSC_nekocore_challenge_scaling()
{
    new ChallengeScaling_ABModuleScript();
    new ChallengeScaling_UnitScript();
    new ChallengeScaling_WorldScript();
}

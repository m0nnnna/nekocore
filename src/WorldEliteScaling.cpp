/*
 * mod-autobalance never touches open-world content at all -- confirmed by
 * reading its own gate directly, not assumed: ABUtils.cpp's
 * ShouldMapBeEnabled() returns false for any map where !map->IsDungeon()
 * ("Not enabled because the map is not an instance"), and
 * ABUnitScript::_Modify_Damage_Healing (the hook that actually scales
 * damage/healing numbers) independently bails unless BOTH source and
 * target are on a dungeon map. So a world elite or world boss out on a
 * continent is always at its raw creature_template stats, full stop --
 * exactly the "great in instances, brutal solo out in the world" gap this
 * fixes. Setting a multiplier on AutoBalanceCreatureInfo (the way
 * AutoBalanceManaBurnFix.cpp does for mana burn, which has no such gate)
 * would NOT make AutoBalance's own damage hook fire for these creatures --
 * that hook's dungeon check comes first and returns before it would ever
 * read the multiplier. So this is a real standalone scaler, not a thin
 * wrapper around AutoBalance for the open world.
 *
 * Deliberately scoped to just the two levers that matter for "can a solo
 * player or small group actually fight this thing": the creature's max
 * health (time-to-kill) and the damage/healing it deals to players
 * (survivability). Armor and CC-duration scaling are what's left on the
 * table if this needs to go further -- not built here since health +
 * outgoing damage are the two big levers and every extra stat is another
 * thing to keep in sync with AutoBalance's own struct.
 *
 * Which creatures: rank ELITE, RAREELITE, or WORLDBOSS
 * (SharedDefines.h's CreatureEliteType) on a MAP_COMMON map
 * (MapEntry::IsWorldMap() -- the real open continents, not instances,
 * battlegrounds, or arenas, confirmed against DBCStructure.h directly).
 * Plain CREATURE_ELITE_RARE ("rare" but not elite) is deliberately
 * excluded -- those are already normal-difficulty mobs meant to be
 * soloable, matching how the user described the problem ("world elites
 * and world bosses", not every rare spawn).
 *
 * When: UnitScript::OnUnitEnterCombat, which for a Creature only fires
 * from Creature::AtEngage -- the actual out-of-combat -> combat
 * transition (confirmed at its one call site in Creature.cpp), not
 * re-fired on every subsequent hit of the same fight. So "capture the
 * radius as the fight starts" falls out of this hook for free, no
 * dedup/cooldown tracking needed on this module's end.
 *
 * The player count itself is a spatial snapshot (everyone within
 * Nekocore.WorldEliteScaling.Radius of the creature at the moment it
 * engages), not a threat-table read -- deliberately, so a healer or
 * caster standing at range who hasn't landed a hit yet still counts.
 * That's also why the default radius (100 yards) is generous rather than
 * melee-sized: it needs to comfortably cover a caster/healer's actual
 * standing position during a pull, not just weapon range.
 *
 * Health baseline is captured once per creature (AutoBalanceCreatureInfo's
 * own initialMaxHealth field, shared with AutoBalance's struct on
 * purpose) so re-engaging the same creature later always scales from its
 * true unmodified template health, never from an already-scaled value.
 */

#include "ScriptMgr.h"
#include "Creature.h"
#include "CreatureData.h"
#include "Map.h"
#include "Player.h"
#include "Config.h"

#include "ABCreatureInfo.h"

#include <algorithm>

namespace
{
    bool  Enable            = true;
    float Radius            = 100.0f;
    uint32 BaselineElite     = 3;
    uint32 BaselineRareElite = 5;
    uint32 BaselineWorldBoss = 15;
    float MinMultiplier     = 0.4f;
    float MaxMultiplier     = 1.5f;
    bool  ScaleXP           = true;

    void LoadWorldEliteScalingConfig()
    {
        Enable            = sConfigMgr->GetOption<bool>("Nekocore.WorldEliteScaling.Enable", true);
        Radius            = sConfigMgr->GetOption<float>("Nekocore.WorldEliteScaling.Radius", 100.0f);
        BaselineElite     = sConfigMgr->GetOption<uint32>("Nekocore.WorldEliteScaling.BaselineElite", 3);
        BaselineRareElite = sConfigMgr->GetOption<uint32>("Nekocore.WorldEliteScaling.BaselineRareElite", 5);
        BaselineWorldBoss = sConfigMgr->GetOption<uint32>("Nekocore.WorldEliteScaling.BaselineWorldBoss", 15);
        MinMultiplier     = sConfigMgr->GetOption<float>("Nekocore.WorldEliteScaling.MinMultiplier", 0.4f);
        MaxMultiplier     = sConfigMgr->GetOption<float>("Nekocore.WorldEliteScaling.MaxMultiplier", 1.5f);
        ScaleXP           = sConfigMgr->GetOption<bool>("Nekocore.WorldEliteScaling.ScaleXP", true);
    }

    uint32 BaselineForRank(uint32 rank)
    {
        switch (rank)
        {
            case CREATURE_ELITE_ELITE:     return BaselineElite;
            case CREATURE_ELITE_RAREELITE: return BaselineRareElite;
            case CREATURE_ELITE_WORLDBOSS: return BaselineWorldBoss;
            default:                       return 0; // not a scaled rank
        }
    }

    uint32 CountNearbyPlayers(Creature* creature)
    {
        uint32 count = 0;
        Map::PlayerList const& players = creature->GetMap()->GetPlayers();
        for (auto const& ref : players)
        {
            Player* player = ref.GetSource();
            if (!player || !player->IsAlive() || player->IsGameMaster())
                continue;

            if (creature->GetDistance(player) <= Radius)
                ++count;
        }
        return count;
    }
}

class WorldEliteScaling_UnitScript : public UnitScript
{
public:
    WorldEliteScaling_UnitScript()
        : UnitScript("WorldEliteScaling_UnitScript", true, {
            UNITHOOK_ON_UNIT_ENTER_COMBAT,
            UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN,
            UNITHOOK_MODIFY_MELEE_DAMAGE,
            UNITHOOK_MODIFY_PERIODIC_DAMAGE_AURAS_TICK
        })
    {
    }

    void OnUnitEnterCombat(Unit* unit, Unit* /*victim*/) override
    {
        if (!Enable)
            return;

        Creature* creature = unit->ToCreature();
        if (!creature || !creature->GetMap() || !creature->GetMap()->IsWorldMap())
            return;

        CreatureTemplate const* cInfo = creature->GetCreatureTemplate();
        if (!cInfo)
            return;

        uint32 baseline = BaselineForRank(cInfo->rank);
        if (!baseline)
            return; // normal/rare (non-elite) -- not our concern

        uint32 nearby = CountNearbyPlayers(creature);
        float multiplier = std::clamp(float(nearby) / float(baseline), MinMultiplier, MaxMultiplier);

        AutoBalanceCreatureInfo* abInfo = creature->CustomData.GetDefault<AutoBalanceCreatureInfo>("AutoBalanceCreatureInfo");

        abInfo->ScaledDamageMultiplier = multiplier;
        abInfo->ScaledManaMultiplier   = multiplier;
        // Kill XP follows the health cut (read back in WorldEliteScaling_
        // PlayerScript): a solo player against an elite at 40% health got the
        // full elite reward for 40% of the work, which made world elites the
        // best XP farm in the game. Never raised above the template reward --
        // a large group already splits the kill between more players.
        abInfo->XPModifier = std::min(multiplier, 1.0f);

        if (!abInfo->initialMaxHealth)
            abInfo->initialMaxHealth = creature->GetMaxHealth();

        float healthPct = creature->GetHealthPct();
        uint32 newMaxHealth = uint32(abInfo->initialMaxHealth * multiplier);
        creature->SetMaxHealth(newMaxHealth);
        creature->SetHealth(uint32(newMaxHealth * healthPct / 100.0f));
        // The core only allows loot, XP and quest credit once players have
        // dealt half the creature's health (IsDamageEnoughForLootingAndReward),
        // and set that requirement at spawn from the UNSCALED health.
        // SetMaxHealth does not touch it, so a solo player against an elite
        // cut to 40% could never reach it: Hogger died with no loot and no
        // Huge Gnoll Claw. Measure it against the health actually fought.
        creature->ResetPlayerDamageReq();

        LOG_DEBUG("module.nekocore", "WorldEliteScaling: {} ({}) engaged on map {} with {} nearby player(s) (baseline {}) -> multiplier {:.2f}, maxHealth {}->{}",
            creature->GetName(), creature->GetEntry(), creature->GetMapId(), nearby, baseline, multiplier,
            abInfo->initialMaxHealth, newMaxHealth);
    }

    void ModifySpellDamageTaken(Unit* target, Unit* source, int32& amount, SpellInfo const* /*spellInfo*/) override
    {
        ScaleOutgoingAmount(target, source, amount);
    }

    void ModifyMeleeDamage(Unit* target, Unit* source, uint32& amount) override
    {
        int32 signedAmount = int32(amount);
        ScaleOutgoingAmount(target, source, signedAmount);
        amount = uint32(signedAmount);
    }

    void ModifyPeriodicDamageAurasTick(Unit* target, Unit* source, uint32& amount, SpellInfo const* /*spellInfo*/) override
    {
        int32 signedAmount = int32(amount);
        ScaleOutgoingAmount(target, source, signedAmount);
        amount = uint32(signedAmount);
    }

private:
    // Only scales damage a world-scaled creature deals TO a player -- the
    // reverse direction (player damaging the creature) is intentionally
    // left alone, same reasoning as skipping armor scaling above: health +
    // outgoing damage are the two levers this was built for.
    //
    // The map check is not redundant with OnUnitEnterCombat's. The multiplier
    // is read out of AutoBalanceCreatureInfo, which is mod-autobalance's OWN
    // struct on the creature (same CustomData key on purpose, see the header
    // comment) -- so inside a dungeon this reads a multiplier AutoBalance set
    // for itself and has already applied in its own ABUnitScript, and
    // applying it again here would square it. Only creatures on a real
    // continent have a multiplier that belongs to this module.
    void ScaleOutgoingAmount(Unit* target, Unit* source, int32& amount)
    {
        if (!target || !source || !target->IsPlayer())
            return;

        Creature* creature = source->ToCreature();
        if (!creature || !creature->GetMap() || !creature->GetMap()->IsWorldMap())
            return;

        float multiplier = creature->CustomData.GetDefault<AutoBalanceCreatureInfo>("AutoBalanceCreatureInfo")->ScaledDamageMultiplier;
        if (multiplier == 1.0f)
            return;

        amount = int32(amount * multiplier);
    }
};

class WorldEliteScaling_PlayerScript : public PlayerScript
{
public:
    WorldEliteScaling_PlayerScript() : PlayerScript("WorldEliteScaling_PlayerScript", { PLAYERHOOK_ON_GIVE_EXP }) { }

    void OnPlayerGiveXP(Player* /*player*/, uint32& amount, Unit* victim, uint8 xpSource) override
    {
        if (!Enable || !ScaleXP || xpSource != XPSOURCE_KILL || !victim)
            return;

        // World maps only, for the same reason as ScaleOutgoingAmount: in a
        // dungeon the struct is AutoBalance's, which scales XP itself.
        Creature* creature = victim->ToCreature();
        if (!creature || !creature->GetMap() || !creature->GetMap()->IsWorldMap())
            return;

        float modifier = creature->CustomData.GetDefault<AutoBalanceCreatureInfo>("AutoBalanceCreatureInfo")->XPModifier;
        if (modifier < 1.0f)
            amount = uint32(amount * modifier);
    }
};

class WorldEliteScaling_WorldScript : public WorldScript
{
public:
    WorldEliteScaling_WorldScript() : WorldScript("WorldEliteScaling_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        LoadWorldEliteScalingConfig();
    }
};

void AddSC_world_elite_scaling()
{
    new WorldEliteScaling_UnitScript();
    new WorldEliteScaling_PlayerScript();
    new WorldEliteScaling_WorldScript();
}

/*
 * mod-autobalance scales creature damage/healing via UnitScript hooks
 * (ModifySpellDamageTaken, etc.) that fire on the FINAL damage total a
 * spell effect produces -- see AutoBalance_UnitScript::_Modify_Damage_Healing
 * in modules/mod-autobalance/src/ABUnitScript.cpp. That works fine for
 * ordinary damage spells, but Mana Burn (SPELL_EFFECT_POWER_BURN,
 * Spell::EffectPowerBurn in src/server/game/Spells/SpellEffects.cpp) is
 * different: it drains a FLAT amount of the TARGET's mana taken directly
 * from the spell's own unscaled effect base value (Spell.dbc), converts
 * however much mana actually got drained into 1:1 HP damage, and only
 * THAT resulting HP damage flows into the standard pipeline AutoBalance
 * hooks into (confirmed by reading EffectPowerBurn and tracing m_damage
 * through to Unit::CalculateSpellDamageTaken, not guessed). The mana lost
 * itself never passes through any AutoBalance-aware code at all -- a
 * boss scaled DOWN for a smaller group still drains the exact same huge
 * chunk of mana content designers set for a full group, even though its
 * resulting damage number gets correctly reduced.
 *
 * Spell id list: started from a grep of src/server/scripts for every
 * "Mana Burn"-named spell this core's own creature scripts cast (5 ids),
 * then merged with a much larger list the user had already compiled
 * researching this same problem (2 local files, 76 ids total). Every id
 * was verified directly against Spell.dbc before being trusted -- not
 * just carried over on faith -- confirming each genuinely has a
 * SPELL_EFFECT_POWER_BURN effect (76/76 did) and recording which EFFECT
 * slot it's actually in (mostly 0, but several are at 1 or 2 -- hence
 * hooking all three below rather than assuming 0 like the first pass of
 * this fix did). One id from that combined list, 8129, is deliberately
 * excluded: it's the player Priest talent, the one id EffectPowerBurn
 * itself special-cases as a percentage of max mana rather than a flat
 * amount, players aren't AutoBalance-scaled in the first place, and it
 * already has its own core SpellScript (spell_pri_mana_burn) this
 * doesn't touch (also: spell_script_names is one ScriptName per spell
 * id, so registering a second script against 8129 would conflict with
 * that existing one). The user's own research files described trying to
 * fix this before by directly overwriting these spells' rows in the
 * spell_dbc table (a server-side per-spell override AzerothCore supports,
 * LOAD_DBC(sSpellStore, "Spell.dbc", "spell_dbc") in DBCStores.cpp) --
 * confirmed that was never actually applied to this database (spell_dbc
 * has 4517 rows but zero for any of these 76 ids, checked directly), so
 * there was nothing to revert. That approach would have been a static,
 * one-time value change anyway -- doesn't respond to encounter size the
 * way this dynamic per-cast multiplier does, which is the whole reason
 * for building this instead.
 *
 * Fix, part one: a SpellScript on OnEffectHitTarget -- runs just
 * before Spell::EffectPowerBurn processes each target (it only acts in
 * HIT_TARGET mode, and Spell::HandleEffects recomputes `damage` from the
 * DBC at the start of every mode, so a LAUNCH_TARGET change is thrown
 * away: the first version of this fix never scaled the mana at all) -- that scales the
 * effect's base value by the CASTER's own AutoBalance
 * ScaledDamageMultiplier before the core handler ever sees it, so the
 * mana drained is scaled by the same factor mod-autobalance already
 * computed for that creature.
 *
 * Fix, part two (OnHit), because part one alone DOUBLE-scales the damage
 * half. EffectPowerBurn derives its damage from however much mana was
 * actually drained (`newDamage = -(ModifyPower(...)) * dmgMultiplier;
 * m_damage += newDamage`), so scaling the effect value scales the damage
 * with it -- and then Spell::DoAllEffectOnTarget's `m_damage > 0` block
 * (Spell.cpp) hands that total to Unit::CalculateSpellDamageTaken, which
 * fires ModifySpellDamageTaken unconditionally (Unit.cpp) and lets
 * AutoBalance scale it a SECOND time. Result before this: mana drained
 * x1, damage x2. It matters -- 68 of the 75 spells here have a non-zero
 * EffectValueMultiplier on their POWER_BURN effect (0.5 to 30, checked
 * against Spell.dbc), so most of them really do deal damage.
 *
 * So the OnHit handler divides the accumulated damage back out by the
 * same multiplier, leaving the one application that the damage pipeline
 * is about to do. OnHit is the right seam: CallScriptOnHitHandlers()
 * runs before that `m_damage > 0` block in the same function, and
 * SpellScript::SetHitDamage writes straight to m_spell->m_damage and is
 * legal in that hook (IsInTargetHook covers SPELL_SCRIPT_HOOK_HIT).
 *
 * The invariant this rests on: whoever set ScaledDamageMultiplier on the
 * creature also applies it to that creature's outgoing damage. True for
 * both writers -- mod-autobalance in dungeons (ABUnitScript) and
 * WorldEliteScaling.cpp in the open world -- and where neither has
 * touched the creature the multiplier is 1.0f and both handlers no-op,
 * so battlegrounds and AutoBalance-disabled maps fall out correctly.
 * AutoBalance's one hardcoded spellIdsToNeverModify entry (1177, Twin
 * Empathy) is not in this file's list, so that exemption can't desync
 * the two halves either.
 *
 * Reads mod-autobalance's own CustomData directly (its src/ dir is on the
 * shared `modules` target's include path -- confirmed against
 * modules/CMakeLists.txt's CollectIncludeDirectories/
 * target_include_directories setup, a supported cross-module include for
 * MODULES=static builds, not a hack). Needs no changes to mod-autobalance
 * itself, and defaults safely to a 1.0 no-op for any caster AutoBalance
 * hasn't touched (GetDefault<AutoBalanceCreatureInfo>() default-
 * constructs with ScaledDamageMultiplier = 1.0f if nothing set it).
 *
 * Registration: spell_script_names is spell_id -> ScriptName, one name
 * per spell, so each of the 3 classes below (see their own comment for
 * why there are 3) is registered once per matching spell id under a
 * distinct name via RegisterSpellScriptWithArgs (the plain
 * RegisterSpellScript macro always uses the class's own name and can't
 * be reused this way). SQL: data/sql/db-world/base/mana_burn_scaling.sql.
 */

#include "ScriptMgr.h"
#include "SpellScript.h"
#include "SpellScriptLoader.h"
#include "Unit.h"

#include "ABCreatureInfo.h"

namespace
{
    // Whatever has already scaled this creature: mod-autobalance inside a
    // dungeon, or WorldEliteScaling.cpp out in the world. 1.0f when nothing
    // has, which makes both handlers below a no-op. Defensive about <= 0 so
    // the division in UndoDamageDoubleScaling can never blow up.
    float ScaledDamageMultiplierOf(Unit* caster)
    {
        if (!caster)
            return 1.0f;

        float multiplier = caster->CustomData.GetDefault<AutoBalanceCreatureInfo>("AutoBalanceCreatureInfo")->ScaledDamageMultiplier;
        return multiplier > 0.0f ? multiplier : 1.0f;
    }
}

// Three near-identical classes, one per effect slot, rather than one class
// hooking all three: AzerothCore's spell-script loader validates every
// registered hook against the actual spell's effect data at startup and
// logs a warning for any that don't match ("did not match dbc effect
// data -- handler ... won't be executed") -- harmless (the effect-0 hook
// still fires fine on a spell that only has POWER_BURN at 0), but 65 of
// these 75 spells only have it at effect 0, so registering all three
// against every spell produced ~140 spurious warnings at every startup.
// Each spell is registered below under whichever ONE of these three
// actually matches its own data (grouped by checking Spell.dbc directly,
// same as the id list itself) -- zero warnings this way.
#define NEKOCORE_MANA_BURN_SCALE_BODY \
    void ScaleEffectValue(SpellEffIndex /*effIndex*/) \
    { \
        float multiplier = ScaledDamageMultiplierOf(GetCaster()); \
        if (multiplier == 1.0f) \
            return; \
        SetEffectValue(int32(GetEffectValue() * multiplier)); \
    } \
    \
    void UndoDamageDoubleScaling() \
    { \
        float multiplier = ScaledDamageMultiplierOf(GetCaster()); \
        if (multiplier == 1.0f) \
            return; \
        SetHitDamage(int32(float(GetHitDamage()) / multiplier)); \
    }

class spell_nekocore_mana_burn_scaling_e0 : public SpellScript
{
    PrepareSpellScript(spell_nekocore_mana_burn_scaling_e0);
    NEKOCORE_MANA_BURN_SCALE_BODY

    void Register() override
    {
        OnEffectHitTarget += SpellEffectFn(spell_nekocore_mana_burn_scaling_e0::ScaleEffectValue, EFFECT_0, SPELL_EFFECT_POWER_BURN);
        OnHit += SpellHitFn(spell_nekocore_mana_burn_scaling_e0::UndoDamageDoubleScaling);
    }
};

class spell_nekocore_mana_burn_scaling_e1 : public SpellScript
{
    PrepareSpellScript(spell_nekocore_mana_burn_scaling_e1);
    NEKOCORE_MANA_BURN_SCALE_BODY

    void Register() override
    {
        OnEffectHitTarget += SpellEffectFn(spell_nekocore_mana_burn_scaling_e1::ScaleEffectValue, EFFECT_1, SPELL_EFFECT_POWER_BURN);
        OnHit += SpellHitFn(spell_nekocore_mana_burn_scaling_e1::UndoDamageDoubleScaling);
    }
};

class spell_nekocore_mana_burn_scaling_e2 : public SpellScript
{
    PrepareSpellScript(spell_nekocore_mana_burn_scaling_e2);
    NEKOCORE_MANA_BURN_SCALE_BODY

    void Register() override
    {
        OnEffectHitTarget += SpellEffectFn(spell_nekocore_mana_burn_scaling_e2::ScaleEffectValue, EFFECT_2, SPELL_EFFECT_POWER_BURN);
        OnHit += SpellHitFn(spell_nekocore_mana_burn_scaling_e2::UndoDamageDoubleScaling);
    }
};

#undef NEKOCORE_MANA_BURN_SCALE_BODY

// Mana DRAIN (SPELL_EFFECT_POWER_DRAIN) has the same flaw as burn: a flat
// amount straight from Spell.dbc that AutoBalance never sees. It deals no
// health damage, so only the effect value needs scaling, and
// Spell::EffectPowerDrain runs in HIT_TARGET mode, not LAUNCH_TARGET.
// Razorclaw the Butcher's Butcher Drain (7485) takes 350 mana every
// 2.8-9.7 s, which empties a solo level-24 caster in two or three casts.
class spell_nekocore_mana_drain_scaling_e0 : public SpellScript
{
    PrepareSpellScript(spell_nekocore_mana_drain_scaling_e0);

    void ScaleEffectValue(SpellEffIndex /*effIndex*/)
    {
        float multiplier = ScaledDamageMultiplierOf(GetCaster());
        if (multiplier == 1.0f)
            return;
        SetEffectValue(int32(GetEffectValue() * multiplier));
    }

    void Register() override
    {
        OnEffectHitTarget += SpellEffectFn(spell_nekocore_mana_drain_scaling_e0::ScaleEffectValue, EFFECT_0, SPELL_EFFECT_POWER_DRAIN);
    }
};

void AddSC_nekocore_mana_burn_scaling()
{
    // EFFECT_0 -- 65 spells
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_2691");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_8211");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_11981");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_12745");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_13321");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_14033");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_15785");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_15800");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_15980");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_17615");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_17630");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_19665");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_19821");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_20817");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_21858");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_22189");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_22745");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_22936");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_22947");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_23393");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_23772");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_24684");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_25779");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_26046");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_26049");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_27992");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_28301");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_29405");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_29907");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_31729");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_32003");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_32897");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_33385");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_33974");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_34930");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_34931");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_36484");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_36846");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_37159");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_38883");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_38884");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_39020");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_39136");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_39262");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_39675");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_40305");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_40861");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_40940");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_41039");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_46266");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_48054");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_50638");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_54338");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_55010");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_57047");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_59723");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_63705");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_66100");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_68026");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_68027");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_68028");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_71086");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_71743");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_72029");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e0, "spell_nekocore_mana_burn_72030");
    // EFFECT_1 -- 1 spell
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e1, "spell_nekocore_mana_burn_41545");
    // EFFECT_2 -- 9 spells
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_17631");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_22290");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_22559");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_23010");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_23187");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_23189");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_39037");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_62129");
    RegisterSpellScriptWithArgs(spell_nekocore_mana_burn_scaling_e2, "spell_nekocore_mana_burn_62471");
    // POWER_DRAIN, EFFECT_0
    RegisterSpellScriptWithArgs(spell_nekocore_mana_drain_scaling_e0, "spell_nekocore_mana_drain_7485");
}

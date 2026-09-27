/*
 * Handlers for era spells whose behaviour lived in the Vanilla/TBC CORE,
 * not in their data.
 *
 * Most era spells need nothing here: build_era_spells.py gives them their
 * own era effects, and AzerothCore runs those natively. The exceptions
 * carry a DUMMY effect -- a placeholder the old core filled in with
 * hardcoded logic that AzerothCore (a WotLK core) never had, and whose
 * WotLK SpellScripts were written for a different effect layout (the core
 * refuses to bind them: see tools/server/dump_era_script_mismatches.sh).
 * Without a handler such a spell casts and does nothing.
 *
 * Every rule below is read from the era spell's OWN data wherever the data
 * states it (seal -> judgement link, talent chance, regen coefficients),
 * and cites the source where it does not. They are bound to era spell ids
 * by build_era_spell_sql.py's ERA_SCRIPTS, so a rebuild keeps them.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Random.h"
#include "SpellAuras.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "SpellScript.h"
#include "SpellScriptLoader.h"

#include "EraSpells.h"

namespace
{
    using namespace NekoEraSpells;

    // Sanctified Judgement, TBC Retribution talent, ranks 1-3 (era copies).
    constexpr uint32 TBC_SANCTIFIED_JUDGEMENT[] = { 431876, 431877, 431878 };

    // Vanilla/TBC seals name the judgement they unleash in EFFECT_2: a
    // DUMMY aura whose amount is that judgement's spell id (Seal of
    // Righteousness r1 -> 20187 Judgement of Righteousness). The TBC core
    // read it exactly this way, and so does WotLK's own spell_pal_judgement.
    AuraEffect const* FindEraSeal(Unit const* caster)
    {
        for (AuraEffect const* eff : caster->GetAuraEffectsByType(SPELL_AURA_DUMMY))
        {
            if (eff->GetEffIndex() != EFFECT_2 || eff->GetCasterGUID() != caster->GetGUID())
                continue;
            if (EraOfSpell(eff->GetId()) == ERA_WOTLK || eff->GetAmount() <= 0)
                continue;
            if (sSpellMgr->GetSpellInfo(static_cast<uint32>(eff->GetAmount())) ||
                sSpellMgr->GetSpellInfo(static_cast<uint32>(eff->GetAmount()) + OffsetOfEra(EraOfSpell(eff->GetId()))))
                return eff;
        }
        return nullptr;
    }
}

// Judgement (Vanilla 20271 / TBC 20271): "Unleashes the energy of a Seal
// spell to judge an enemy". Casts the active seal's judgement on the target
// and consumes the seal -- in these eras judging used the seal up, unlike
// WotLK where it stays. The judgement cast is this era's own copy of the
// spell the seal names, so it carries era values and era scripts.
class spell_era_pal_judgement : public SpellScript
{
    PrepareSpellScript(spell_era_pal_judgement);

    void HandleScript(SpellEffIndex /*effIndex*/)
    {
        Unit* caster = GetCaster();
        Unit* target = GetHitUnit();
        if (!caster || !target)
            return;

        AuraEffect const* sealEff = FindEraSeal(caster);
        if (!sealEff)
            return;

        Era const era = EraOfSpell(sealEff->GetId());
        uint32 const named = static_cast<uint32>(sealEff->GetAmount());
        uint32 const judgement = EraSpellFor(era, named) ? EraSpellFor(era, named) : named;
        SpellInfo const* sealInfo = sealEff->GetSpellInfo();

        caster->CastSpell(target, judgement, true);

        // Sanctified Judgement: "$s1% chance to return 80% of the mana cost
        // of the judged seal". The chance is the talent rank's own amount.
        for (uint32 talentSpell : TBC_SANCTIFIED_JUDGEMENT)
        {
            AuraEffect const* talent = caster->GetAuraEffect(talentSpell, EFFECT_0);
            if (!talent || !roll_chance_i(talent->GetAmount()))
                continue;
            int32 const cost = sealInfo->CalcPowerCost(caster, sealInfo->GetSchoolMask());
            if (cost > 0)
                caster->EnergizeBySpell(caster, talentSpell, uint32(cost * 80 / 100), POWER_MANA);
            break;
        }

        caster->RemoveAurasDueToSpell(sealEff->GetId(), caster->GetGUID());
    }

    void Register() override
    {
        OnEffectHitTarget += SpellEffectFn(spell_era_pal_judgement::HandleScript, EFFECT_0, SPELL_EFFECT_SCRIPT_EFFECT);
    }
};

// Aspect of the Viper (TBC 34074). Patch 2.4 tooltip: "regenerating mana
// equal to up to 55% of your Intellect plus 35% of your level every 5 sec.
// The lower your mana, the more mana will be regenerated." 55 and 35 are
// this row's own EFFECT_0/EFFECT_1 amounts and 5 sec its period, so they
// are read from the spell rather than restated. "Up to" is taken as the
// full amount at empty mana falling linearly to nothing at full mana --
// the patch notes give the ends, not the curve between them.
class spell_era_hun_aspect_of_the_viper : public AuraScript
{
    PrepareAuraScript(spell_era_hun_aspect_of_the_viper);

    void HandlePeriodic(AuraEffect const* aurEff)
    {
        Unit* target = GetTarget();
        if (!target || target->getPowerType() != POWER_MANA)
            return;

        uint32 const maxMana = target->GetMaxPower(POWER_MANA);
        if (!maxMana)
            return;

        float const intPct = float(aurEff->GetAmount());
        float const levelPct = float(GetSpellInfo()->Effects[EFFECT_1].CalcValue());
        float const missing = 1.0f - float(target->GetPower(POWER_MANA)) / float(maxMana);
        float const full = target->GetStat(STAT_INTELLECT) * intPct / 100.0f
            + float(target->GetLevel()) * levelPct / 100.0f;

        int32 const gain = int32(full * missing);
        if (gain > 0)
            target->EnergizeBySpell(target, GetId(), uint32(gain), POWER_MANA);
    }

    void Register() override
    {
        OnEffectPeriodic += AuraEffectPeriodicFn(spell_era_hun_aspect_of_the_viper::HandlePeriodic, EFFECT_0, SPELL_AURA_PERIODIC_DUMMY);
    }
};

// Holy Shock (Vanilla/TBC 20473 chain). The same mechanic as WotLK's
// spell_pal_holy_shock -- a DUMMY that becomes the heal or the damage spell
// of the same rank depending on the target -- but that script can never
// bind to an era copy: its Validate() demands a rank of WotLK's own chain
// (IsRankOf(20473)) and WotLK's heal/damage ranks. This resolves the same
// rank within the ERA's chains instead (era copies of 25914 heal / 25912
// damage, built by build_era_spell_sql.py's emit_spell_ranks).
class spell_era_pal_holy_shock : public SpellScript
{
    PrepareSpellScript(spell_era_pal_holy_shock);

    static constexpr uint32 HOLY_SHOCK_DAMAGE_R1 = 25912;
    static constexpr uint32 HOLY_SHOCK_HEALING_R1 = 25914;

    uint32 RankedEraSpell(uint32 wotlkFirstRank)
    {
        uint32 const first = EraSpellFor(EraOfSpell(GetSpellInfo()->Id), wotlkFirstRank);
        return first ? sSpellMgr->GetSpellWithRank(first, GetSpellInfo()->GetRank(), false) : 0;
    }

    bool Validate(SpellInfo const* spellInfo) override
    {
        Era const era = EraOfSpell(spellInfo->Id);
        return era != ERA_WOTLK && EraSpellFor(era, HOLY_SHOCK_DAMAGE_R1) && EraSpellFor(era, HOLY_SHOCK_HEALING_R1);
    }

    SpellCastResult CheckCast()
    {
        Unit* caster = GetCaster();
        Unit* target = GetExplTargetUnit();
        if (!target)
            return SPELL_FAILED_BAD_TARGETS;
        if (!caster->IsFriendlyTo(target))
        {
            if (!caster->IsValidAttackTarget(target))
                return SPELL_FAILED_BAD_TARGETS;
            if (!caster->isInFront(target))
                return SPELL_FAILED_UNIT_NOT_INFRONT;
        }
        return SPELL_CAST_OK;
    }

    void HandleDummy(SpellEffIndex /*effIndex*/)
    {
        Unit* caster = GetCaster();
        Unit* target = GetHitUnit();
        if (!target)
            return;
        uint32 const spell = RankedEraSpell(caster->IsFriendlyTo(target) ? HOLY_SHOCK_HEALING_R1 : HOLY_SHOCK_DAMAGE_R1);
        if (spell)
            caster->CastSpell(target, spell, true);
    }

    void Register() override
    {
        OnCheckCast += SpellCheckCastFn(spell_era_pal_holy_shock::CheckCast);
        OnEffectHitTarget += SpellEffectFn(spell_era_pal_holy_shock::HandleDummy, EFFECT_0, SPELL_EFFECT_DUMMY);
    }
};

// Cold Snap (Vanilla 12472 / TBC 11958): "When activated, this spell
// finishes the cooldown on all of your Frost spells." The same job as
// WotLK's spell_mage_cold_snap, which cannot be reused: it spares only
// WotLK Cold Snap's own id (11958), so on an era copy -- itself a Frost mage
// spell with a cooldown -- it would reset its own cooldown too.
class spell_era_mag_cold_snap : public SpellScript
{
    PrepareSpellScript(spell_era_mag_cold_snap);

    bool Load() override
    {
        return GetCaster()->IsPlayer();
    }

    void HandleDummy(SpellEffIndex /*effIndex*/)
    {
        Player* caster = GetCaster()->ToPlayer();
        uint32 const self = GetSpellInfo()->Id;

        std::vector<uint32> reset;
        for (auto const& [spellId, _] : caster->GetSpellMap())
        {
            SpellInfo const* spellInfo = sSpellMgr->GetSpellInfo(spellId);
            if (spellInfo && spellId != self && spellInfo->SpellFamilyName == SPELLFAMILY_MAGE
                && (spellInfo->GetSchoolMask() & SPELL_SCHOOL_MASK_FROST) && spellInfo->GetRecoveryTime() > 0)
                reset.push_back(spellId);
        }

        for (uint32 spellId : reset)
        {
            auto const itr = caster->GetSpellCooldownMap().find(spellId);
            caster->RemoveSpellCooldown(spellId, itr != caster->GetSpellCooldownMap().end() && itr->second.needSendToClient);
        }
    }

    void Register() override
    {
        OnEffectHit += SpellEffectFn(spell_era_mag_cold_snap::HandleDummy, EFFECT_0, SPELL_EFFECT_DUMMY);
    }
};

// Furor (Vanilla/TBC 17056 chain): "Gives you $s1% chance to gain 10 Rage
// when you shapeshift into Bear and Dire Bear Form or 40 Energy when you
// shapeshift into Cat Form." Bound to the era Cat, Bear and Dire Bear Forms,
// since the talent itself never sees the shapeshift. The core's own Furor
// code (AuraEffect::HandleAuraModShapeshift) applies WotLK's Cat Form rule,
// "keep up to $s1 energy", so build_era_spells.py's ERA_HIDDEN_FROM_CORE
// moves the era talent out of the druid family that code searches.
class spell_era_dru_furor : public AuraScript
{
    PrepareAuraScript(spell_era_dru_furor);

    static constexpr uint32 FUROR_ICON = 238;
    static constexpr uint32 FUROR_RAGE = 17057;
    static constexpr uint32 FUROR_ENERGY = 17099;

    bool Validate(SpellInfo const* /*spellInfo*/) override
    {
        return ValidateSpellInfo({ FUROR_RAGE, FUROR_ENERGY });
    }

    void AfterApply(AuraEffect const* aurEff, AuraEffectHandleModes /*mode*/)
    {
        Unit* target = GetTarget();
        int32 chance = 0;
        for (AuraEffect const* eff : target->GetAuraEffectsByType(SPELL_AURA_DUMMY))
        {
            if (eff->GetEffIndex() == EFFECT_0 && eff->GetSpellInfo()->SpellIconID == FUROR_ICON
                && EraOfSpell(eff->GetId()) != ERA_WOTLK)
            {
                chance = eff->GetAmount();
                break;
            }
        }
        if (chance <= 0 || !roll_chance_i(chance))
            return;

        switch (aurEff->GetMiscValue())
        {
            case FORM_CAT:
                target->CastSpell(target, FUROR_ENERGY, true, nullptr, aurEff);
                break;
            case FORM_BEAR:
            case FORM_DIREBEAR:
                target->CastSpell(target, FUROR_RAGE, true, nullptr, aurEff);
                break;
            default:
                break;
        }
    }

    void Register() override
    {
        AfterEffectApply += AuraEffectApplyFn(spell_era_dru_furor::AfterApply, EFFECT_0, SPELL_AURA_MOD_SHAPESHIFT, AURA_EFFECT_HANDLE_REAL);
    }
};

// Improved Drain Soul (TBC 18213 chain): "Returns $s3% of your maximum mana
// if the target is killed by you while you drain its soul." WotLK's
// spell_warl_improved_drain_soul does this, but looks for WotLK's Drain Soul
// chain (1120) on the victim, which an era warlock never casts. This looks
// for the era's own Drain Soul instead. The proc row (a kill by a Drain Soul
// family spell) is kept by build_era_spell_sql.py's ERA_KEEP_PROCS.
class spell_era_warl_improved_drain_soul : public AuraScript
{
    PrepareAuraScript(spell_era_warl_improved_drain_soul);

    static constexpr uint32 DRAIN_SOUL_R1 = 1120;
    static constexpr uint32 IMPROVED_DRAIN_SOUL_MANA = 18371;

    bool Validate(SpellInfo const* spellInfo) override
    {
        return EraSpellFor(EraOfSpell(spellInfo->Id), DRAIN_SOUL_R1) && ValidateSpellInfo({ IMPROVED_DRAIN_SOUL_MANA });
    }

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        Unit* caster = eventInfo.GetActor();
        Unit* victim = eventInfo.GetActionTarget();
        uint32 const drainSoul = EraSpellFor(EraOfSpell(GetId()), DRAIN_SOUL_R1);
        return caster && victim && caster->HasActivePowerType(POWER_MANA)
            && victim->GetAuraApplicationOfRankedSpell(drainSoul, caster->GetGUID());
    }

    void HandleProc(ProcEventInfo& eventInfo)
    {
        PreventDefaultAction();
        Unit* caster = eventInfo.GetActor();
        int32 const amount = CalculatePct(caster->GetMaxPower(POWER_MANA), GetSpellInfo()->Effects[EFFECT_2].CalcValue());
        caster->CastCustomSpell(IMPROVED_DRAIN_SOUL_MANA, SPELLVALUE_BASE_POINT0, amount, caster, true);
    }

    void Register() override
    {
        DoCheckProc += AuraCheckProcFn(spell_era_warl_improved_drain_soul::CheckProc);
        OnProc += AuraProcFn(spell_era_warl_improved_drain_soul::HandleProc);
    }
};

void AddSC_era_spell_scripts()
{
    RegisterSpellScript(spell_era_dru_furor);
    RegisterSpellScript(spell_era_warl_improved_drain_soul);
    RegisterSpellScript(spell_era_mag_cold_snap);
    RegisterSpellScript(spell_era_pal_holy_shock);
    RegisterSpellScript(spell_era_pal_judgement);
    RegisterSpellScript(spell_era_hun_aspect_of_the_viper);
}

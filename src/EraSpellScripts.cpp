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
#include "Item.h"

#include <cstring>
#include <vector>

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

    /// An era judgement debuff this caster put on its target: Judgement of
    /// Light, Wisdom, the Crusader or Justice. Righteousness and Command
    /// deal damage and leave no aura.
    bool IsEraJudgementDebuff(Aura const* aura, Unit const* caster)
    {
        SpellInfo const* info = aura->GetSpellInfo();
        return EraOfSpell(aura->GetId()) != ERA_WOTLK && aura->GetCasterGUID() == caster->GetGUID()
            && info->SpellFamilyName == SPELLFAMILY_PALADIN && aura->GetMaxDuration() > 0
            && info->SpellName[0] && std::strncmp(info->SpellName[0], "Judgement of", 12) == 0;
    }

    /// "Only one Judgement per Paladin can be active at any one time." The
    /// core keeps that rule by SPELL_SPECIFIC_JUDGEMENT, which it gives only
    /// to WotLK's three debuff ids (SpellInfo.cpp, 20184-20186), so an era
    /// judgement stacked beside the paladin's previous one.
    void RemoveEraJudgements(Unit* caster, Unit* target)
    {
        std::vector<uint32> previous;
        for (auto const& [id, aurApp] : target->GetAppliedAuras())
            if (IsEraJudgementDebuff(aurApp->GetBase(), caster))
                previous.push_back(id);
        for (uint32 id : previous)
            target->RemoveAurasDueToSpell(id, caster->GetGUID());
    }
}

namespace
{
    /// Vanilla Judgement of Command is itself a DUMMY whose amount names the
    /// damage spell (20425 -> 20467), and the 1.12 core cast that by hand,
    /// "doubled if the target is stunned". Casting the dummy here did
    /// nothing. Every other judgement is cast as it is.
    void CastEraJudgement(Unit* caster, Unit* target, NekoEraSpells::Era era, uint32 judgement)
    {
        using namespace NekoEraSpells;
        SpellInfo const* info = sSpellMgr->GetSpellInfo(judgement);
        if (info && info->Effects[EFFECT_0].IsEffect(SPELL_EFFECT_DUMMY))
        {
            uint32 const named = static_cast<uint32>(info->Effects[EFFECT_0].CalcValue(caster));
            uint32 const damageSpell = EraSpellFor(era, named) ? EraSpellFor(era, named) : named;
            if (SpellInfo const* damageInfo = sSpellMgr->GetSpellInfo(damageSpell))
            {
                int32 damage = damageInfo->Effects[EFFECT_0].CalcValue(caster);
                if (target->HasUnitState(UNIT_STATE_STUNNED))
                    damage *= 2;
                caster->CastCustomSpell(damageSpell, SPELLVALUE_BASE_POINT0, damage, target, true);
                return;
            }
        }
        caster->CastSpell(target, judgement, true);
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

        RemoveEraJudgements(caster, target);
        CastEraJudgement(caster, target, era, judgement);

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

// Seal of Righteousness (Vanilla 21084 / 20154, 20287-20293): "granting
// each melee attack an additional $/87;s1 to $/25;s1 Holy damage. Slower
// weapons cause more Holy damage per swing." The seal is a melee-hit DUMMY
// the 1.12 core turned into damage, so the numbers are that core's, as
// vmangos has them: the seal's own amount over 87 for a 1.5 speed weapon,
// over 25 for a 4.0 one, straight line between; Improved Seal of
// Righteousness adds its percent to that base; spell damage adds 10% (one-
// hand) or 12.5% (two-hand) of Holy spell power. WotLK's
// spell_pal_seal_of_righteousness is the 3.0 formula (AP and spell power by
// weapon speed) and was only bound to rank 1, so ranks 2-8 never hit.
class spell_era_pal_seal_of_righteousness : public AuraScript
{
    PrepareAuraScript(spell_era_pal_seal_of_righteousness);

    static constexpr uint32 SEAL_OF_RIGHTEOUSNESS_DAMAGE = 25742;
    static constexpr uint32 IMPROVED_SEAL_OF_RIGHTEOUSNESS[] = { 20224, 20225, 20330, 20331, 20332 };
    static constexpr float MIN_SPEED = 1.5f;
    static constexpr float MAX_SPEED = 4.0f;

    bool Validate(SpellInfo const* /*spellInfo*/) override
    {
        return ValidateSpellInfo({ SEAL_OF_RIGHTEOUSNESS_DAMAGE });
    }

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        Unit* target = eventInfo.GetProcTarget();
        return GetTarget()->IsPlayer() && target && target->IsAlive();
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        PreventDefaultAction();

        Player* player = GetTarget()->ToPlayer();
        Unit* victim = eventInfo.GetProcTarget();
        Item const* weapon = player->GetWeaponForAttack(BASE_ATTACK, true);
        float const speed = weapon ? weapon->GetTemplate()->Delay / 1000.0f : BASE_ATTACK_TIME / 1000.0f;
        bool const twoHand = weapon && weapon->GetTemplate()->InventoryType == INVTYPE_2HWEAPON;

        float const amount = float(aurEff->GetAmount());
        float const minDamage = amount / 87.0f;
        float const maxDamage = amount / 25.0f;
        float damage = (maxDamage - minDamage) * ((speed - MIN_SPEED) / (MAX_SPEED - MIN_SPEED)) + minDamage;

        for (uint32 talent : IMPROVED_SEAL_OF_RIGHTEOUSNESS)
            if (AuraEffect const* improved = player->GetAuraEffect(talent, EFFECT_0))
                if (improved->GetAmount() > 0)
                    damage += damage * improved->GetAmount() / 100.0f;

        damage += player->SpellBaseDamageBonusDone(SPELL_SCHOOL_MASK_HOLY) * (twoHand ? 0.125f : 0.10f);

        int32 const bp = std::max<int32>(0, int32(damage + 0.5f));
        player->CastCustomSpell(SEAL_OF_RIGHTEOUSNESS_DAMAGE, SPELLVALUE_BASE_POINT0, bp, victim, true, nullptr, aurEff);
    }

    void Register() override
    {
        DoCheckProc += AuraCheckProcFn(spell_era_pal_seal_of_righteousness::CheckProc);
        OnEffectProc += AuraEffectProcFn(spell_era_pal_seal_of_righteousness::HandleProc, EFFECT_0, SPELL_AURA_DUMMY);
    }
};

// Judgement of Light / Wisdom (Vanilla and TBC, every rank): "Melee attacks
// made against you have a chance of causing the attacker to be healed for
// $20267s1" / "...of restoring $20268s1 of the attacker's mana". The era
// debuff's proc trigger was a DUMMY the 1.12/2.4.3 core swapped for the
// rank's heal or mana spell, cast by the ATTACKER on itself.
// build_era_spells.py (judgement_procs) points the clone's trigger at that
// spell's era copy; a plain proc would have the debuffed target cast it, so
// the mob would heal itself. This casts it from the attacker instead.
class spell_era_pal_judgement_of_light_wisdom : public AuraScript
{
    PrepareAuraScript(spell_era_pal_judgement_of_light_wisdom);

    static constexpr uint32 JUDGEMENT = 20271;

    bool CheckProc(ProcEventInfo& eventInfo)
    {
        Unit* attacker = eventInfo.GetActor();
        if (!attacker || attacker == GetTarget() || !attacker->IsAlive())
            return false;
        // The Judgement that applies this debuff is a melee-class hit on the
        // target too, so it would trigger its own heal or mana return.
        if (SpellInfo const* spell = eventInfo.GetSpellInfo())
            if (spell->Id == GetId() || BaseSpellOf(spell->Id) == JUDGEMENT)
                return false;
        return true;
    }

    void HandleProc(AuraEffect const* aurEff, ProcEventInfo& eventInfo)
    {
        PreventDefaultAction();

        Unit* attacker = eventInfo.GetActor();
        uint32 const procSpell = aurEff->GetSpellInfo()->Effects[aurEff->GetEffIndex()].TriggerSpell;
        if (!sSpellMgr->GetSpellInfo(procSpell))
            return;
        attacker->CastSpell(attacker, procSpell, true, nullptr, aurEff);
    }

    void Register() override
    {
        DoCheckProc += AuraCheckProcFn(spell_era_pal_judgement_of_light_wisdom::CheckProc);
        OnEffectProc += AuraEffectProcFn(spell_era_pal_judgement_of_light_wisdom::HandleProc, EFFECT_0, SPELL_AURA_PROC_TRIGGER_SPELL);
    }
};

// The hit spell 25742 the Vanilla seal above casts. The core adds the
// target's "Holy damage taken" (Judgement of the Crusader) with 25742's own
// coefficient, and 25742 has no spell_bonus_data, so that is the instant-cast
// default of 1.5/3.5: JotC rank 3's +50 put ~21 on every swing where 1.12
// added the seal's 10%. A spell_bonus_data row cannot fix that: the core
// reads the same row for the caster's spell power as well, which the seal
// script already adds, and WotLK's Seal of Righteousness casts 25742 too.
// So this rescales the taken bonus on hits from a Vanilla seal only. OnHit
// runs before crit, resist and absorb, so they still apply to the result.
class spell_era_pal_seal_of_righteousness_damage : public SpellScript
{
    PrepareSpellScript(spell_era_pal_seal_of_righteousness_damage);

    void HandleHit()
    {
        SpellInfo const* seal = GetTriggeringSpell();
        Unit* caster = GetCaster();
        Unit* target = GetHitUnit();
        if (!seal || EraOfSpell(seal->Id) != ERA_VANILLA || !caster || !target || !caster->IsPlayer())
            return;

        // The taken bonus alone, already multiplied by the target's percent
        // taken modifiers: (0 + benefit * coeff) * mod.
        SpellInfo const* spellInfo = GetSpellInfo();
        int32 const takenBonus = int32(target->SpellDamageBonusTaken(caster, spellInfo, 0, SPELL_DIRECT_DAMAGE));
        float const defaultCoeff = caster->CalculateDefaultCoefficient(spellInfo, SPELL_DIRECT_DAMAGE);
        if (takenBonus <= 0 || defaultCoeff <= 0.0f)
            return;

        Item const* weapon = caster->ToPlayer()->GetWeaponForAttack(BASE_ATTACK, true);
        float const eraCoeff = weapon && weapon->GetTemplate()->InventoryType == INVTYPE_2HWEAPON ? 0.125f : 0.10f;

        int32 const excess = int32(takenBonus * (1.0f - eraCoeff / defaultCoeff) + 0.5f);
        SetHitDamage(std::max(0, GetHitDamage() - excess));
    }

    void Register() override
    {
        OnHit += SpellHitFn(spell_era_pal_seal_of_righteousness_damage::HandleHit);
    }
};

// Divine Shield, Divine Protection, Blessing of Protection (Vanilla): "Once
// protected, the target cannot be made invulnerable by Divine Shield, Divine
// Protection or Blessing of Protection again for $25771d." -- the era's own
// Forbearance, 1 minute where WotLK's lasts 2, and nothing about Avenging
// Wrath, which Vanilla did not have. Replaces WotLK's spell_pal_immunities.
class spell_era_pal_immunities : public SpellScript
{
    PrepareSpellScript(spell_era_pal_immunities);

    static constexpr uint32 FORBEARANCE = 25771;

    uint32 Forbearance()
    {
        uint32 const eraCopy = EraSpellFor(EraOfSpell(GetSpellInfo()->Id), FORBEARANCE);
        return eraCopy ? eraCopy : FORBEARANCE;
    }

    bool Validate(SpellInfo const* /*spellInfo*/) override
    {
        return ValidateSpellInfo({ FORBEARANCE });
    }

    SpellCastResult CheckCast()
    {
        Unit* target = GetExplTargetUnit();
        if (!target)
            target = GetCaster();
        if (target->HasAura(Forbearance()))
            return SPELL_FAILED_TARGET_AURASTATE;
        return SPELL_CAST_OK;
    }

    void ApplyForbearance()
    {
        if (Unit* target = GetHitUnit())
            GetCaster()->AddAura(Forbearance(), target);
    }

    void Register() override
    {
        OnCheckCast += SpellCheckCastFn(spell_era_pal_immunities::CheckCast);
        AfterHit += SpellHitFn(spell_era_pal_immunities::ApplyForbearance);
    }
};

// Every era judgement debuff: "Your melee strikes will refresh the spell's
// duration" (the Vanilla and TBC seal tooltips). The 1.12/2.4.3 core did
// this on each melee hit the judging paladin landed; AzerothCore has no such
// rule, so the debuff ran out after its 10 sec however often the paladin hit.
// DIRECT_DAMAGE is a white swing, and DealMeleeDamage only deals it when the
// swing landed (a miss, dodge or parry never gets here).
class era_pal_judgement_refresh : public UnitScript
{
public:
    era_pal_judgement_refresh() : UnitScript("era_pal_judgement_refresh") { }

    uint32 DealDamage(Unit* attacker, Unit* victim, uint32 damage, DamageEffectType damagetype) override
    {
        if (damagetype != DIRECT_DAMAGE || !attacker || !victim || attacker == victim
            || !attacker->IsPlayer() || attacker->getClass() != CLASS_PALADIN)
            return damage;

        for (auto const& [id, aurApp] : victim->GetAppliedAuras())
            if (IsEraJudgementDebuff(aurApp->GetBase(), attacker))
                aurApp->GetBase()->RefreshDuration();
        return damage;
    }
};

void AddSC_era_spell_scripts()
{
    new era_pal_judgement_refresh();
    RegisterSpellScript(spell_era_pal_seal_of_righteousness);
    RegisterSpellScript(spell_era_pal_seal_of_righteousness_damage);
    RegisterSpellScript(spell_era_pal_immunities);
    RegisterSpellScript(spell_era_dru_furor);
    RegisterSpellScript(spell_era_warl_improved_drain_soul);
    RegisterSpellScript(spell_era_mag_cold_snap);
    RegisterSpellScript(spell_era_pal_holy_shock);
    RegisterSpellScript(spell_era_pal_judgement);
    RegisterSpellScript(spell_era_pal_judgement_of_light_wisdom);
    RegisterSpellScript(spell_era_hun_aspect_of_the_viper);
}

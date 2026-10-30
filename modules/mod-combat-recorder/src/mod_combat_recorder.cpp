/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 *
 * mod-combat-recorder -- a diagnostic firehose for "why is combat broken for
 * this player" reports.
 *
 * NekoLog (src/NekoLog.cpp) is the player-facing boss log: bosses only,
 * database-backed, deliberately small. This is the opposite: every combat
 * event that involves a player (or their pet/guardian/charm), trash and
 * open world included, written as one JSON object per line to
 * <LogsDir>/CombatRecorder/combat-YYYY-MM-DD.jsonl, so a report can be
 * answered by grepping one player's fight instead of guessing.
 *
 * Events ("e"), all carry t (unix ms), map, inst, and the actors as
 * a/v ({g: guid, n: name, ent: entry or 0 for players, lvl, hp, mhp}):
 *   snap      full state of a player or creature: stats, armor, resists,
 *             defensive/crit %, equipped item entries, auras, and for
 *             creatures the AutoBalance multipliers. Written when a unit
 *             enters combat and every SnapshotIntervalMs while in combat.
 *   enter / exit / death
 *   dmg       OnDamage -- the FINAL amount after armor/absorb/resist.
 *   melee_mod / spell_mod / dot_mod
 *             the pre-OnDamage amount from the calculation step (spell id
 *             where there is one). Compare with the dmg line that follows
 *             to see what mitigation / scripts did.
 *   heal / heal_mod
 *   roll      melee outcome inputs: skills, crit/miss/dodge/parry/block
 *             chances (x100) the roll is about to use. RollData.
 *   aura_on / aura_off   spell, stacks, duration, caster, remove mode.
 *   cast      player spell casts (spell, target, cast time).
 *
 * Not captured: crit/miss/absorb RESULTS (they only exist at the SMSG_*
 * packet builders, same gap NekoLog documents). The roll inputs plus the
 * resulting dmg lines are the closest this hook set gets.
 *
 * Cost: when disabled every hook returns on one bool. When enabled, lines
 * are built outside the lock, appended under it, and written by the world
 * thread every FlushMs, never on a map thread.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "Pet.h"
#include "Spell.h"
#include "SpellAuras.h"
#include "SpellInfo.h"
#include "Map.h"
#include "Item.h"
#include "ObjectAccessor.h"
#include "Config.h"
#include "GameTime.h"
#include "Log.h"
#include "StringFormat.h"
#include "ABCreatureInfo.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace
{
    bool     Enable          = false;
    bool     RollData        = true;
    bool     IncludeCreatures = true;   // snapshots of the creatures fought
    uint32   SnapshotMs      = 2000;
    uint32   FlushMs         = 1000;
    uint32   MaxBufferBytes  = 8u * 1024 * 1024;
    std::string OutDir;
    std::unordered_set<std::string> NameFilter;   // lower-case; empty = everyone

    std::mutex              BufLock;
    std::string             Buf;
    uint64                  Dropped = 0;

    // Players currently in combat -> ms since their last snapshot. World thread only
    // for iteration; guarded because Enter/Leave hooks come from map threads.
    std::mutex                              CombatLock;
    std::unordered_map<uint64, uint32>      InCombat;
    std::unordered_set<uint64>              CreatureSeen;   // creatures already snapshotted

    uint64 NowMs()
    {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }

    std::string Esc(std::string const& s)
    {
        std::string o;
        o.reserve(s.size() + 2);
        for (char c : s)
        {
            if (c == '"' || c == '\\') { o += '\\'; o += c; }
            else if (static_cast<unsigned char>(c) < 0x20) o += ' ';
            else o += c;
        }
        return o;
    }

    // The player this unit answers to (itself, owner of a pet/guardian, charmer), or null.
    Player* PlayerOf(Unit const* u)
    {
        return u ? const_cast<Unit*>(u)->GetCharmerOrOwnerPlayerOrPlayerItself() : nullptr;
    }

    bool Wanted(Unit const* a, Unit const* b)
    {
        if (!Enable)
            return false;
        Player* pa = PlayerOf(a);
        Player* pb = PlayerOf(b);
        if (!pa && !pb)
            return false;
        if (NameFilter.empty())
            return true;
        auto match = [](Player* p)
        {
            if (!p)
                return false;
            std::string n = p->GetName();
            std::transform(n.begin(), n.end(), n.begin(), ::tolower);
            return NameFilter.count(n) > 0;
        };
        return match(pa) || match(pb);
    }

    std::string Actor(char const* key, Unit const* u)
    {
        if (!u)
            return {};
        return Acore::StringFormat(",\"{}\":{{\"g\":{},\"n\":\"{}\",\"ent\":{},\"lvl\":{},\"hp\":{},\"mhp\":{}}}",
            key, u->GetGUID().GetRawValue(), Esc(u->GetName()),
            u->IsPlayer() ? 0 : u->GetEntry(), u->GetLevel(), u->GetHealth(), u->GetMaxHealth());
    }

    // Opens a line; caller appends more fields and calls Emit().
    std::string Head(char const* ev, Unit const* a, Unit const* v)
    {
        Map const* m = (a ? a : v)->GetMap();
        return Acore::StringFormat("{{\"t\":{},\"e\":\"{}\",\"map\":{},\"inst\":{},\"diff\":{},\"pc\":{}{}{}",
            NowMs(), ev, m ? m->GetId() : 0, m ? m->GetInstanceId() : 0,
            m ? uint32(m->GetDifficulty()) : 0, m ? m->GetPlayersCountExceptGMs() : 0,
            Actor("a", a), Actor("v", v));
    }

    void Emit(std::string&& line)
    {
        line += "}\n";
        std::lock_guard<std::mutex> g(BufLock);
        if (Buf.size() + line.size() > MaxBufferBytes)
        {
            ++Dropped;
            return;
        }
        Buf += line;
    }

    std::string Auras(Unit const* u)
    {
        std::string o = ",\"auras\":[";
        bool first = true;
        for (auto const& [id, app] : const_cast<Unit*>(u)->GetAppliedAuras())
        {
            Aura const* au = app->GetBase();
            if (!au)
                continue;
            if (!first)
                o += ',';
            first = false;
            o += Acore::StringFormat("[{},{},{},{}]", au->GetId(), au->GetStackAmount(),
                au->GetDuration(), au->GetCasterGUID().GetRawValue());
        }
        return o + "]";
    }

    void Snapshot(Unit* u, char const* why)
    {
        if (!u || !u->IsInWorld())
            return;
        std::string l = Head("snap", u, nullptr);
        l += Acore::StringFormat(",\"why\":\"{}\",\"x\":{:.1f},\"y\":{:.1f},\"z\":{:.1f},\"zone\":{},\"area\":{},\"spd\":{:.2f},\"scale\":{:.2f}",
            why, u->GetPositionX(), u->GetPositionY(), u->GetPositionZ(), u->GetZoneId(), u->GetAreaId(),
            u->GetSpeed(MOVE_RUN), u->GetObjectScale());
        l += Acore::StringFormat(",\"armor\":{},\"res\":[{},{},{},{},{},{}],\"str\":[{},{},{},{},{}]",
            u->GetArmor(), u->GetResistance(SPELL_SCHOOL_HOLY), u->GetResistance(SPELL_SCHOOL_FIRE),
            u->GetResistance(SPELL_SCHOOL_NATURE), u->GetResistance(SPELL_SCHOOL_FROST),
            u->GetResistance(SPELL_SCHOOL_SHADOW), u->GetResistance(SPELL_SCHOOL_ARCANE),
            u->GetStat(STAT_STRENGTH), u->GetStat(STAT_AGILITY), u->GetStat(STAT_STAMINA),
            u->GetStat(STAT_INTELLECT), u->GetStat(STAT_SPIRIT));
        l += Acore::StringFormat(",\"pow\":[{},{}],\"ptype\":{},\"ap\":{:.0f},\"rap\":{:.0f},\"form\":{},\"flags\":{},\"unitstate\":{}",
            u->GetPower(u->getPowerType()), u->GetMaxPower(u->getPowerType()), uint32(u->getPowerType()),
            u->GetTotalAttackPowerValue(BASE_ATTACK), u->GetTotalAttackPowerValue(RANGED_ATTACK),
            uint32(u->GetShapeshiftForm()), u->GetUInt32Value(UNIT_FIELD_FLAGS), u->GetUnitState());
        l += Acore::StringFormat(",\"dmg\":[{:.1f},{:.1f}],\"atkspeed\":{}",
            u->GetFloatValue(UNIT_FIELD_MINDAMAGE), u->GetFloatValue(UNIT_FIELD_MAXDAMAGE),
            u->GetAttackTime(BASE_ATTACK));

        if (Player* p = u->ToPlayer())
        {
            l += Acore::StringFormat(",\"class\":{},\"race\":{},\"crit\":{:.2f},\"rcrit\":{:.2f},\"dodge\":{:.2f},\"parry\":{:.2f},\"block\":{:.2f}",
                uint32(p->getClass()), uint32(p->getRace()), p->GetFloatValue(PLAYER_CRIT_PERCENTAGE),
                p->GetFloatValue(PLAYER_RANGED_CRIT_PERCENTAGE), p->GetFloatValue(PLAYER_DODGE_PERCENTAGE),
                p->GetFloatValue(PLAYER_PARRY_PERCENTAGE), p->GetFloatValue(PLAYER_BLOCK_PERCENTAGE));
            l += Acore::StringFormat(",\"spcrit\":[{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f}],\"sp\":{},\"heal\":{}",
                p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 1), p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 2),
                p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 3), p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 4),
                p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 5), p->GetFloatValue(PLAYER_SPELL_CRIT_PERCENTAGE1 + 6),
                p->SpellBaseDamageBonusDone(SPELL_SCHOOL_MASK_MAGIC), p->SpellBaseHealingBonusDone(SPELL_SCHOOL_MASK_MAGIC));
            l += ",\"gear\":[";
            for (uint8 s = EQUIPMENT_SLOT_START; s < EQUIPMENT_SLOT_END; ++s)
            {
                Item* it = p->GetItemByPos(INVENTORY_SLOT_BAG_0, s);
                l += Acore::StringFormat("{}{}", s == EQUIPMENT_SLOT_START ? "" : ",", it ? it->GetEntry() : 0);
            }
            l += "]";
            Group* grp = p->GetGroup();
            l += Acore::StringFormat(",\"grp\":{},\"raid\":{}", grp ? grp->GetMembersCount() : 1,
                grp && grp->isRaidGroup() ? 1 : 0);
        }
        else if (Creature* c = u->ToCreature())
        {
            l += Acore::StringFormat(",\"rank\":{},\"family\":{},\"cflagsx\":{},\"ai\":\"{}\"",
                uint32(c->GetCreatureTemplate()->rank), uint32(c->GetCreatureTemplate()->family),
                c->GetCreatureTemplate()->flags_extra, Esc(c->GetAIName()));
            l += Acore::StringFormat(",\"script\":\"{}\",\"victim\":{}", Esc(c->GetScriptName()),
                c->GetVictim() ? c->GetVictim()->GetGUID().GetRawValue() : 0);
            if (auto* ab = c->CustomData.Get<AutoBalanceCreatureInfo>("AutoBalanceCreatureInfo"))
            {
                l += Acore::StringFormat(",\"ab\":{{\"pc\":{},\"dmg\":{:.3f},\"sdmg\":{:.3f},\"hp\":{:.3f},\"shp\":{:.3f},\"mana\":{:.3f},\"armor\":{:.3f},\"cc\":{:.3f}}}",
                    ab->instancePlayerCount, ab->DamageMultiplier, ab->ScaledDamageMultiplier,
                    ab->HealthMultiplier, ab->ScaledHealthMultiplier, ab->ManaMultiplier,
                    ab->ArmorMultiplier, ab->CCDurationMultiplier);
            }
        }
        l += Auras(u);
        Emit(std::move(l));
    }

    // Snapshot a creature the first time it shows up in a fight (until it dies/exits combat).
    void TrackCreature(Unit* u)
    {
        if (!IncludeCreatures || !u || u->IsPlayer() || PlayerOf(u))
            return;
        bool fresh;
        {
            std::lock_guard<std::mutex> g(CombatLock);
            fresh = CreatureSeen.insert(u->GetGUID().GetRawValue()).second;
        }
        if (fresh)
            Snapshot(u, "first_seen");
    }

    void FlushToDisk()
    {
        std::string out;
        uint64 dropped;
        {
            std::lock_guard<std::mutex> g(BufLock);
            out.swap(Buf);
            dropped = Dropped;
            Dropped = 0;
        }
        if (dropped)
            out += Acore::StringFormat("{{\"t\":{},\"e\":\"dropped\",\"n\":{}}}\n", NowMs(), dropped);
        if (out.empty())
            return;

        std::time_t now = std::time(nullptr);
        std::tm tm{};
        localtime_r(&now, &tm);
        char day[16];
        std::strftime(day, sizeof(day), "%Y-%m-%d", &tm);
        std::string path = Acore::StringFormat("{}/combat-{}.jsonl", OutDir, day);
        if (FILE* f = std::fopen(path.c_str(), "ab"))
        {
            std::fwrite(out.data(), 1, out.size(), f);
            std::fclose(f);
        }
        else
            LOG_ERROR("module", "mod-combat-recorder: cannot append to {}", path);
    }

    void LoadConfig()
    {
        Enable           = sConfigMgr->GetOption<bool>("CombatRecorder.Enable", false);
        RollData         = sConfigMgr->GetOption<bool>("CombatRecorder.RollData", true);
        IncludeCreatures = sConfigMgr->GetOption<bool>("CombatRecorder.CreatureSnapshots", true);
        SnapshotMs       = sConfigMgr->GetOption<uint32>("CombatRecorder.SnapshotIntervalMs", 2000);
        FlushMs          = std::max<uint32>(100, sConfigMgr->GetOption<uint32>("CombatRecorder.FlushMs", 1000));
        MaxBufferBytes   = sConfigMgr->GetOption<uint32>("CombatRecorder.MaxBufferMB", 8) * 1024 * 1024;

        NameFilter.clear();
        std::string names = sConfigMgr->GetOption<std::string>("CombatRecorder.Players", "");
        size_t pos = 0;
        while (pos <= names.size())
        {
            size_t end = names.find(',', pos);
            if (end == std::string::npos)
                end = names.size();
            std::string n = names.substr(pos, end - pos);
            n.erase(std::remove_if(n.begin(), n.end(), ::isspace), n.end());
            std::transform(n.begin(), n.end(), n.begin(), ::tolower);
            if (!n.empty())
                NameFilter.insert(n);
            pos = end + 1;
        }

        std::string logs = sConfigMgr->GetOption<std::string>("LogsDir", "");
        OutDir = (logs.empty() ? std::string(".") : logs) + "/CombatRecorder";
        std::error_code ec;
        std::filesystem::create_directories(OutDir, ec);
        if (Enable)
            LOG_INFO("module", "mod-combat-recorder: ON -> {} ({})", OutDir,
                NameFilter.empty() ? "all players" : "filtered by name");
    }
}

class CombatRecorder_World : public WorldScript
{
public:
    CombatRecorder_World() : WorldScript("CombatRecorder_World", { WORLDHOOK_ON_AFTER_CONFIG_LOAD, WORLDHOOK_ON_UPDATE, WORLDHOOK_ON_SHUTDOWN }) { }

    void OnAfterConfigLoad(bool /*reload*/) override { LoadConfig(); }

    void OnUpdate(uint32 diff) override
    {
        if (!Enable)
            return;

        if (SnapshotMs)
        {
            std::vector<uint64> due;
            {
                std::lock_guard<std::mutex> g(CombatLock);
                for (auto& [guid, ms] : InCombat)
                {
                    ms += diff;
                    if (ms >= SnapshotMs)
                    {
                        ms = 0;
                        due.push_back(guid);
                    }
                }
            }
            for (uint64 raw : due)
            {
                if (Player* p = ObjectAccessor::FindPlayer(ObjectGuid(raw)))
                    if (p->IsInCombat())
                        Snapshot(p, "tick");
            }
        }

        static uint32 acc = 0;
        acc += diff;
        if (acc >= FlushMs)
        {
            acc = 0;
            FlushToDisk();
        }
    }

    void OnShutdown() override { FlushToDisk(); }
};

class CombatRecorder_Unit : public UnitScript
{
public:
    CombatRecorder_Unit() : UnitScript("CombatRecorder_Unit", true, {
        UNITHOOK_ON_DAMAGE, UNITHOOK_ON_HEAL, UNITHOOK_MODIFY_MELEE_DAMAGE, UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN,
        UNITHOOK_MODIFY_PERIODIC_DAMAGE_AURAS_TICK, UNITHOOK_MODIFY_HEAL_RECEIVED,
        UNITHOOK_ON_BEFORE_ROLL_MELEE_OUTCOME_AGAINST, UNITHOOK_ON_AURA_APPLY, UNITHOOK_ON_AURA_REMOVE,
        UNITHOOK_ON_UNIT_ENTER_COMBAT, UNITHOOK_ON_UNIT_EXIT_COMBAT, UNITHOOK_ON_UNIT_DEATH,
        UNITHOOK_ON_UNIT_ENTER_EVADE_MODE }) { }

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        if (!Wanted(attacker, victim))
            return;
        std::string l = Head("dmg", attacker, victim);
        l += Acore::StringFormat(",\"amt\":{}", damage);
        Emit(std::move(l));
        // First hit on a creature we haven't described yet.
        if (victim && !victim->IsPlayer())
            TrackCreature(victim);
    }

    void OnHeal(Unit* healer, Unit* receiver, uint32& gain) override
    {
        if (!Wanted(healer, receiver))
            return;
        std::string l = Head("heal", healer, receiver);
        l += Acore::StringFormat(",\"amt\":{}", gain);
        Emit(std::move(l));
    }

    void ModifyMeleeDamage(Unit* target, Unit* attacker, uint32& damage) override
    {
        if (!Wanted(attacker, target))
            return;
        std::string l = Head("melee_mod", attacker, target);
        l += Acore::StringFormat(",\"amt\":{}", damage);
        Emit(std::move(l));
    }

    void ModifySpellDamageTaken(Unit* target, Unit* attacker, int32& damage, SpellInfo const* spell) override
    {
        if (!Wanted(attacker, target))
            return;
        std::string l = Head("spell_mod", attacker, target);
        l += Acore::StringFormat(",\"amt\":{},\"spell\":{},\"school\":{}", damage,
            spell ? spell->Id : 0, spell ? spell->SchoolMask : 0);
        Emit(std::move(l));
    }

    void ModifyPeriodicDamageAurasTick(Unit* target, Unit* attacker, uint32& damage, SpellInfo const* spell) override
    {
        if (!Wanted(attacker, target))
            return;
        std::string l = Head("dot_mod", attacker ? attacker : target, attacker ? target : nullptr);
        l += Acore::StringFormat(",\"amt\":{},\"spell\":{},\"school\":{}", damage,
            spell ? spell->Id : 0, spell ? spell->SchoolMask : 0);
        Emit(std::move(l));
    }

    void ModifyHealReceived(Unit* target, Unit* healer, uint32& heal, SpellInfo const* spell) override
    {
        if (!Wanted(healer, target))
            return;
        std::string l = Head("heal_mod", healer ? healer : target, healer ? target : nullptr);
        l += Acore::StringFormat(",\"amt\":{},\"spell\":{}", heal, spell ? spell->Id : 0);
        Emit(std::move(l));
    }

    void OnBeforeRollMeleeOutcomeAgainst(Unit const* attacker, Unit const* victim, WeaponAttackType att,
        int32& attMax, int32& vicMax, int32& attSkill, int32& vicDef, int32& crit, int32& miss,
        int32& dodge, int32& parry, int32& block) override
    {
        if (!RollData || !Wanted(attacker, victim))
            return;
        std::string l = Head("roll", attacker, victim);
        l += Acore::StringFormat(",\"att\":{},\"skill\":[{},{},{},{}],\"chance\":{{\"crit\":{},\"miss\":{},\"dodge\":{},\"parry\":{},\"block\":{}}}",
            uint32(att), attMax, vicMax, attSkill, vicDef, crit, miss, dodge, parry, block);
        Emit(std::move(l));
    }

    void OnAuraApply(Unit* unit, Aura* aura) override
    {
        Unit* caster = aura ? aura->GetCaster() : nullptr;
        if (!aura || !Wanted(unit, caster))
            return;
        std::string l = Head("aura_on", unit, caster);
        l += Acore::StringFormat(",\"spell\":{},\"stacks\":{},\"dur\":{},\"maxdur\":{},\"flags\":{}",
            aura->GetId(), aura->GetStackAmount(), aura->GetDuration(), aura->GetMaxDuration(), aura->GetSpellInfo()->Attributes);
        Emit(std::move(l));
    }

    void OnAuraRemove(Unit* unit, AuraApplication* app, AuraRemoveMode mode) override
    {
        Aura const* aura = app ? app->GetBase() : nullptr;
        if (!aura || !Wanted(unit, nullptr))
            return;
        std::string l = Head("aura_off", unit, nullptr);
        l += Acore::StringFormat(",\"spell\":{},\"stacks\":{},\"mode\":{}", aura->GetId(), aura->GetStackAmount(), uint32(mode));
        Emit(std::move(l));
    }

    void OnUnitEnterCombat(Unit* unit, Unit* victim) override
    {
        if (!Wanted(unit, victim))
            return;
        std::string l = Head("enter", unit, victim);
        Emit(std::move(l));
        Snapshot(unit, "enter");
        if (victim)
            Snapshot(victim, "enter_target");
        TrackCreature(unit->IsPlayer() ? victim : unit);
        if (Player* p = unit->ToPlayer())
        {
            std::lock_guard<std::mutex> g(CombatLock);
            InCombat.emplace(p->GetGUID().GetRawValue(), 0);
        }
    }

    void OnUnitExitCombat(Unit* unit) override
    {
        if (!Wanted(unit, nullptr))
            return;
        Emit(Head("exit", unit, nullptr));
        std::lock_guard<std::mutex> g(CombatLock);
        InCombat.erase(unit->GetGUID().GetRawValue());
        CreatureSeen.erase(unit->GetGUID().GetRawValue());
    }

    void OnUnitDeath(Unit* unit, Unit* killer) override
    {
        if (!Wanted(unit, killer))
            return;
        Snapshot(unit, "death");
        Emit(Head("death", unit, killer));
        std::lock_guard<std::mutex> g(CombatLock);
        InCombat.erase(unit->GetGUID().GetRawValue());
        CreatureSeen.erase(unit->GetGUID().GetRawValue());
    }

    void OnUnitEnterEvadeMode(Unit* unit, uint8 reason) override
    {
        if (!Wanted(unit->GetVictim(), unit) && !Wanted(unit, nullptr))
            return;
        std::string l = Head("evade", unit, nullptr);
        l += Acore::StringFormat(",\"reason\":{}", uint32(reason));
        Emit(std::move(l));
    }
};

class CombatRecorder_Player : public PlayerScript
{
public:
    CombatRecorder_Player() : PlayerScript("CombatRecorder_Player", { PLAYERHOOK_ON_SPELL_CAST }) { }

    void OnPlayerSpellCast(Player* player, Spell* spell, bool skipCheck) override
    {
        if (!spell || !Wanted(player, nullptr))
            return;
        Unit* t = spell->m_targets.GetUnitTarget();
        std::string l = Head("cast", player, t);
        l += Acore::StringFormat(",\"spell\":{},\"casttime\":{},\"skipcheck\":{}", spell->GetSpellInfo()->Id,
            spell->GetCastTime(), skipCheck ? 1 : 0);
        Emit(std::move(l));
    }
};

void AddSC_mod_combat_recorder()
{
    new CombatRecorder_World();
    new CombatRecorder_Unit();
    new CombatRecorder_Player();
}

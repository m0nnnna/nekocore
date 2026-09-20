/*
 * NekoLog -- server-side combat logging for dungeons and raids.
 *
 * Why the server and not an addon: a 3.3.5a addon has no network access, so
 * the only thing it can produce is a SavedVariables text file anyone can
 * edit, and any "signature" it computes lives in readable Lua. The server
 * already sees every hit, heal, death and boss state change before any
 * client does, so it is the one place a log can't be forged from. Every
 * boss pull on the realm is recorded automatically; the website reads
 * the tables directly (data/sql/db-characters/base/nekolog.sql), nobody
 * uploads anything.
 *
 * What gets captured, and from which hook (all call sites checked in this
 * checkout's Unit.cpp / SpellAuraEffects.cpp / InstanceScript.cpp):
 *
 *   damage   UnitScript::OnDamage (Unit::DealDamage, the FINAL amount after
 *            armor/absorb/resist). That hook has no spell on it, so the
 *            spell/school/pre-mitigation amount is picked up one step
 *            earlier in the same call chain -- ModifySpellDamageTaken
 *            (CalculateSpellDamageTaken), ModifyMeleeDamage
 *            (CalculateMeleeDamage) or ModifyPeriodicDamageAurasTick (DoT
 *            ticks) -- and stashed in a thread_local until OnDamage consumes
 *            it. Maps update on their own threads, hence thread_local, not
 *            a global. A DealDamage with no stashed context (falling,
 *            environment, scripted SetHealth-style damage) logs as spell 0.
 *   heal     OnHeal (Unit::DealHeal, effective heal) + ModifyHealReceived
 *            (Unit::HealBySpell, the raw amount) the same way; extra =
 *            overheal.
 *   death    OnUnitDeath.
 *   cast     PlayerScript::OnPlayerSpellCast.
 *   auras    OnAuraApply / OnAuraRemove.
 *   encounter boundaries: a creature that is a dungeon/world boss entering
 *            combat opens one (OnUnitEnterCombat, called from
 *            Creature::EngageWithTarget's AI path); its death closes it as a
 *            kill (OnUnitDeath), its leaving combat alive closes it as a
 *            wipe/reset (OnUnitExitCombat); OnBeforeSetBossState DONE/FAIL
 *            from the instance script closes it the same way for scripted
 *            encounters where the "boss" creature isn't the thing that dies.
 *
 * Not captured yet (needs a core patch at the SMSG_* combat-log packet
 * builders, where crit/miss/absorb/block are actually known): crit flags,
 * misses/dodges/parries, per-shield absorb attribution, energize.
 *
 * Only boss encounters are recorded. Between pulls nothing is written at
 * all -- a run row is only created when the first boss of the instance
 * engages, and damage/heal/death/cast/aura events outside an open encounter
 * never reach the database. Trash is not a log.
 *
 * The one wrinkle: AzerothCore only flags a creature as a dungeon boss if
 * it is the one that gives encounter credit (instance_encounters ->
 * CREATURE_FLAG_EXTRA_DUNGEON_BOSS, set in ObjectMgr::LoadInstanceEncounters).
 * Some fights start with a creature that ISN'T the credited one -- Sneed's
 * Shredder dies and summons Sneed, who is the boss. To keep phase one, the
 * last PRE_WINDOW_MS of events per instance sit in a memory-only ring
 * buffer. When a boss engages and it is a temp-summon whose summoner is a
 * creature that entered combat inside that window, the encounter starts at
 * the summoner's pull and the buffered events from that point on are
 * promoted into it. The same applies to any creature that is still alive
 * and in combat when the boss engages -- adds pulled a moment before the
 * boss are part of the pull, not trash. Everything else in the buffer is
 * discarded, so a pack fully killed before the boss engaged stays out.
 *
 * End of an encounter: the boss's death (or SetBossState DONE) fixes the
 * kill time, but recording keeps going until every player on the map has
 * dropped combat (adds still up after the boss) or LINGER_MAX_MS passes,
 * whichever is first. The combat-dropped close is deferred by
 * COMBAT_OVER_GRACE_MS and cancelled if anyone re-enters combat: Unit::Kill
 * clears the victim's combat (which drops the players out of combat) BEFORE
 * it fires OnUnitDeath, so closing synchronously on leave-combat would lose
 * the last add's killing blow and death. A wipe/reset closes immediately.
 *
 * Storage: events buffer per run and are flushed as multi-row INSERTs
 * through CharacterDatabase's async queue (never on the map thread's
 * critical path) every few seconds or when the buffer fills. Ids for runs
 * and encounters are handed out from in-memory counters seeded from the
 * tables at startup so rows can be linked without waiting on the DB.
 *
 * Config: Nekocore.Log.Enable / Nekocore.Log.Auras / Nekocore.Log.Casts
 * (conf/nekocore.conf.dist), live-reloadable.
 */

#include "ScriptMgr.h"
#include "Player.h"
#include "Creature.h"
#include "Pet.h"
#include "TemporarySummon.h"
#include "ObjectAccessor.h"
#include "Map.h"
#include "InstanceScript.h"
#include "Spell.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "SpellAuras.h"
#include "DBCStores.h"
#include "DatabaseEnv.h"
#include "GameTime.h"
#include "Config.h"
#include "StringFormat.h"

#include "IndividualProgression.h"

#include <mutex>
#include <deque>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace
{
    bool logEnabled = true;
    bool logAuras   = true;
    bool logCasts   = true;

    constexpr uint32 FLUSH_INTERVAL_MS = 5000;
    constexpr size_t FLUSH_ROWS        = 400;   // rows per INSERT statement
    constexpr uint32 PRE_WINDOW_MS     = 180000; // memory-only look-back for summon-phase bosses
    constexpr uint32 LINGER_MAX_MS     = 90000;  // longest we keep recording after the boss dies
    constexpr uint32 COMBAT_OVER_GRACE_MS = 3000; // leave-combat -> close delay (see header)

    enum EventKind : uint8
    {
        EV_DAMAGE      = 1,
        EV_HEAL        = 2,
        EV_DEATH       = 3,
        EV_CAST        = 4,
        EV_AURA_APPLY  = 5,
        EV_AURA_REMOVE = 6,
    };

    enum ActorKind : uint8
    {
        ACTOR_PLAYER   = 1,
        ACTOR_PET      = 2,
        ACTOR_CREATURE = 3,
    };

    enum EncResult : uint8
    {
        RESULT_OPEN = 0,
        RESULT_KILL = 1,
        RESULT_WIPE = 2,
    };

    struct Event
    {
        uint32 t;
        uint8  kind;
        uint64 src;
        uint64 dst;
        uint32 spell;
        int32  amount;
        int32  extra;
        uint8  school;
        uint8  flags;
    };

    // Everything nekolog_actor needs, captured while the unit still exists
    // (a promoted pre-buffer event may refer to a creature that is dead and
    // gone by the time it is written).
    struct ActorInfo
    {
        uint64 guid = 0;
        uint8  kind = ACTOR_CREATURE;
        uint32 entry = 0;
        std::string name;
        uint8  cls = 0, race = 0, level = 0, spec = 0;
        uint64 owner = 0;
        uint32 charGuid = 0;
    };

    // Per-instance look-back buffer; never written to the DB unless promoted.
    struct PreBuffer
    {
        std::deque<Event> events;                       // Event::t is absolute NowMs()
        std::unordered_map<uint64, ActorInfo> actors;
        std::unordered_map<uint64, uint32> engagedMs;   // creature guid -> when it entered combat
    };

    struct Run
    {
        uint64 id = 0;
        uint32 startMs = 0;
        uint64 encId = 0;          // open encounter, 0 = none
        ObjectGuid encBoss;
        uint32 encStartMs = 0;
        uint32 encKillMs = 0;      // boss died at this time; still recording the tail
        uint32 encCombatOverMs = 0; // players dropped combat at this time; close after grace
        uint32 lastFlushMs = 0;
        std::vector<Event> buf;
        std::unordered_set<uint64> actorsWritten;
        uint16 kills = 0;
        uint16 wipes = 0;
    };

    // Damage/heal context handed from the Modify* hooks to OnDamage/OnHeal.
    struct HitContext
    {
        bool   valid = false;
        uint32 spell = 0;
        uint8  school = 0;
        uint32 raw = 0;
        bool   periodic = false;
    };
    thread_local HitContext tlsCtx;

    std::mutex runsMutex;
    std::unordered_map<uint64, Run> runs;       // key: map id << 32 | instance id
    std::unordered_map<uint64, PreBuffer> pre;  // same key; guarded by runsMutex
    std::unordered_set<uint32> spellsWritten;    // guarded by runsMutex
    uint64 nextRunId = 1;
    uint64 nextEncId = 1;

    uint64 RunKey(Map const* map)
    {
        return (uint64(map->GetId()) << 32) | map->GetInstanceId();
    }

    bool Loggable(Map const* map)
    {
        return logEnabled && map && map->IsDungeon();
    }

    uint32 NowMs()
    {
        return uint32(GameTime::GetGameTimeMS().count());
    }

    std::string Escaped(std::string s)
    {
        CharacterDatabase.EscapeString(s);
        return s;
    }

    // --- writers ---------------------------------------------------------

    void FlushEvents(Run& run)
    {
        if (run.buf.empty())
            return;

        std::string sql;
        size_t n = 0;
        for (Event const& ev : run.buf)
        {
            if (n == 0)
                sql = "INSERT INTO nekolog_event (run_id, enc_id, t_ms, kind, src, dst, spell, amount, extra, school, flags) VALUES ";
            else
                sql += ',';
            // Buffers are flushed on every encounter close, so everything in
            // here belongs to the encounter that is open right now.
            sql += Acore::StringFormat("({},{},{},{},{},{},{},{},{},{},{})",
                run.id, run.encId, ev.t, ev.kind, ev.src, ev.dst, ev.spell, ev.amount, ev.extra, ev.school, ev.flags);
            if (++n >= FLUSH_ROWS)
            {
                CharacterDatabase.Execute(sql);
                n = 0;
            }
        }
        if (n)
            CharacterDatabase.Execute(sql);

        run.buf.clear();
        run.lastFlushMs = NowMs();
    }

    void WriteSpell(uint32 spellId)
    {
        if (!spellId || !spellsWritten.insert(spellId).second)
            return;
        SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId);
        if (!info)
            return;
        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT IGNORE INTO nekolog_spell (id, name, school) VALUES ({},'{}',{})",
            spellId, Escaped(info->SpellName[0] ? info->SpellName[0] : ""), uint32(info->GetSchoolMask())));
    }

    ActorInfo Snapshot(Unit* unit)
    {
        ActorInfo a;
        a.guid = unit->GetGUID().GetRawValue();
        a.name = unit->GetName();
        a.level = uint8(unit->GetLevel());
        if (Player* p = unit->ToPlayer())
        {
            a.kind = ACTOR_PLAYER;
            a.cls = p->getClass();
            a.race = p->getRace();
            a.spec = p->GetMostPointsTalentTree();
            a.charGuid = p->GetGUID().GetCounter();
        }
        else if (Creature* c = unit->ToCreature())
        {
            a.entry = c->GetEntry();
            if (Unit* o = c->GetCharmerOrOwner())
                if (Player* op = o->GetCharmerOrOwnerPlayerOrPlayerItself())
                {
                    a.kind = ACTOR_PET;
                    a.owner = op->GetGUID().GetRawValue();
                }
        }
        return a;
    }

    void WriteActorInfo(Run& run, ActorInfo const& a)
    {
        if (!run.actorsWritten.insert(a.guid).second)
            return;
        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT IGNORE INTO nekolog_actor (run_id, guid, kind, entry, name, class, race, level, spec, owner, char_guid) "
            "VALUES ({},{},{},{},'{}',{},{},{},{},{},{})",
            run.id, a.guid, uint32(a.kind), a.entry, Escaped(a.name),
            uint32(a.cls), uint32(a.race), uint32(a.level), uint32(a.spec), a.owner, a.charGuid));
    }

    void WriteActor(Run& run, Unit* unit)
    {
        if (!unit || run.actorsWritten.count(unit->GetGUID().GetRawValue()))
            return;
        ActorInfo a = Snapshot(unit);
        if (a.kind == ACTOR_PET)
            if (Player* op = unit->GetCharmerOrOwnerPlayerOrPlayerItself())
                WriteActor(run, op);
        WriteActorInfo(run, a);
    }

    // Remember a unit in the pre-buffer's actor table (and its owner, for pets).
    void PreActor(PreBuffer& pb, Unit* unit)
    {
        if (!unit)
            return;
        uint64 guid = unit->GetGUID().GetRawValue();
        if (pb.actors.count(guid))
            return;
        ActorInfo a = Snapshot(unit);
        if (a.kind == ACTOR_PET)
            PreActor(pb, unit->GetCharmerOrOwnerPlayerOrPlayerItself());
        pb.actors.emplace(guid, std::move(a));
    }

    void TrimPre(PreBuffer& pb, uint32 now)
    {
        while (!pb.events.empty() && now - pb.events.front().t > PRE_WINDOW_MS)
            pb.events.pop_front();
        for (auto it = pb.engagedMs.begin(); it != pb.engagedMs.end();)
            it = (now - it->second > PRE_WINDOW_MS) ? pb.engagedMs.erase(it) : std::next(it);
        if (pb.events.empty() && pb.engagedMs.empty())
            pb.actors.clear();
    }

    // Must hold runsMutex.
    Run& GetOrOpenRun(Map* map, uint32 startMs)
    {
        uint64 key = RunKey(map);
        auto it = runs.find(key);
        if (it != runs.end())
            return it->second;

        Run& run = runs[key];
        run.id = nextRunId++;
        run.startMs = startMs;
        run.lastFlushMs = NowMs();

        MapEntry const* entry = sMapStore.LookupEntry(map->GetId());
        std::string name = entry && entry->name[0] ? entry->name[0] : "";
        uint32 maxPlayers = map->ToInstanceMap() ? map->ToInstanceMap()->GetMaxPlayers() : 0;
        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT INTO nekolog_run (id, map_id, instance_id, map_name, spawn_mode, is_raid, max_players, started_at) "
            "VALUES ({},{},{},'{}',{},{},{},{})",
            run.id, map->GetId(), map->GetInstanceId(), Escaped(name), uint32(map->GetSpawnMode()),
            uint32(map->IsRaid() ? 1 : 0), maxPlayers, uint32(GameTime::GetGameTime().count()) - (NowMs() - startMs) / 1000));
        return run;
    }

    // Must hold runsMutex. The run with an open encounter on this map, or
    // nullptr -- everything outside a boss pull is ignored.
    Run* OpenEncounterRun(Map* map)
    {
        auto it = runs.find(RunKey(map));
        return (it != runs.end() && it->second.encId) ? &it->second : nullptr;
    }

    // Must hold runsMutex. Inside an open encounter the event is queued for
    // the DB; otherwise it only goes to the map's memory-only pre-buffer,
    // where it is dropped unless a summon-phase boss promotes it.
    void Record(Map* map, Unit* src, Unit* dst, uint8 kind, uint32 spell, int32 amount, int32 extra, uint8 school, uint8 flags)
    {
        uint32 now = NowMs();
        Event ev{ now, kind,
            src ? src->GetGUID().GetRawValue() : 0,
            dst ? dst->GetGUID().GetRawValue() : 0,
            spell, amount, extra, school, flags };

        if (Run* run = OpenEncounterRun(map))
        {
            WriteActor(*run, src);
            WriteActor(*run, dst);
            WriteSpell(spell);
            ev.t = now - run->startMs;
            run->buf.push_back(ev);
            if (run->buf.size() >= FLUSH_ROWS)
                FlushEvents(*run);
            return;
        }

        PreBuffer& pb = pre[RunKey(map)];
        TrimPre(pb, now);
        PreActor(pb, src);
        PreActor(pb, dst);
        pb.events.push_back(ev);
    }

    // Must hold runsMutex. Called from OnUnitEnterCombat for a boss with no
    // encounter open on its map.
    void OpenEncounter(Map* map, Creature* boss)
    {
        uint32 now = NowMs();
        uint32 startMs = now;
        PreBuffer* pb = nullptr;
        auto pit = pre.find(RunKey(map));
        if (pit != pre.end())
        {
            pb = &pit->second;
            TrimPre(*pb, now);
            // Summon-phase boss (Sneed's Shredder -> Sneed): start at the summoner's pull.
            if (TempSummon* ts = boss->ToTempSummon())
            {
                ObjectGuid summoner = ts->GetSummonerGUID();
                if (summoner.IsCreatureOrVehicle())
                {
                    auto eit = pb->engagedMs.find(summoner.GetRawValue());
                    if (eit != pb->engagedMs.end())
                        startMs = std::min(startMs, eit->second);
                }
            }
            // Anything still alive and fighting when the boss engages is part
            // of this pull: start at the earliest of those pulls.
            for (auto const& [guid, engaged] : pb->engagedMs)
            {
                if (guid == boss->GetGUID().GetRawValue())
                    continue;
                Creature* c = ObjectAccessor::GetCreature(*boss, ObjectGuid(guid));
                if (c && c->IsAlive() && c->IsInCombat())
                    startMs = std::min(startMs, engaged);
            }
        }

        Run& run = GetOrOpenRun(map, startMs);
        if (startMs < run.startMs)   // can't predate an existing run's clock
            startMs = run.startMs;
        run.encId = nextEncId++;
        run.encBoss = boss->GetGUID();
        run.encStartMs = startMs;
        run.encKillMs = 0;
        run.encCombatOverMs = 0;
        WriteActor(run, boss);

        if (pb)
        {
            if (startMs < now)
                for (Event const& ev : pb->events)
                {
                    if (ev.t < startMs)
                        continue;
                    if (auto a = pb->actors.find(ev.src); a != pb->actors.end()) WriteActorInfo(run, a->second);
                    if (auto a = pb->actors.find(ev.dst); a != pb->actors.end()) WriteActorInfo(run, a->second);
                    WriteSpell(ev.spell);
                    Event promoted = ev;
                    promoted.t = ev.t - run.startMs;
                    run.buf.push_back(promoted);
                }
            pre.erase(pit);
        }

        uint32 players = 0;
        uint8 minEra = 255, maxEra = 0;
        std::string parts;
        for (auto const& ref : map->GetPlayers())
        {
            Player* p = ref.GetSource();
            if (!p || p->IsGameMaster())
                continue;
            ++players;
            uint8 era = sIndividualProgression->GetPlayerProgressionFromQuests(p);
            minEra = std::min(minEra, era);
            maxEra = std::max(maxEra, era);
            WriteActor(run, p);
            if (!parts.empty())
                parts += ',';
            parts += Acore::StringFormat("({},{},{})", run.encId, p->GetGUID().GetRawValue(), uint32(era));
        }
        if (minEra == 255)
            minEra = 0;

        CharacterDatabase.Execute(Acore::StringFormat(
            "INSERT INTO nekolog_encounter (id, run_id, boss_entry, boss_guid, boss_name, start_ms, players, min_era, max_era) "
            "VALUES ({},{},{},{},'{}',{},{},{},{})",
            run.encId, run.id, boss->GetEntry(), boss->GetGUID().GetRawValue(), Escaped(boss->GetName()),
            run.encStartMs - run.startMs, players, uint32(minEra), uint32(maxEra)));
        if (run.buf.size() >= FLUSH_ROWS)
            FlushEvents(run);
        if (!parts.empty())
            CharacterDatabase.Execute("INSERT IGNORE INTO nekolog_participant (enc_id, guid, era) VALUES " + parts);
    }

    void CloseEncounter(Run& run, uint8 result)
    {
        if (!run.encId)
            return;

        FlushEvents(run);   // events so far carry this encounter's id
        uint32 endMs = (result == RESULT_KILL && run.encKillMs) ? run.encKillMs : NowMs();
        CharacterDatabase.Execute(Acore::StringFormat(
            "UPDATE nekolog_encounter SET end_ms={}, result={} WHERE id={}",
            endMs - run.startMs, uint32(result), run.encId));

        if (result == RESULT_KILL) ++run.kills; else ++run.wipes;
        CharacterDatabase.Execute(Acore::StringFormat(
            "UPDATE nekolog_run SET kills={}, wipes={} WHERE id={}", run.kills, run.wipes, run.id));

        run.encId = 0;
        run.encBoss.Clear();
        run.encKillMs = 0;
        run.encCombatOverMs = 0;
    }

    // Boss is down: fix the kill time, keep recording the tail until the
    // group drops combat (see FinishIfCombatOver) or the linger cap.
    void MarkKilled(Run& run)
    {
        if (run.encId && !run.encKillMs)
            run.encKillMs = NowMs();
    }

    // Must hold runsMutex. Arms (or disarms) the deferred close; OnUpdate
    // performs it once the grace period passes with nobody back in combat.
    void FinishIfCombatOver(Run& run, Map* map)
    {
        if (!run.encId || !run.encKillMs)
            return;
        for (auto const& ref : map->GetPlayers())
        {
            Player* p = ref.GetSource();
            if (p && !p->IsGameMaster() && p->IsAlive() && p->IsInCombat())
            {
                run.encCombatOverMs = 0;
                return;
            }
        }
        if (!run.encCombatOverMs)
            run.encCombatOverMs = NowMs();
    }

    void CloseRun(uint64 key)
    {
        auto it = runs.find(key);
        if (it == runs.end())
            return;
        Run& run = it->second;
        if (run.encId)
            CloseEncounter(run, RESULT_WIPE);
        FlushEvents(run);
        CharacterDatabase.Execute(Acore::StringFormat(
            "UPDATE nekolog_run SET ended_at={} WHERE id={}", uint32(GameTime::GetGameTime().count()), run.id));
        runs.erase(it);
    }

    bool IsBoss(Unit* unit)
    {
        Creature* c = unit ? unit->ToCreature() : nullptr;
        return c && (c->IsDungeonBoss() || c->isWorldBoss());
    }
}

class NekoLog_UnitScript : public UnitScript
{
public:
    NekoLog_UnitScript() : UnitScript("NekoLog_UnitScript") { }

    // --- context stash (same call chain as the OnDamage/OnHeal below) ---

    void ModifySpellDamageTaken(Unit* target, Unit* /*attacker*/, int32& damage, SpellInfo const* spellInfo) override
    {
        if (!target || !Loggable(target->GetMap()))
            return;
        tlsCtx = HitContext{ true, spellInfo ? spellInfo->Id : 0,
            uint8(spellInfo ? spellInfo->GetSchoolMask() : 1), uint32(std::max(damage, 0)), false };
    }

    void ModifyMeleeDamage(Unit* target, Unit* /*attacker*/, uint32& damage) override
    {
        if (!target || !Loggable(target->GetMap()))
            return;
        tlsCtx = HitContext{ true, 0, 1, damage, false };
    }

    void ModifyPeriodicDamageAurasTick(Unit* target, Unit* /*attacker*/, uint32& damage, SpellInfo const* spellInfo) override
    {
        if (!target || !Loggable(target->GetMap()))
            return;
        tlsCtx = HitContext{ true, spellInfo ? spellInfo->Id : 0,
            uint8(spellInfo ? spellInfo->GetSchoolMask() : 1), damage, true };
    }

    void ModifyHealReceived(Unit* target, Unit* /*healer*/, uint32& heal, SpellInfo const* spellInfo) override
    {
        if (!target || !Loggable(target->GetMap()))
            return;
        // Keep the periodic flag a HoT tick already set via ModifyPeriodicDamageAurasTick.
        bool periodic = tlsCtx.valid && tlsCtx.periodic && spellInfo && tlsCtx.spell == spellInfo->Id;
        tlsCtx = HitContext{ true, spellInfo ? spellInfo->Id : 0,
            uint8(spellInfo ? spellInfo->GetSchoolMask() : 2), heal, periodic };
    }

    // --- the actual events ---

    void OnDamage(Unit* attacker, Unit* victim, uint32& damage) override
    {
        HitContext ctx = tlsCtx;
        tlsCtx.valid = false;
        if (!attacker || !victim || !Loggable(victim->GetMap()))
            return;
        if (!ctx.valid)
            ctx = HitContext{ true, 0, 1, damage, false };
        if (damage == 0 && ctx.raw == 0)
            return;

        int32 mitigated = int32(ctx.raw) - int32(damage);
        std::lock_guard<std::mutex> lock(runsMutex);
        Record(victim->GetMap(), attacker, victim, EV_DAMAGE, ctx.spell, int32(damage), std::max(mitigated, 0), ctx.school, ctx.periodic ? 1 : 0);
    }

    void OnHeal(Unit* healer, Unit* receiver, uint32& gain) override
    {
        HitContext ctx = tlsCtx;
        tlsCtx.valid = false;
        if (!healer || !receiver || !Loggable(receiver->GetMap()))
            return;
        if (!ctx.valid)
            ctx = HitContext{ true, 0, 2, gain, false };
        if (gain == 0 && ctx.raw == 0)
            return;

        int32 overheal = int32(ctx.raw) - int32(gain);
        std::lock_guard<std::mutex> lock(runsMutex);
        Record(receiver->GetMap(), healer, receiver, EV_HEAL, ctx.spell, int32(gain), std::max(overheal, 0), ctx.school, ctx.periodic ? 1 : 0);
    }

    void OnUnitDeath(Unit* unit, Unit* killer) override
    {
        if (!unit || !Loggable(unit->GetMap()))
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        Record(unit->GetMap(), killer, unit, EV_DEATH, 0, 0, 0, 0, 0);
        Run* run = OpenEncounterRun(unit->GetMap());
        if (run && unit->GetGUID() == run->encBoss)
        {
            MarkKilled(*run);
            FinishIfCombatOver(*run, unit->GetMap());
        }
    }

    void OnUnitEnterCombat(Unit* unit, Unit* /*victim*/) override
    {
        Creature* c = unit ? unit->ToCreature() : nullptr;
        if (!c || !Loggable(c->GetMap()))
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        Map* map = c->GetMap();
        if (Run* open = OpenEncounterRun(map); open && open->encKillMs && IsBoss(c))
            CloseEncounter(*open, RESULT_KILL);
        if (!OpenEncounterRun(map))
        {
            // Remember the pull time of every creature so a boss summoned
            // by one of them can be traced back to it.
            PreBuffer& pb = pre[RunKey(map)];
            TrimPre(pb, NowMs());
            pb.engagedMs.emplace(c->GetGUID().GetRawValue(), NowMs());
            PreActor(pb, c);
            if (IsBoss(c))
                OpenEncounter(map, c);
        }
    }

    void OnUnitExitCombat(Unit* unit) override
    {
        if (!IsBoss(unit) || !Loggable(unit->GetMap()) || !unit->IsAlive())
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        auto it = runs.find(RunKey(unit->GetMap()));
        if (it != runs.end() && it->second.encId && !it->second.encKillMs && it->second.encBoss == unit->GetGUID())
            CloseEncounter(it->second, RESULT_WIPE);
    }

    void OnAuraApply(Unit* unit, Aura* aura) override
    {
        if (!logAuras || !unit || !aura || !Loggable(unit->GetMap()))
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        Record(unit->GetMap(), aura->GetCaster(), unit, EV_AURA_APPLY, aura->GetId(), 0, 0,
            uint8(aura->GetSpellInfo()->GetSchoolMask()), 0);
    }

    void OnAuraRemove(Unit* unit, AuraApplication* aurApp, AuraRemoveMode /*mode*/) override
    {
        if (!logAuras || !unit || !aurApp || !Loggable(unit->GetMap()))
            return;
        Aura* aura = aurApp->GetBase();
        if (!aura)
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        Record(unit->GetMap(), aura->GetCaster(), unit, EV_AURA_REMOVE, aura->GetId(), 0, 0,
            uint8(aura->GetSpellInfo()->GetSchoolMask()), 0);
    }
};

class NekoLog_PlayerScript : public PlayerScript
{
public:
    NekoLog_PlayerScript() : PlayerScript("NekoLog_PlayerScript") { }

    // Character deleted: keep the logs (they're the other players' history
    // too) but drop the characters.guid link, because AzerothCore reuses
    // guids (MAX(guid)+1 at startup) and a new toon must not inherit them.
    void OnPlayerDelete(ObjectGuid guid, uint32 /*accountId*/) override
    {
        CharacterDatabase.Execute(Acore::StringFormat("UPDATE nekolog_actor SET char_guid=0 WHERE char_guid={}", guid.GetCounter()));
        CharacterDatabase.Execute(Acore::StringFormat("UPDATE nekolog_rank SET char_guid=0 WHERE char_guid={}", guid.GetCounter()));
    }

    void OnPlayerLeaveCombat(Player* player) override
    {
        if (!player || !Loggable(player->GetMap()))
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        if (Run* run = OpenEncounterRun(player->GetMap()))
            FinishIfCombatOver(*run, player->GetMap());
    }

    void OnPlayerEnterCombat(Player* player, Unit* /*enemy*/) override
    {
        if (!player || !Loggable(player->GetMap()))
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        if (Run* run = OpenEncounterRun(player->GetMap()))
            run->encCombatOverMs = 0;   // tail is still going
    }

    void OnPlayerSpellCast(Player* player, Spell* spell, bool /*skipCheck*/) override
    {
        if (!logCasts || !player || !spell || !Loggable(player->GetMap()))
            return;
        SpellInfo const* info = spell->GetSpellInfo();
        if (!info)
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        Unit* target = spell->m_targets.GetUnitTarget();
        Record(player->GetMap(), player, target, EV_CAST, info->Id, 0, 0, uint8(info->GetSchoolMask()), 0);
    }
};

class NekoLog_GlobalScript : public GlobalScript
{
public:
    NekoLog_GlobalScript() : GlobalScript("NekoLog_GlobalScript") { }

    void OnBeforeSetBossState(uint32 /*id*/, EncounterState newState, EncounterState oldState, Map* instance) override
    {
        if (!Loggable(instance) || newState == oldState || oldState == TO_BE_DECIDED)
            return;
        if (newState != DONE && newState != FAIL)
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        auto it = runs.find(RunKey(instance));
        if (it == runs.end() || !it->second.encId)
            return;
        if (newState == FAIL)
            CloseEncounter(it->second, RESULT_WIPE);
        else
        {
            MarkKilled(it->second);
            FinishIfCombatOver(it->second, instance);
        }
    }
};

class NekoLog_AllMapScript : public AllMapScript
{
public:
    NekoLog_AllMapScript() : AllMapScript("NekoLog_AllMapScript") { }

    void OnDestroyInstance(MapInstanced* /*mapInstanced*/, Map* map) override
    {
        if (!map)
            return;
        std::lock_guard<std::mutex> lock(runsMutex);
        CloseRun(RunKey(map));
        pre.erase(RunKey(map));
    }
};

class NekoLog_WorldScript : public WorldScript
{
public:
    NekoLog_WorldScript() : WorldScript("NekoLog_WorldScript") { }

    void OnBeforeConfigLoad(bool /*reload*/) override
    {
        logEnabled = sConfigMgr->GetOption<bool>("Nekocore.Log.Enable", true);
        logAuras   = sConfigMgr->GetOption<bool>("Nekocore.Log.Auras", true);
        logCasts   = sConfigMgr->GetOption<bool>("Nekocore.Log.Casts", true);
    }

    void OnStartup() override
    {
        // Seed the id counters past whatever the tables already hold, and
        // close out runs a previous worldserver never got to finish.
        if (QueryResult r = CharacterDatabase.Query("SELECT COALESCE(MAX(id),0) FROM nekolog_run"))
            nextRunId = (*r)[0].Get<uint64>() + 1;
        if (QueryResult r = CharacterDatabase.Query("SELECT COALESCE(MAX(id),0) FROM nekolog_encounter"))
            nextEncId = (*r)[0].Get<uint64>() + 1;
        CharacterDatabase.Execute("UPDATE nekolog_encounter SET result=2, end_ms=start_ms WHERE result=0");
        CharacterDatabase.Execute("UPDATE nekolog_run SET ended_at=started_at WHERE ended_at=0");
        LOG_INFO("module.nekocore", "NekoLog: combat logging {} (next run id {})", logEnabled ? "enabled" : "disabled", nextRunId);
    }

    void OnUpdate(uint32 /*diff*/) override
    {
        uint32 now = NowMs();
        std::lock_guard<std::mutex> lock(runsMutex);
        for (auto& [key, run] : runs)
        {
            if (run.encId && run.encKillMs
                && (now - run.encKillMs >= LINGER_MAX_MS
                    || (run.encCombatOverMs && now - run.encCombatOverMs >= COMBAT_OVER_GRACE_MS)))
                CloseEncounter(run, RESULT_KILL);
            if (!run.buf.empty() && now - run.lastFlushMs >= FLUSH_INTERVAL_MS)
                FlushEvents(run);
        }
    }

    void OnShutdown() override
    {
        std::lock_guard<std::mutex> lock(runsMutex);
        std::vector<uint64> keys;
        for (auto const& [key, run] : runs)
            keys.push_back(key);
        for (uint64 key : keys)
            CloseRun(key);
    }
};

void AddSC_nekolog()
{
    new NekoLog_UnitScript();
    new NekoLog_PlayerScript();
    new NekoLog_GlobalScript();
    new NekoLog_AllMapScript();
    new NekoLog_WorldScript();
}

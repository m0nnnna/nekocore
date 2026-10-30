--[[
NekoCombatRecorder -- records fights so combat problems can be diagnosed.

What the server cannot see is here: the combat log carries the RESULT of
every swing and spell (hit, crit, miss, dodge, parry, block, resist, absorb,
immune, glancing/crushing), and the client knows its own stats, latency and
framerate. NekoCore's server-side recorder (mod-combat-recorder) has the
other half: damage before mitigation, AutoBalance multipliers, melee roll
chances. Together they answer "why".

Everything is written to SavedVariables, which WoW saves at logout or /reload:
  WTF/Account/<ACCOUNT>/SavedVariables/NekoCombatRecorder.lua
Send that file when you report a problem. Nothing is uploaded.

Layout of NekoCombatRecorderDB:
  schema, enabled, keep, maxEvents
  fights = { { start=<unix>, zone, sub, inst, diff, group, patch, char, realm,
               snaps = { "<key=value ...>" , ... },
               ev    = { "<ms>|<EVENT>|<src>|<dst>|<args...>", ... },
               dropped=<n>, ended=<unix>, dur=<sec> } , ... }
Event strings are pipe-delimited; src/dst are "name:guidTail:flags".
]]

local SCHEMA = 1
local PRE_SECONDS = 4          -- events kept from before PLAYER_REGEN_DISABLED
local SNAP_EVERY = 2           -- seconds between snapshots in combat
local MINE_MASK = 0x7          -- COMBATLOG_OBJECT_AFFILIATION_MINE|PARTY|RAID

local db
local fight                    -- current fight table, nil when out of combat
local fightStartT              -- GetTime() at fight start
local pre = {}                 -- { {t, str}, ... } ring before combat
local sinceSnap = 0

local band, floor, format, concat = bit.band, math.floor, string.format, table.concat

local function Msg(text)
    DEFAULT_CHAT_FRAME:AddMessage("|cff66ccffNekoCombatRecorder:|r " .. text)
end

local function Pipe(v)
    if v == nil then return "" end
    if v == true then return "1" end
    if v == false then return "0" end
    return (tostring(v):gsub("|", "/"))
end

local function Who(guid, name, flags)
    if not guid then return "" end
    return format("%s:%s:%x", Pipe(name), guid:sub(-8), flags or 0)
end

local function Snapshot(why)
    local parts = {}
    local function add(k, v) parts[#parts + 1] = k .. "=" .. Pipe(v) end
    local function addn(k, ...) -- numbers joined by commas
        local t = {}
        for i = 1, select("#", ...) do t[i] = Pipe(floor((select(i, ...) or 0) * 100 + 0.5) / 100) end
        parts[#parts + 1] = k .. "=" .. concat(t, ",")
    end

    local now = GetTime()
    add("why", why)
    add("t", floor((now - (fightStartT or now)) * 1000))
    add("hp", UnitHealth("player") .. "/" .. UnitHealthMax("player"))
    add("pw", UnitPower("player") .. "/" .. UnitPowerMax("player") .. ":" .. (UnitPowerType("player")))
    add("lvl", UnitLevel("player"))
    add("class", select(2, UnitClass("player")))
    add("race", select(2, UnitRace("player")))
    add("form", GetShapeshiftForm())
    add("mounted", IsMounted() and 1 or 0)
    add("moving", GetUnitSpeed("player") > 0 and 1 or 0)
    addn("stats", UnitStat("player", 1), UnitStat("player", 2), UnitStat("player", 3), UnitStat("player", 4), UnitStat("player", 5))
    addn("armor", select(2, UnitArmor("player")))
    addn("res", select(2, UnitResistance("player", 1)), select(2, UnitResistance("player", 2)), select(2, UnitResistance("player", 3)),
        select(2, UnitResistance("player", 4)), select(2, UnitResistance("player", 5)), select(2, UnitResistance("player", 6)))
    do
        local base, pos, neg = UnitAttackPower("player")
        addn("ap", base + pos + neg)
        base, pos, neg = UnitRangedAttackPower("player")
        addn("rap", base + pos + neg)
    end
    addn("crit", GetCritChance(), GetRangedCritChance(), GetSpellCritChance(2), GetSpellCritChance(3),
        GetSpellCritChance(4), GetSpellCritChance(5), GetSpellCritChance(6), GetSpellCritChance(7))
    addn("avoid", GetDodgeChance(), GetParryChance(), GetBlockChance())
    addn("rating", GetCombatRating(6), GetCombatRating(7), GetCombatRating(8), GetCombatRating(24),
        GetCombatRating(18), GetCombatRating(19), GetCombatRating(20), GetCombatRating(2), GetCombatRating(3),
        GetCombatRating(4), GetCombatRating(1), GetCombatRating(15))   -- hit m/r/s, expertise, haste m/r/s, dodge, parry, block, defense, resilience
    addn("spell", GetSpellBonusDamage(2), GetSpellBonusDamage(3), GetSpellBonusDamage(4), GetSpellBonusDamage(5),
        GetSpellBonusDamage(6), GetSpellBonusDamage(7), GetSpellBonusHealing())
    addn("regen", GetManaRegen())
    do
        local lo, hi, olo, ohi, pp, pn, pm = UnitDamage("player")
        addn("wdmg", lo, hi, olo, ohi, pm)
    end
    addn("speed", UnitAttackSpeed("player"))
    add("defense", (UnitDefense("player")))
    do
        local _, _, home, world = GetNetStats()
        add("lat", (home or 0) .. "/" .. (world or 0))
        add("fps", floor(GetFramerate() or 0))
    end
    add("zone", GetRealZoneText())
    add("sub", GetSubZoneText())

    -- target
    if UnitExists("target") then
        add("tgt", format("%s|%s|%s|%s|%s|%s", Pipe(UnitName("target")), UnitLevel("target"), UnitClassification("target"),
            UnitCreatureType("target") or "", UnitHealth("target") .. "/" .. UnitHealthMax("target"), (UnitGUID("target") or ""):sub(-8)))
    end

    -- buffs / debuffs: id:stacks:duration-left
    local function auras(filter, fn)
        local t = {}
        for i = 1, 40 do
            local name, _, _, count, _, dur, exp, _, _, _, id = fn("player", i)
            if not name then break end
            t[#t + 1] = format("%d:%d:%d", id or 0, count or 0, exp and exp > 0 and floor(exp - GetTime()) or 0)
        end
        parts[#parts + 1] = filter .. "=" .. concat(t, ",")
    end
    auras("buffs", UnitBuff)
    auras("debuffs", UnitDebuff)

    -- gear (item ids)
    local g = {}
    for slot = 1, 19 do
        local link = GetInventoryItemLink("player", slot)
        g[#g + 1] = link and (link:match("item:(%d+)") or "0") or "0"
    end
    parts[#parts + 1] = "gear=" .. concat(g, ",")
    if UnitExists("pet") then
        add("pet", format("%s|%s|%s", Pipe(UnitName("pet")), UnitLevel("pet"), UnitHealth("pet") .. "/" .. UnitHealthMax("pet")))
    end

    return concat(parts, " ")
end

-- rest = everything after the millisecond stamp. In combat it is stamped
-- against the pull; out of combat it waits (with its absolute time) in `pre`.
local function Push(rest, t)
    t = t or GetTime()
    if fight then
        local ev = fight.ev
        if #ev >= db.maxEvents then
            fight.dropped = (fight.dropped or 0) + 1
        else
            ev[#ev + 1] = floor((t - fightStartT) * 1000) .. "|" .. rest
        end
    else
        pre[#pre + 1] = { t, rest }
        if #pre > 200 then table.remove(pre, 1) end
    end
end

local function StartFight()
    if fight then return end
    local zone = GetRealZoneText()
    local _, itype, diff = GetInstanceInfo()
    local group = GetNumRaidMembers() > 0 and GetNumRaidMembers() or (GetNumPartyMembers() > 0 and GetNumPartyMembers() + 1 or 1)
    fightStartT = GetTime()
    fight = {
        start = time(), zone = zone, sub = GetSubZoneText(), inst = itype, diff = diff, group = group,
        patch = NEKO_PATCH_VERSION or "unknown", char = UnitName("player"), realm = GetRealmName(),
        build = select(2, GetBuildInfo()), snaps = {}, ev = {},
    }
    -- promote the pre-combat buffer, restamped relative to the pull (negative ms)
    local cutoff = fightStartT - PRE_SECONDS
    for _, p in ipairs(pre) do
        if p[1] >= cutoff then
            fight.ev[#fight.ev + 1] = floor((p[1] - fightStartT) * 1000) .. "|" .. p[2]
        end
    end
    wipe(pre)
    fight.snaps[1] = Snapshot("start")
    sinceSnap = 0
end

local function EndFight(why)
    if not fight then return end
    fight.snaps[#fight.snaps + 1] = Snapshot(why or "end")
    fight.ended = time()
    fight.dur = floor(GetTime() - fightStartT)
    local fights = db.fights
    fights[#fights + 1] = fight
    while #fights > db.keep do table.remove(fights, 1) end
    fight, fightStartT = nil, nil
end

local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("PLAYER_REGEN_DISABLED")
f:RegisterEvent("PLAYER_REGEN_ENABLED")
f:RegisterEvent("PLAYER_DEAD")
f:RegisterEvent("PLAYER_LOGOUT")
f:RegisterEvent("PLAYER_TARGET_CHANGED")
f:RegisterEvent("UI_ERROR_MESSAGE")
f:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
f:RegisterEvent("UNIT_SPELLCAST_SENT")
f:RegisterEvent("UNIT_SPELLCAST_START")
f:RegisterEvent("UNIT_SPELLCAST_SUCCEEDED")
f:RegisterEvent("UNIT_SPELLCAST_FAILED")
f:RegisterEvent("UNIT_SPELLCAST_INTERRUPTED")
f:RegisterEvent("UNIT_SPELLCAST_DELAYED")
f:RegisterEvent("UNIT_SPELLCAST_CHANNEL_START")
f:RegisterEvent("UNIT_SPELLCAST_CHANNEL_STOP")

local handlers = {}

function handlers.ADDON_LOADED(name)
    if name ~= "NekoCombatRecorder" then return end
    NekoCombatRecorderDB = NekoCombatRecorderDB or {}
    db = NekoCombatRecorderDB
    if db.schema ~= SCHEMA then
        db.fights = {}
        db.schema = SCHEMA
    end
    if db.enabled == nil then db.enabled = true end
    db.keep = db.keep or 10
    db.maxEvents = db.maxEvents or 6000
    db.fights = db.fights or {}
end

function handlers.PLAYER_REGEN_DISABLED() if db and db.enabled then StartFight() end end
function handlers.PLAYER_REGEN_ENABLED() EndFight("end") end
function handlers.PLAYER_LOGOUT() EndFight("logout") end

function handlers.PLAYER_DEAD()
    if fight then Push("PLAYER_DEAD"); fight.snaps[#fight.snaps + 1] = Snapshot("dead") end
end

function handlers.PLAYER_TARGET_CHANGED()
    if db and db.enabled then
        Push(format("TARGET|%s", Who(UnitGUID("target"), UnitName("target"), 0)))
    end
end

function handlers.UI_ERROR_MESSAGE(msg)
    if db and db.enabled and fight then Push(format("UI_ERROR|%s", Pipe(msg))) end
end

local function Cast(kind)
    return function(unit, spell, rank, a, b)
        if not (db and db.enabled) or (unit ~= "player" and unit ~= "pet") then return end
        Push(format("%s|%s|%s|%s|%s", kind, unit, Pipe(spell), Pipe(rank), Pipe(a or b)))
    end
end
handlers.UNIT_SPELLCAST_SENT = function(unit, spell, rank, target)
    if not (db and db.enabled) or unit ~= "player" then return end
    Push(format("CAST_SENT|%s|%s|%s", Pipe(spell), Pipe(rank), Pipe(target)))
end
handlers.UNIT_SPELLCAST_START = Cast("CAST_START")
handlers.UNIT_SPELLCAST_SUCCEEDED = Cast("CAST_OK")
handlers.UNIT_SPELLCAST_FAILED = Cast("CAST_FAIL")
handlers.UNIT_SPELLCAST_INTERRUPTED = Cast("CAST_INTERRUPTED")
handlers.UNIT_SPELLCAST_DELAYED = Cast("CAST_DELAYED")
handlers.UNIT_SPELLCAST_CHANNEL_START = Cast("CHANNEL_START")
handlers.UNIT_SPELLCAST_CHANNEL_STOP = Cast("CHANNEL_STOP")

function handlers.COMBAT_LOG_EVENT_UNFILTERED(timestamp, event, srcGUID, srcName, srcFlags, dstGUID, dstName, dstFlags, ...)
    if not (db and db.enabled) then return end
    if band(srcFlags or 0, MINE_MASK) == 0 and band(dstFlags or 0, MINE_MASK) == 0 then return end
    local n = select("#", ...)
    local args = {}
    for i = 1, n do args[i] = Pipe((select(i, ...))) end
    local t = GetTime()
    Push(format("%s|%s|%s|%s", event, Who(srcGUID, srcName, srcFlags), Who(dstGUID, dstName, dstFlags),
        concat(args, "|")), t)
end

f:SetScript("OnEvent", function(_, event, ...)
    local h = handlers[event]
    if h then h(...) end
end)

f:SetScript("OnUpdate", function(_, elapsed)
    if not fight then return end
    sinceSnap = sinceSnap + elapsed
    if sinceSnap >= SNAP_EVERY then
        sinceSnap = 0
        if #fight.snaps < 600 then fight.snaps[#fight.snaps + 1] = Snapshot("tick") end
    end
end)

SLASH_NEKOCOMBATRECORDER1 = "/ncr"
SlashCmdList["NEKOCOMBATRECORDER"] = function(arg)
    arg = (arg or ""):lower()
    if arg == "on" then db.enabled = true; Msg("recording ON")
    elseif arg == "off" then db.enabled = false; Msg("recording OFF")
    elseif arg == "clear" then db.fights = {}; Msg("cleared saved fights")
    elseif arg == "mark" then
        if fight then Push("MARK"); fight.snaps[#fight.snaps + 1] = Snapshot("mark"); Msg("marked this moment in the fight")
        else Msg("not in combat") end
    else
        local n, ev = #db.fights, 0
        for _, ft in ipairs(db.fights) do ev = ev + #ft.ev end
        Msg(format("%s. %d fight(s) saved (%d events), keeping the last %d.", db.enabled and "recording ON" or "recording OFF", n, ev, db.keep))
        Msg("Saved when you /reload or log out. Send this file when reporting a problem:")
        Msg("|cffffff00WTF\\Account\\<ACCOUNT NAME>\\SavedVariables\\NekoCombatRecorder.lua|r")
        Msg("/ncr on | off | clear | mark (tag the moment something went wrong, in combat)")
    end
end

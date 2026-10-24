-- A 3.3.5 client draws a debuff's tooltip from its own Spell.dbc: the aura
-- update packet carries no effect amounts, only id, flags, caster level,
-- stacks, caster and duration. The realm's AutoBalance scales an enemy DoT
-- on each tick (ModifyPeriodicDamageAurasTick), so the tooltip shows the
-- unscaled DBC number -- often "3", or nothing where the text has no value.
-- The real tick is in the combat log; remember the last one per target and
-- spell and put it into the tooltip.

local lastTick = {} -- [destGUID] = { [spellId] = amount }

local frame = CreateFrame("Frame")
frame:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:SetScript("OnEvent", function(_, event, ...)
    if event == "PLAYER_ENTERING_WORLD" then
        wipe(lastTick)
        return
    end
    local _, subEvent, _, _, _, destGUID, _, _, spellId, _, _, amount, _, _, resisted, _, absorbed = ...
    if subEvent ~= "SPELL_PERIODIC_DAMAGE" or not destGUID or not spellId then
        return
    end
    -- The tick as dealt, before this target's resist and absorb.
    local tick = (amount or 0) + (resisted or 0) + (absorbed or 0)
    local byTarget = lastTick[destGUID]
    if not byTarget then
        byTarget = {}
        lastTick[destGUID] = byTarget
    end
    byTarget[spellId] = tick
end)

-- "Inflicts 3 Shadow damage every 3 sec." / "Deals 3 Nature damage every 2 sec."
local function Rewrite(tooltip, tick)
    local name = tooltip:GetName()
    for i = 2, tooltip:NumLines() do
        local line = _G[name .. "TextLeft" .. i]
        local text = line and line:GetText()
        if text then
            local new, count = text:gsub("%d+( [^%d]-damage every)", tick .. "%1", 1)
            if count > 0 then
                line:SetText(new)
                tooltip:Show()
                return
            end
        end
    end
    tooltip:AddLine(string.format("%d damage per tick (last tick)", tick), 1, 0.82, 0)
    tooltip:Show()
end

local function OnDebuff(tooltip, unit, index, filter)
    local guid = unit and UnitGUID(unit)
    local byTarget = guid and lastTick[guid]
    if not byTarget then
        return
    end
    local spellId = select(11, UnitDebuff(unit, index, filter))
    local tick = spellId and byTarget[spellId]
    if tick then
        Rewrite(tooltip, tick)
    end
end

hooksecurefunc(GameTooltip, "SetUnitDebuff", OnDebuff)
hooksecurefunc(GameTooltip, "SetUnitAura", function(tooltip, unit, index, filter)
    if filter and filter:find("HARMFUL") then
        OnDebuff(tooltip, unit, index, filter)
    end
end)

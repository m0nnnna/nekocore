-- Diagnostic only: dumps talent tab/spec state to chat so we can see what
-- the client's own talent API reports without going anywhere near the
-- stock TalentFrame UI (which showed a confusing "Activate These Talents"
-- state after the new dedicated era tabs were added -- this addon exists
-- to find out why before touching that UI again).

local function safe(fn, ...)
	local ok, a, b, c, d, e = pcall(fn, ...)
	if not ok then
		return "ERROR: " .. tostring(a)
	end
	return a, b, c, d, e
end

local function dump()
	print("|cff00ff00[NekoTalentDebug]|r ---- talent state dump ----")

	local numGroups = safe(GetNumTalentGroups)
	local activeGroup = safe(GetActiveTalentGroup)
	print(string.format("GetNumTalentGroups=%s  GetActiveTalentGroup=%s", tostring(numGroups), tostring(activeGroup)))

	local numTabs = safe(GetNumTalentTabs)
	print(string.format("GetNumTalentTabs=%s", tostring(numTabs)))

	-- Probe indices 1-9 regardless of what GetNumTalentTabs() reports --
	-- tells us whether "extra" tabs genuinely don't exist from the client's
	-- perspective (GetTalentTabInfo returns nil) or exist but are being
	-- undercounted by GetNumTalentTabs specifically.
	for i = 1, 9 do
		local name, icon, pointsSpent, background = safe(GetTalentTabInfo, i)
		local numTalents = safe(GetNumTalents, i)
		if name ~= nil or (type(numTalents) == "number" and numTalents > 0) then
			local inRange = (type(numTabs) == "number" and i <= numTabs) and "IN-RANGE" or "OUT-OF-RANGE"
			print(string.format("  [%s] tab %d: name=%s pointsSpent=%s numTalents=%s icon=%s",
				inRange, i, tostring(name), tostring(pointsSpent), tostring(numTalents), tostring(icon)))
			-- also probe the first talent slot in this tab, to see if the
			-- underlying per-talent data is there even if the tab-level
			-- query is inconsistent
			local tname, ticon, tier, column, rank, maxRank = safe(GetTalentInfo, i, 1, false, false, safe(GetActiveTalentGroup))
			print(string.format("      talent 1 in tab %d: name=%s tier=%s col=%s rank=%s maxRank=%s",
				i, tostring(tname), tostring(tier), tostring(column), tostring(rank), tostring(maxRank)))
		end
	end

	print("|cff00ff00[NekoTalentDebug]|r ---- end dump ----")
end

SLASH_NEKOTALENTDEBUG1 = "/ntd"
SlashCmdList["NEKOTALENTDEBUG"] = dump

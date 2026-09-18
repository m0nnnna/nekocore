--[[
Custom era talent frame -- first working slice.

Why this exists: build_era_tree.py gives each era its own dedicated
TalentTab.dbc ids (not merged into WotLK's existing 3 tabs), and the
client's talent API happily reports them (GetNumTalentTabs() correctly
returns 6 for a class with one extra era loaded, confirmed live via
NekoTalentDebug's /ntd). But the STOCK TalentFrame only ever creates
tab-button widgets for the first few tabs and gets visibly confused once
more than 3 same-class tabs exist (a third-party-modified Blizzard_TalentUI
on this specific client shows a bogus "Activate These Talents" state and
blanks every tab, not just the extra ones -- root cause not fully chased
down since we're replacing that code path anyway, not fixing it).

This frame talks to the SAME underlying API the stock frame does
(GetTalentTabInfo/GetTalentInfo/GetTalentPrereqs/LearnTalent) for a
DIFFERENT tab index range -- it doesn't reimplement talent-learning, just
the display, so all the real validation (tier gating, prereqs,
CMSG_LEARN_TALENT round-trip) is exactly as authoritative as the stock
frame's.

Now covers all 3 eras (stock WotLK tabs 1-3, Vanilla 4-6, TBC 7-9 --
build_era_tree.py's ERA_ORDER fixes that index layout) and picks which
block to show automatically: DetectEra() reads the same two hidden
progression quest ids EraProgressionSync.cpp (server side) keys off
(IsQuestFlaggedCompleted is plain client Lua, no server round-trip needed)
and SetEra() repoints the frame at that block's 3 tabs -- N always opens
whichever era the character is actually in right now, no manual era
picker needed. No branch/prereq arrow textures (cosmetic, skipped for
now).

Confirmed API facts (read directly from this client's own
Interface\FrameXML\TalentFrameBase.lua, not guessed):
  GetTalentInfo(tabIndex, talentIndex, inspect, isPet, talentGroup)
    -> name, iconTexture, tier, column, rank, maxRank, isExceptional,
       meetsPrereq, previewRank, meetsPreviewPrereq
  tier/column are 1-INDEXED (unlike Talent.dbc's own 0-indexed TierID/
  ColumnIndex fields) -- tier-gate formula stock code uses:
  (tier - 1) * PLAYER_TALENTS_PER_TIER <= pointsSpentInThisTab
]]

local ERA_TAB_COUNT = 3
local GRID_COLS = 4
local CELL_SIZE = 38
local ICON_SIZE = 32
local FRAME_WIDTH = 400
local FRAME_HEIGHT = 480
local CONTENT_MARGIN = 20
local CONTENT_WIDTH = FRAME_WIDTH - 2 * CONTENT_MARGIN
local GRID_LEFT = (CONTENT_WIDTH - GRID_COLS * CELL_SIZE) / 2
local GRID_TOP = -16
local TAB_WIDTH = 108
local TAB_HEIGHT = 24
local TAB_GAP = 8

-- mod-individual-progression tracks a character's era entirely via these
-- two hidden quest ids being rewarded (66000 + ProgressionState, see
-- IndividualProgression.cpp / this repo's EraProgressionSync.cpp doc
-- comment) -- IsQuestFlaggedCompleted lets client Lua read that same state
-- directly, no server messaging needed. Tab index ranges must stay in sync
-- with build_era_tree.py's ERA_ORDER (stock 1-3, Vanilla 4-6, TBC 7-9).
local PRE_TBC_QUEST = 66008
local TBC_TIER_5_QUEST = 66013

local frame
local tabButtons = {}
local talentButtons = {}
local gridLines = {}
local selectedLocalTab = 1
local currentEraTabStart = 4
local currentEraLabel = "Vanilla"

local function ActualTabIndex()
	return currentEraTabStart + selectedLocalTab - 1
end

local function TalentGroup()
	local ok, g = pcall(GetActiveTalentGroup)
	if ok and g then return g end
	return 1
end

local function UpdateTalents()
	local tabIndex = ActualTabIndex()
	local ok, name, icon, pointsSpent = pcall(GetTalentTabInfo, tabIndex)
	if not ok then name, pointsSpent = "?", 0 end
	frame.title:SetText(name or "?")
	frame.specIcon:SetTexture(icon)
	frame.specIcon:ClearAllPoints()
	frame.specIcon:SetPoint("RIGHT", frame.title, "LEFT", -6, 0)
	frame.pointsText:SetText(string.format("%d points spent in this tree", pointsSpent or 0))

	local okPts, unspent = pcall(GetUnspentTalentPoints)
	frame.pointsAvail:SetText((okPts and unspent) and ("Talent points available: " .. unspent) or "")

	local numTalents = select(2, pcall(GetNumTalents, tabIndex)) or 0
	if type(numTalents) ~= "number" then numTalents = 0 end

	local maxIndex = math.max(numTalents, #talentButtons)
	for i = 1, maxIndex do
		local btn = talentButtons[i]
		if not btn then
			btn = CreateFrame("Button", "NekoTalentUIButton"..i, frame.content)
			btn:SetSize(ICON_SIZE, ICON_SIZE)
			btn.slot = btn:CreateTexture(nil, "BACKGROUND")
			btn.slot:SetTexture("Interface\\Buttons\\UI-EmptySlot")
			btn.slot:SetPoint("CENTER")
			btn.slot:SetSize(ICON_SIZE * 1.5, ICON_SIZE * 1.5)
			btn.icon = btn:CreateTexture(nil, "ARTWORK")
			btn.icon:SetPoint("CENTER")
			btn.icon:SetSize(ICON_SIZE - 4, ICON_SIZE - 4)
			btn.icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
			btn.border = btn:CreateTexture(nil, "OVERLAY")
			btn.border:SetTexture("Interface\\Buttons\\UI-Quickslot2")
			btn.border:SetPoint("CENTER", 0, 0)
			btn.border:SetSize(ICON_SIZE * 1.4, ICON_SIZE * 1.4)
			btn.rank = btn:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
			btn.rank:SetPoint("BOTTOM", 0, -12)
			btn:SetScript("OnClick", function(self)
				LearnTalent(ActualTabIndex(), self.talentIndex, false, TalentGroup())
				UpdateTalents()
			end)
			btn:SetScript("OnEnter", function(self)
				GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
				local tok = pcall(GameTooltip.SetTalent, GameTooltip, ActualTabIndex(), self.talentIndex, false, false, TalentGroup())
				if not tok then
					GameTooltip:SetText(self.name or "?")
				end
				GameTooltip:Show()
			end)
			btn:SetScript("OnLeave", function() GameTooltip:Hide() end)
			talentButtons[i] = btn
		end

		if i <= numTalents then
			local tok, tname, ticon, tier, column, rank, maxRank, isExceptional, meetsPrereq =
				pcall(GetTalentInfo, tabIndex, i, false, false, TalentGroup())
			if tok and tname then
				btn.talentIndex = i
				btn.name = tname
				btn.icon:SetTexture(ticon)
				btn:ClearAllPoints()
				btn:SetPoint("TOPLEFT", frame.content, "TOPLEFT",
					GRID_LEFT + ((column or 1) - 1) * CELL_SIZE,
					GRID_TOP - ((tier or 1) - 1) * CELL_SIZE)
				btn.rank:SetText(string.format("%d/%d", rank or 0, maxRank or 0))

				local maxed = (rank or 0) >= (maxRank or 0) and (maxRank or 0) > 0
				local locked = meetsPrereq == false
				if maxed then
					btn.border:SetVertexColor(1, 0.82, 0)
					btn.icon:SetDesaturated(false)
					btn.rank:SetTextColor(1, 0.82, 0)
				elseif locked then
					btn.border:SetVertexColor(0.5, 0.5, 0.5)
					btn.icon:SetDesaturated(true)
					btn.rank:SetTextColor(0.6, 0.6, 0.6)
				else
					btn.border:SetVertexColor(1, 1, 1)
					btn.icon:SetDesaturated(false)
					btn.rank:SetTextColor((rank or 0) > 0 and 0.2 or 0.8, (rank or 0) > 0 and 1 or 0.8, (rank or 0) > 0 and 0.2 or 0.8)
				end
				btn:Show()
			else
				btn:Hide()
			end
		else
			btn:Hide()
		end
	end
end

local function SelectLocalTab(i)
	selectedLocalTab = i
	for idx, b in ipairs(tabButtons) do
		if idx == i then
			b:LockHighlight()
		else
			b:UnlockHighlight()
		end
	end
	UpdateTalents()
end

local function CreateUI()
	frame = CreateFrame("Frame", "NekoTalentUIFrame", UIParent)
	frame:SetSize(FRAME_WIDTH, FRAME_HEIGHT)
	frame:SetPoint("CENTER")
	frame:SetMovable(true)
	frame:EnableMouse(true)
	frame:RegisterForDrag("LeftButton")
	frame:SetScript("OnDragStart", frame.StartMoving)
	frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
	frame:SetBackdrop({
		bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
		edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
		tile = true, tileSize = 32, edgeSize = 32,
		insets = { left = 11, right = 12, top = 12, bottom = 11 },
	})
	frame:Hide()
	tinsert(UISpecialFrames, "NekoTalentUIFrame")

	local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
	close:SetPoint("TOPRIGHT", -4, -4)

	frame.titleBar = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
	frame.titleBar:SetPoint("TOP", 0, -14)
	frame.titleBar:SetText("Era Talents (Vanilla)")

	frame.specIcon = frame:CreateTexture(nil, "ARTWORK")
	frame.specIcon:SetSize(18, 18)

	frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	frame.title:SetPoint("TOP", 0, -38)

	frame.pointsAvail = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
	frame.pointsAvail:SetPoint("TOPRIGHT", -20, -38)
	frame.pointsAvail:SetTextColor(1, 0.82, 0)

	frame.pointsText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
	frame.pointsText:SetPoint("BOTTOM", 0, 14)

	local divider = frame:CreateTexture(nil, "ARTWORK")
	divider:SetTexture("Interface\\Common\\UI-TooltipDivider")
	divider:SetSize(FRAME_WIDTH - 2 * CONTENT_MARGIN, 8)
	divider:SetPoint("BOTTOM", 0, 34)

	frame.content = CreateFrame("Frame", nil, frame)
	frame.content:SetPoint("TOPLEFT", CONTENT_MARGIN, -96)
	frame.content:SetPoint("BOTTOMRIGHT", -CONTENT_MARGIN, 44)

	for row = 1, 9 do
		local line = frame.content:CreateTexture(nil, "BACKGROUND")
		line:SetTexture(1, 1, 1, 0.05)
		line:SetSize(GRID_COLS * CELL_SIZE, 1)
		line:SetPoint("TOPLEFT", frame.content, "TOPLEFT", GRID_LEFT, GRID_TOP - (row - 1) * CELL_SIZE - CELL_SIZE / 2)
		gridLines[row] = line
	end

	local tabRowWidth = ERA_TAB_COUNT * TAB_WIDTH + (ERA_TAB_COUNT - 1) * TAB_GAP
	local tabStartX = (FRAME_WIDTH - tabRowWidth) / 2
	for i = 1, ERA_TAB_COUNT do
		local b = CreateFrame("Button", "NekoTalentUITab"..i, frame, "UIPanelButtonTemplate")
		b:SetSize(TAB_WIDTH, TAB_HEIGHT)
		b:SetPoint("TOPLEFT", tabStartX + (i - 1) * (TAB_WIDTH + TAB_GAP), -62)
		b:SetScript("OnClick", function() SelectLocalTab(i) end)
		tabButtons[i] = b
	end
end

local function QuestDone(id)
	local ok, done = pcall(IsQuestFlaggedCompleted, id)
	return ok and done
end

local function DetectEra()
	if not QuestDone(PRE_TBC_QUEST) then
		return 4, "Vanilla"
	elseif not QuestDone(TBC_TIER_5_QUEST) then
		return 7, "TBC"
	else
		return 1, "WotLK"
	end
end

local function SetEra(tabStart, label)
	currentEraTabStart = tabStart
	currentEraLabel = label
	selectedLocalTab = 1
	frame.titleBar:SetText("Era Talents (" .. label .. ")")
	for i, b in ipairs(tabButtons) do
		local ok, name = pcall(GetTalentTabInfo, tabStart + i - 1)
		b:SetText((ok and name) or ("Tab " .. i))
	end
end

local function Toggle()
	if not frame then
		CreateUI()
	end
	if frame:IsShown() then
		frame:Hide()
	else
		SetEra(DetectEra())
		frame:Show()
		SelectLocalTab(selectedLocalTab)
	end
end

local function TakeOverNKeybind()
	-- Override the default N keybind (stock TOGGLETALENTS) to call our
	-- Toggle() instead, so N opens /neko directly rather than the stock
	-- frame (which we're bypassing entirely -- see the module doc comment
	-- for why). A hidden button click is the standard addon idiom for
	-- hijacking a default keybind: SetBindingClick points the key at a
	-- button's OnClick rather than at a native command.
	if not _G["NekoTalentUIKeybindButton"] then
		local btn = CreateFrame("Button", "NekoTalentUIKeybindButton", UIParent)
		btn:SetScript("OnClick", Toggle)
	end
	SetBindingClick("N", "NekoTalentUIKeybindButton")
	SaveBindings(1) -- account-wide binding set, so it persists across sessions
end

local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:SetScript("OnEvent", TakeOverNKeybind)

SLASH_NEKOTALENTUI1 = "/neko"
SlashCmdList["NEKOTALENTUI"] = Toggle

--[[
Era talent frame -- a stock-looking replacement for the Blizzard talent
window, pointed at the era tabs build_era_tree.py adds to TalentTab.dbc.

Why a custom frame at all: the stock TalentFrame only ever creates tab
widgets for a class's first three tabs and comes apart once more exist
(the era tabs are 4-6 Vanilla, 7-9 TBC -- see build_era_tree.py's
ERA_ORDER). This frame talks to the SAME client API the stock frame does
(GetTalentTabInfo / GetTalentInfo / GetTalentPrereqs / LearnTalent) for a
different tab index range, so all real validation (tier gating, prereqs,
the CMSG_LEARN_TALENT round trip) is exactly as authoritative as stock.

Which era to show is read client-side: mod-individual-progression rewards
hidden quest 66000+ProgressionState, and IsQuestFlaggedCompleted() sees
that with no server round trip (same two ids EraProgressionSync.cpp keys
off). N / /neko opens whichever era the character is in right now.

Looks: this is deliberately built out of the stock talent frame's own art
so it reads as Blizzard UI, not an addon -- the 384x512 portrait frame
(Interface\TalentFrame\UI-TalentFrame-*), each tree's own background
painting (TalentTab.dbc BackgroundFile, e.g. "MageFire", which the era
tabs reuse from the stock tabs), the UI-TalentBranches / UI-TalentArrows
atlases for prerequisite lines, RankBorder + green/gold/grey rank numbers,
bottom tabs from CharacterFrameTabButtonTemplate, a scrolling tree.
Geometry is the stock frame's (32px buttons on a 63px grid, 30px branch
pieces) so the backgrounds line up the way Blizzard drew them.

Confirmed API facts (from this client's own Interface\FrameXML\
TalentFrameBase.lua, not guessed):
  GetTalentTabInfo(tab) -> name, icon, pointsSpent, background, previewPointsSpent
  GetTalentInfo(tab, i, inspect, isPet, talentGroup)
    -> name, icon, tier, column, rank, maxRank, isExceptional, meetsPrereq,
       previewRank, meetsPreviewPrereq            (tier/column 1-indexed)
  GetTalentPrereqs(tab, i, inspect, isPet, talentGroup)
    -> tier, column, isLearnable, isPreviewLearnable  (repeating)
  tier gate: (tier - 1) * PLAYER_TALENTS_PER_TIER <= pointsSpentInThisTab
]]

local ERA_TAB_COUNT = 3
local FRAME_WIDTH, FRAME_HEIGHT = 384, 512
local BUTTON_SIZE = 32          -- TALENT_BUTTON_SIZE in stock
local GRID_STEP = 63            -- stock buttonSpacingX/Y
local GRID_LEFT, GRID_TOP = 25, 20  -- stock initialOffsetX/Y inside the scroll child
local BRANCH_SIZE = 30
local ARROW_SIZE = 32
local SCROLL_WIDTH, SCROLL_HEIGHT = 296, 330
local TREE_ART_WIDTH = 320      -- 256 + 64: the four background pieces
local BOTTOM_ART_VISIBLE = 0.58 -- fraction of the bottom pieces that is painting, not black
local TALENTS_PER_TIER = PLAYER_TALENTS_PER_TIER or 5

-- mod-individual-progression's hidden progression quests; tab ranges must
-- stay in sync with build_era_tree.py's ERA_ORDER.
local PRE_TBC_QUEST = 66008
local TBC_TIER_5_QUEST = 66013
local ERAS = {
	vanilla = { start = 4, label = "Vanilla" },
	tbc     = { start = 7, label = "Burning Crusade" },
	wotlk   = { start = 1, label = "Wrath of the Lich King" },
}

-- Branch/arrow atlas coordinates. FrameXML defines these globally
-- (TalentFrameBase.lua); the copies below are the 3.3.5 values, used only
-- if that file ever isn't loaded.
local BRANCH_COORDS = TALENT_BRANCH_TEXTURECOORDS or {
	up          = { [1] = {0.12890625, 0.25390625, 0, 0.484375},   [-1] = {0.12890625, 0.25390625, 0.515625, 1.0} },
	down        = { [1] = {0, 0.125, 0.515625, 1.0},               [-1] = {0, 0.125, 0, 0.484375} },
	left        = { [1] = {0.2578125, 0.3828125, 0, 0.5},          [-1] = {0.2578125, 0.3828125, 0.5, 1.0} },
	right       = { [1] = {0.2578125, 0.3828125, 0, 0.5},          [-1] = {0.2578125, 0.3828125, 0.5, 1.0} },
	topright    = { [1] = {0.515625, 0.640625, 0, 0.5},            [-1] = {0.515625, 0.640625, 0.5, 1.0} },
	topleft     = { [1] = {0.640625, 0.765625, 0, 0.5},            [-1] = {0.640625, 0.765625, 0.5, 1.0} },
	bottomright = { [1] = {0.38671875, 0.51171875, 0, 0.5},        [-1] = {0.38671875, 0.51171875, 0.5, 1.0} },
	bottomleft  = { [1] = {0.7734375, 0.8984375, 0, 0.5},          [-1] = {0.7734375, 0.8984375, 0.5, 1.0} },
}
local ARROW_COORDS = TALENT_ARROW_TEXTURECOORDS or {
	top   = { [1] = {0, 0.5, 0, 0.5},   [-1] = {0, 0.5, 0.5, 1.0} },
	right = { [1] = {1.0, 0.5, 0, 0.5}, [-1] = {1.0, 0.5, 0.5, 1.0} },
	left  = { [1] = {0.5, 1.0, 0, 0.5}, [-1] = {0.5, 1.0, 0.5, 1.0} },
}

local GOLD = { 1, 0.82, 0 }
local GREEN = { 0.1, 1, 0.1 }
local GREY = { 0.5, 0.5, 0.5 }

local frame
local tabButtons = {}
local talentButtons = {}
local branchPool, arrowPool = {}, {}
local branchUsed, arrowUsed = 0, 0
local selectedLocalTab = 1
local currentEra = ERAS.vanilla

local function ActualTabIndex()
	return currentEra.start + selectedLocalTab - 1
end

local function TalentGroup()
	local ok, g = pcall(GetActiveTalentGroup)
	return (ok and g) or 1
end

local function CellPos(tier, column)
	return GRID_LEFT + (column - 1) * GRID_STEP, -(GRID_TOP + (tier - 1) * GRID_STEP)
end

-- ---------------------------------------------------------------------------
-- prerequisite lines

local function AcquireBranch()
	branchUsed = branchUsed + 1
	local t = branchPool[branchUsed]
	if not t then
		t = frame.child:CreateTexture(nil, "BORDER")
		t:SetTexture("Interface\\TalentFrame\\UI-TalentBranches")
		branchPool[branchUsed] = t
	end
	t:Show()
	return t
end

local function AcquireArrow()
	arrowUsed = arrowUsed + 1
	local t = arrowPool[arrowUsed]
	if not t then
		t = frame.child:CreateTexture(nil, "OVERLAY")
		t:SetTexture("Interface\\TalentFrame\\UI-TalentArrows")
		t:SetSize(ARROW_SIZE, ARROW_SIZE)
		arrowPool[arrowUsed] = t
	end
	t:Show()
	return t
end

local function PlaceBranch(kind, met, x, y, w, h)
	local t = AcquireBranch()
	t:SetTexCoord(unpack(BRANCH_COORDS[kind][met]))
	t:ClearAllPoints()
	t:SetPoint("TOPLEFT", frame.child, "TOPLEFT", x, y)
	t:SetSize(w or BRANCH_SIZE, h or BRANCH_SIZE)
end

local function PlaceArrow(kind, met, x, y)
	local t = AcquireArrow()
	t:SetTexCoord(unpack(ARROW_COORDS[kind][met]))
	t:ClearAllPoints()
	t:SetPoint("TOPLEFT", frame.child, "TOPLEFT", x, y)
end

-- Draws the line from a prerequisite at (pTier, pCol) to the talent at
-- (tier, col). `met` is 1 (bright) or -1 (greyed). `occupied[tier][col]`
-- says where talents sit so corners avoid running through one.
local function DrawPrereq(pTier, pCol, tier, col, met, occupied)
	local px, py = CellPos(pTier, pCol)
	local x, y = CellPos(tier, col)
	if pCol == col then
		-- straight down: stretch the vertical strip across the gap
		PlaceBranch("up", met, x + 1, py - BUTTON_SIZE, BRANCH_SIZE, (tier - pTier) * GRID_STEP - BUTTON_SIZE)
		PlaceArrow("top", met, x, y + BUTTON_SIZE / 2 + 5)
	elseif pTier == tier then
		local lx = math.min(px, x) + BUTTON_SIZE
		PlaceBranch("right", met, lx, y - 1, math.abs(x - px) - BUTTON_SIZE, BRANCH_SIZE)
		if pCol < col then
			PlaceArrow("left", met, x - BUTTON_SIZE / 2 - 5, y)
		else
			PlaceArrow("right", met, x + BUTTON_SIZE / 2 + 5, y)
		end
	else
		-- diagonal: across on the prereq's row, then down into the talent --
		-- unless a talent sits in that corner cell, then down first and
		-- across on the talent's row.
		local cornerFree = not (occupied[pTier] and occupied[pTier][col])
		if cornerFree then
			local cx, cy = CellPos(pTier, col)
			if pCol < col then
				PlaceBranch("right", met, px + BUTTON_SIZE, py - 1, cx + 1 - (px + BUTTON_SIZE), BRANCH_SIZE)
				PlaceBranch("topright", met, cx + 1, cy - 1)
			else
				PlaceBranch("right", met, cx + BRANCH_SIZE + 1, py - 1, px - (cx + BRANCH_SIZE + 1), BRANCH_SIZE)
				PlaceBranch("topleft", met, cx + 1, cy - 1)
			end
			PlaceBranch("up", met, x + 1, cy - 1 - BRANCH_SIZE, BRANCH_SIZE, (tier - pTier) * GRID_STEP - BRANCH_SIZE - 1)
			PlaceArrow("top", met, x, y + BUTTON_SIZE / 2 + 5)
		else
			local cx, cy = CellPos(tier, pCol)
			PlaceBranch("up", met, cx + 1, py - BUTTON_SIZE, BRANCH_SIZE, (tier - pTier) * GRID_STEP - BUTTON_SIZE + 1)
			if pCol < col then
				PlaceBranch("bottomleft", met, cx + 1, cy - 1)
				PlaceBranch("right", met, cx + BRANCH_SIZE + 1, y - 1, x - (cx + BRANCH_SIZE + 1), BRANCH_SIZE)
				PlaceArrow("left", met, x - BUTTON_SIZE / 2 - 5, y)
			else
				PlaceBranch("bottomright", met, cx + 1, cy - 1)
				PlaceBranch("right", met, x + BUTTON_SIZE, y - 1, cx + 1 - (x + BUTTON_SIZE), BRANCH_SIZE)
				PlaceArrow("right", met, x + BUTTON_SIZE / 2 + 5, y)
			end
		end
	end
end

-- ---------------------------------------------------------------------------
-- talent buttons

local function CreateTalentButton(i)
	local btn = CreateFrame("Button", "NekoTalentUIButton" .. i, frame.child)
	btn:SetSize(BUTTON_SIZE, BUTTON_SIZE)
	btn:RegisterForClicks("LeftButtonUp")

	btn.slot = btn:CreateTexture(nil, "BACKGROUND")
	btn.slot:SetTexture("Interface\\Buttons\\UI-EmptySlot")
	btn.slot:SetSize(64, 64)
	btn.slot:SetPoint("CENTER", 0, -1)

	btn.icon = btn:CreateTexture(nil, "ARTWORK")
	btn.icon:SetAllPoints()

	btn:SetNormalTexture("Interface\\Buttons\\UI-Quickslot2")
	btn:GetNormalTexture():SetSize(64, 64)
	btn:GetNormalTexture():ClearAllPoints()
	btn:GetNormalTexture():SetPoint("CENTER", 0, -1)
	btn:SetPushedTexture("Interface\\Buttons\\UI-Quickslot-Depress")
	btn:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")

	btn.rankBorder = btn:CreateTexture(nil, "OVERLAY")
	btn.rankBorder:SetTexture("Interface\\TalentFrame\\TalentFrame-RankBorder")
	btn.rankBorder:SetSize(32, 32)
	btn.rankBorder:SetPoint("CENTER", btn, "BOTTOMRIGHT", -2, 2)

	btn.rank = btn:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
	btn.rank:SetPoint("CENTER", btn.rankBorder, "CENTER", 0, 0)

	btn:SetScript("OnClick", function(self)
		if self.learnable then
			LearnTalent(ActualTabIndex(), self.talentIndex, false, TalentGroup())
		end
	end)
	btn:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
		local ok = pcall(GameTooltip.SetTalent, GameTooltip, ActualTabIndex(), self.talentIndex, false, false, TalentGroup())
		if not ok then
			GameTooltip:SetText(self.name or "?")
		end
		GameTooltip:Show()
	end)
	btn:SetScript("OnLeave", function() GameTooltip:Hide() end)
	return btn
end

local function LayoutBackground(height)
	-- Two anchors per piece, not SetSize: on this client a texture keeps
	-- its file's native height after SetTexture() if only sized, which left
	-- the bottom pieces at 128px and a black band under long trees.
	local k = height / 384
	local function Pin(t, left, top, right, bottom)
		t:ClearAllPoints()
		t:SetPoint("TOPLEFT", frame.child, "TOPLEFT", left * k, -top * k)
		t:SetPoint("BOTTOMRIGHT", frame.child, "TOPLEFT", right * k, -bottom * k)
	end
	Pin(frame.bgTopLeft, 0, 0, 256, 256)
	Pin(frame.bgTopRight, 256, 0, 320, 256)
	Pin(frame.bgBottomLeft, 0, 255, 256, 384)   -- 1px overlap hides the seam
	Pin(frame.bgBottomRight, 256, 255, 320, 384)
	-- The bottom pieces fade to solid black in roughly their lower 40% (the
	-- stock WotLK frame parks its last tiers on that black). Show only the
	-- painted part, stretched over the piece, so no band under the tree.
	frame.bgBottomLeft:SetTexCoord(0, 1, 0, BOTTOM_ART_VISIBLE)
	frame.bgBottomRight:SetTexCoord(0, 1, 0, BOTTOM_ART_VISIBLE)
end

local function SetTreeBackground(background)
	local base = background and background ~= "" and ("Interface\\TalentFrame\\" .. background) or nil
	-- Don't key off SetTexture's return value: it is nil on some clients
	-- even when the file loaded, which hid every tree's painting.
	if base then
		frame.bgTopLeft:SetTexture(base .. "-TopLeft")
		frame.bgTopRight:SetTexture(base .. "-TopRight")
		frame.bgBottomLeft:SetTexture(base .. "-BottomLeft")
		frame.bgBottomRight:SetTexture(base .. "-BottomRight")
		frame.bgTopLeft:Show(); frame.bgTopRight:Show(); frame.bgBottomLeft:Show(); frame.bgBottomRight:Show()
	else
		frame.bgTopLeft:Hide(); frame.bgTopRight:Hide(); frame.bgBottomLeft:Hide(); frame.bgBottomRight:Hide()
	end
end

local function UpdateTalents()
	local tabIndex = ActualTabIndex()
	local group = TalentGroup()
	local ok, name, icon, pointsSpent, background = pcall(GetTalentTabInfo, tabIndex)
	if not ok then name, pointsSpent = "?", 0 end
	pointsSpent = pointsSpent or 0

	SetTreeBackground(background)
	frame.treeName:SetText(name or "?")
	frame.treeIcon:SetTexture(icon)
	frame.spentText:SetText(string.format("%d point%s in %s", pointsSpent, pointsSpent == 1 and "" or "s", name or "?"))

	local okPts, unspent = pcall(GetUnspentTalentPoints)
	unspent = (okPts and unspent) or 0
	frame.pointsText:SetText(string.format("Talent Points: |cff%s%d|r", unspent > 0 and "00ff00" or "ffffff", unspent))

	local numTalents = select(2, pcall(GetNumTalents, tabIndex))
	if type(numTalents) ~= "number" then numTalents = 0 end

	-- first pass: layout + occupancy, so prereq lines can route around talents
	local occupied, maxTier = {}, 1
	local info = {}
	for i = 1, numTalents do
		local tok, tname, ticon, tier, column, rank, maxRank, _, meetsPrereq =
			pcall(GetTalentInfo, tabIndex, i, false, false, group)
		if tok and tname and tier and column then
			info[i] = { name = tname, icon = ticon, tier = tier, column = column,
			            rank = rank or 0, maxRank = maxRank or 0, meetsPrereq = meetsPrereq ~= false }
			occupied[tier] = occupied[tier] or {}
			occupied[tier][column] = i
			if tier > maxTier then maxTier = tier end
		end
	end
	local childHeight = math.max(SCROLL_HEIGHT, GRID_TOP + (maxTier - 1) * GRID_STEP + BUTTON_SIZE + GRID_TOP)
	frame.child:SetHeight(childHeight)
	LayoutBackground(childHeight)
	if NekoTalentUIDebug then
		DEFAULT_CHAT_FRAME:AddMessage(string.format("[neko] tiers=%d child=%d/%d scroll=%d range=%d bgTL=%dx%d bgBL=%dx%d bg=%s",
			maxTier, frame.child:GetWidth(), frame.child:GetHeight(), frame.scroll:GetHeight(), frame.scroll:GetVerticalScrollRange(),
			frame.bgTopLeft:GetWidth(), frame.bgTopLeft:GetHeight(), frame.bgBottomLeft:GetWidth(), frame.bgBottomLeft:GetHeight(),
			tostring(frame.bgBottomLeft:GetTexture())))
	end

	branchUsed, arrowUsed = 0, 0
	for i = 1, math.max(numTalents, #talentButtons) do
		local btn = talentButtons[i]
		if not btn then
			btn = CreateTalentButton(i)
			talentButtons[i] = btn
		end
		local t = info[i]
		if t then
			local tierUnlocked = (t.tier - 1) * TALENTS_PER_TIER <= pointsSpent
			local available = tierUnlocked and t.meetsPrereq
			local maxed = t.maxRank > 0 and t.rank >= t.maxRank
			btn.talentIndex, btn.name = i, t.name
			btn.learnable = available and not maxed and unspent > 0
			btn.icon:SetTexture(t.icon)
			btn:ClearAllPoints()
			btn:SetPoint("TOPLEFT", frame.child, "TOPLEFT", CellPos(t.tier, t.column))
			btn.rank:SetText(t.rank)
			local color = maxed and GOLD or (available and GREEN or GREY)
			btn.rank:SetTextColor(unpack(color))
			btn.rankBorder:SetVertexColor(unpack(available and { 1, 1, 1 } or GREY))
			btn.icon:SetDesaturated(not available)
			btn.slot:SetVertexColor(unpack(available and { 1, 1, 1 } or GREY))
			btn:Show()

			-- prerequisite lines (bright only if the prereq is satisfied and this tier is open)
			local pok = pcall(GetTalentPrereqs, tabIndex, i, false, false, group)
			if pok then
				local prereqs = { GetTalentPrereqs(tabIndex, i, false, false, group) }
				for p = 1, #prereqs, 4 do
					local pTier, pCol, isLearnable = prereqs[p], prereqs[p + 1], prereqs[p + 2]
					if pTier and pCol then
						DrawPrereq(pTier, pCol, t.tier, t.column, (isLearnable and tierUnlocked) and 1 or -1, occupied)
					end
				end
			end
		else
			btn:Hide()
		end
	end
	for i = branchUsed + 1, #branchPool do branchPool[i]:Hide() end
	for i = arrowUsed + 1, #arrowPool do arrowPool[i]:Hide() end
end

-- ---------------------------------------------------------------------------
-- frame

local function SelectLocalTab(i)
	selectedLocalTab = i
	PanelTemplates_SetTab(frame, i)
	frame.scroll:SetVerticalScroll(0)
	UpdateTalents()
end

local function CreateUI()
	frame = CreateFrame("Frame", "NekoTalentUIFrame", UIParent)
	frame:SetSize(FRAME_WIDTH, FRAME_HEIGHT)
	frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 16, -116)
	frame:SetMovable(true)
	frame:EnableMouse(true)
	frame:SetClampedToScreen(true)
	frame:RegisterForDrag("LeftButton")
	frame:SetScript("OnDragStart", frame.StartMoving)
	frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
	frame:SetToplevel(true)
	frame:Hide()
	tinsert(UISpecialFrames, "NekoTalentUIFrame")

	-- LearnTalent() is fire-and-forget; the rank/points change lands only
	-- after the server answers, and CHARACTER_POINTS_CHANGED is what the
	-- stock frame refreshes on for exactly that reason.
	frame:RegisterEvent("CHARACTER_POINTS_CHANGED")
	frame:RegisterEvent("PLAYER_TALENT_UPDATE")
	frame:RegisterEvent("UNIT_PORTRAIT_UPDATE")
	frame:SetScript("OnEvent", function(self, event, unit)
		if event == "UNIT_PORTRAIT_UPDATE" then
			if unit == "player" then SetPortraitTexture(self.portrait, "player") end
		elseif self:IsShown() then
			UpdateTalents()
		end
	end)

	-- stock 384x512 portrait frame art. The client only ships the bottom
	-- half under TalentFrame\; the stock talent frame takes its top half
	-- from the character sheet's art (checked against the MPQ listfile).
	local function Piece(file, w, h, point, x, y)
		local t = frame:CreateTexture(nil, "BORDER")
		t:SetTexture(file)
		t:SetSize(w, h)
		t:SetPoint(point, x, y)
		return t
	end
	Piece("Interface\\PaperDollInfoFrame\\UI-Character-General-TopLeft", 256, 256, "TOPLEFT", 0, 0)
	Piece("Interface\\PaperDollInfoFrame\\UI-Character-General-TopRight", 128, 256, "TOPRIGHT", 0, 0)
	Piece("Interface\\TalentFrame\\UI-TalentFrame-BotLeft", 256, 256, "BOTTOMLEFT", 0, 0)
	Piece("Interface\\TalentFrame\\UI-TalentFrame-BotRight", 128, 256, "BOTTOMRIGHT", 0, 0)

	frame.portrait = frame:CreateTexture(nil, "ARTWORK")
	frame.portrait:SetSize(60, 60)
	frame.portrait:SetPoint("TOPLEFT", 7, -6)
	SetPortraitTexture(frame.portrait, "player")

	frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	frame.title:SetPoint("TOP", 0, -17)
	frame.title:SetWidth(250)

	local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
	close:SetPoint("TOPRIGHT", -30, -8)

	-- tree header: icon + name on the left, points in tree on the right
	frame.treeIcon = frame:CreateTexture(nil, "ARTWORK")
	frame.treeIcon:SetSize(20, 20)
	frame.treeIcon:SetPoint("TOPLEFT", 72, -46)
	frame.treeIcon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
	frame.treeName = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	frame.treeName:SetPoint("LEFT", frame.treeIcon, "RIGHT", 6, 0)
	frame.spentText = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	frame.spentText:SetPoint("RIGHT", frame, "TOPRIGHT", -44, -56)

	-- scrolling tree
	frame.scroll = CreateFrame("ScrollFrame", "NekoTalentUIScrollFrame", frame, "UIPanelScrollFrameTemplate")
	frame.scroll:SetSize(SCROLL_WIDTH, SCROLL_HEIGHT)
	frame.scroll:SetPoint("TOPLEFT", 22, -76)
	frame.child = CreateFrame("Frame", "NekoTalentUIScrollChild", frame.scroll)
	frame.child:SetSize(TREE_ART_WIDTH, SCROLL_HEIGHT)
	frame.scroll:SetScrollChild(frame.child)
	frame.scroll:EnableMouseWheel(true)
	frame.scroll:SetScript("OnMouseWheel", function(self, delta)
		local max = self:GetVerticalScrollRange()
		self:SetVerticalScroll(math.max(0, math.min(max, self:GetVerticalScroll() - delta * GRID_STEP)))
	end)

	local fill = frame.child:CreateTexture(nil, "BACKGROUND", nil, -8)
	fill:SetTexture(0, 0, 0, 1)
	fill:SetAllPoints()
	-- The paintings are 320x384 in four pieces; era trees can be taller
	-- than that (TBC: 9 tiers), so LayoutBackground() scales all four
	-- uniformly to the scroll child's height rather than leaving the tail
	-- of the tree on black.
	local function Bg()
		return frame.child:CreateTexture(nil, "BACKGROUND", nil, -7)
	end
	frame.bgTopLeft, frame.bgTopRight, frame.bgBottomLeft, frame.bgBottomRight = Bg(), Bg(), Bg(), Bg()
	-- a soft dark wash so icons and lines read over the paintings
	local wash = frame.child:CreateTexture(nil, "BACKGROUND", nil, -6)
	wash:SetTexture(0, 0, 0, 0.25)
	wash:SetAllPoints()

	-- footer
	frame.pointsText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	frame.pointsText:SetPoint("BOTTOMLEFT", 30, 88)

	-- bottom tabs, stock character-frame style
	frame.numTabs = ERA_TAB_COUNT
	for i = 1, ERA_TAB_COUNT do
		local tab = CreateFrame("Button", "NekoTalentUIFrameTab" .. i, frame, "CharacterFrameTabButtonTemplate")
		tab:SetID(i)
		if i == 1 then
			tab:SetPoint("CENTER", frame, "BOTTOMLEFT", 60, 61)
		else
			tab:SetPoint("LEFT", tabButtons[i - 1], "RIGHT", -16, 0)
		end
		tab:SetScript("OnClick", function(self)
			PlaySound("igCharacterInfoTab")
			SelectLocalTab(self:GetID())
		end)
		tab:SetScript("OnEnter", function(self)
			local ok, tname, _, spent = pcall(GetTalentTabInfo, currentEra.start + self:GetID() - 1)
			if ok and tname then
				GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
				GameTooltip:SetText(tname, 1, 1, 1)
				GameTooltip:AddLine(string.format("%d point%s spent", spent or 0, (spent or 0) == 1 and "" or "s"), nil, nil, nil, true)
				GameTooltip:Show()
			end
		end)
		tab:SetScript("OnLeave", function() GameTooltip:Hide() end)
		tabButtons[i] = tab
	end
	PanelTemplates_SetNumTabs(frame, ERA_TAB_COUNT)
end

local function QuestDone(id)
	local ok, done = pcall(IsQuestFlaggedCompleted, id)
	return ok and done
end

local function DetectEra()
	if not QuestDone(PRE_TBC_QUEST) then
		return ERAS.vanilla
	elseif not QuestDone(TBC_TIER_5_QUEST) then
		return ERAS.tbc
	end
	return ERAS.wotlk
end

local function SetEra(era)
	currentEra = era
	selectedLocalTab = 1
	frame.title:SetText(era.label .. " Talents")
	for i, tab in ipairs(tabButtons) do
		local ok, name = pcall(GetTalentTabInfo, era.start + i - 1)
		tab:SetText((ok and name) or ("Tab " .. i))
		PanelTemplates_TabResize(tab, 0)
	end
end

local function Toggle()
	if not frame then
		CreateUI()
	end
	if frame:IsShown() then
		PlaySound("igCharacterInfoClose")
		frame:Hide()
	else
		PlaySound("igCharacterInfoOpen")
		SetEra(DetectEra())
		frame:Show()
		SelectLocalTab(selectedLocalTab)
	end
end

local function TakeOverNKeybind()
	-- Point the stock N key (TOGGLETALENTS) at Toggle() via a hidden
	-- button: SetBindingClick is the standard idiom for hijacking a default
	-- keybind, and the stock frame is what we're bypassing.
	if not _G["NekoTalentUIKeybindButton"] then
		local btn = CreateFrame("Button", "NekoTalentUIKeybindButton", UIParent)
		btn:SetScript("OnClick", Toggle)
	end
	SetBindingClick("N", "NekoTalentUIKeybindButton")
	SaveBindings(1) -- account-wide set, persists across sessions
end

local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:SetScript("OnEvent", TakeOverNKeybind)

SLASH_NEKOTALENTUI1 = "/neko"
SlashCmdList["NEKOTALENTUI"] = function(msg)
	if msg == "debug" then
		NekoTalentUIDebug = not NekoTalentUIDebug
		DEFAULT_CHAT_FRAME:AddMessage("[neko] debug " .. (NekoTalentUIDebug and "on" or "off"))
		return
	end
	Toggle()
end

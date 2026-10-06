--[[
Reports this client's NekoCore patch version to the realm and shows a popup
when the realm says it is out of date.

The version is NEKO_PATCH_VERSION from Version.lua, which
tools/install_patch/install_client.py writes with every patch build: a hash
of the MPQ and the addons, the same value the worldserver reads from
data/generated/patch-version.txt. The handshake is an addon whisper to
yourself -- WoW addons have no HTTP, and a whisper is the one addon channel
that needs no group or guild. src/PatchCheck.cpp swallows it and answers:

  client -> "NEKOPATCH"  "HELLO <version>"
  realm  -> "NEKOPATCH"  "OK" | "OUTDATED <realm's version>"

No answer means the realm does not check (no patch-version.txt), so nothing
is shown.
]]

local PREFIX = "NEKOPATCH"
local VERSION = NEKO_PATCH_VERSION or "unknown"

StaticPopupDialogs["NEKOPATCH_OUTDATED"] = {
    text = "Your NekoCore patch is out of date.\n\n"
        .. "Spells, talents and tooltips may not match the realm until you update.\n\n"
        .. "Close the game and run the NekoCore Launcher -- it updates the patch for you.",
    button1 = OKAY,
    timeout = 0,
    whileDead = true,
    hideOnEscape = true,
}

local frame = CreateFrame("Frame")
local sent = false

frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("CHAT_MSG_ADDON")
frame:SetScript("OnEvent", function(_, event, prefix, message, channel, sender)
    if event == "PLAYER_ENTERING_WORLD" then
        if sent then return end
        sent = true
        SendAddonMessage(PREFIX, "HELLO " .. VERSION, "WHISPER", UnitName("player"))
    elseif prefix == PREFIX and channel == "WHISPER" and sender == UnitName("player") then
        local status, wanted = message:match("^(%S+)%s*(%S*)")
        if status == "OUTDATED" then
            DEFAULT_CHAT_FRAME:AddMessage(string.format(
                "|cffff8000[NekoCore]|r Your patch (%s) is out of date (realm: %s). "
                .. "Close the game and run the NekoCore Launcher.", VERSION, wanted))
            StaticPopup_Show("NEKOPATCH_OUTDATED")
        end
    end
end)

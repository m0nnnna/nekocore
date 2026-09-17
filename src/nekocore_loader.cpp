/*
 * Module entry point -- the build system generates a call to
 * AddnekocoreScripts() (name derived from this module's directory name,
 * "nekocore", by modules/CMakeLists.txt's ConfigureScriptLoader) and expects
 * it to register every script class this module defines.
 */

void AddSC_era_talent_gate();

void AddnekocoreScripts()
{
    AddSC_era_talent_gate();
}

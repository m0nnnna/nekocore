/*
 * Module entry point -- the build system generates a call to
 * AddnekocoreScripts() (name derived from this module's directory name,
 * "nekocore", by modules/CMakeLists.txt's ConfigureScriptLoader) and expects
 * it to register every script class this module defines.
 */

void AddSC_era_talent_gate();
void AddSC_era_talent_info_remap();
void AddSC_era_progression_sync();
void AddSC_nekocore_mana_burn_scaling();
void AddSC_raid_lock();
void AddSC_world_elite_scaling();
void AddSC_nekolog();

void AddnekocoreScripts()
{
    AddSC_era_talent_gate();
    AddSC_era_talent_info_remap();
    AddSC_era_progression_sync();
    AddSC_nekocore_mana_burn_scaling();
    AddSC_raid_lock();
    AddSC_world_elite_scaling();
    AddSC_nekolog();
}

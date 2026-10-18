/*
 * Module entry point -- the build system generates a call to
 * AddnekocoreScripts() (name derived from this module's directory name,
 * "nekocore", by modules/CMakeLists.txt's ConfigureScriptLoader) and expects
 * it to register every script class this module defines.
 */

void AddSC_era_talent_gate();
void AddSC_era_talent_info_remap();
void AddSC_era_progression_sync();
void AddSC_era_spell_gate();
void AddSC_era_spell_sync();
void AddSC_era_talent_migration();
void AddSC_era_spell_scripts();
void AddSC_era_spell_fixups();
void AddSC_nekocore_mana_burn_scaling();
void AddSC_raid_lock();
void AddSC_world_elite_scaling();
void AddSC_nekolog();
void AddSC_nekocore_challenge_run();
void AddSC_nekocore_challenge_scaling();
void AddSC_nekocore_patch_check();
void AddSC_cc_stagger();
void AddSC_era_consumables();
void AddSC_era_hit_crit();

void AddnekocoreScripts()
{
    AddSC_era_talent_gate();
    AddSC_era_talent_info_remap();
    AddSC_era_progression_sync();
    AddSC_era_spell_gate();
    AddSC_era_spell_sync();
    AddSC_era_talent_migration();
    AddSC_era_spell_scripts();
    AddSC_era_spell_fixups();
    AddSC_nekocore_mana_burn_scaling();
    AddSC_raid_lock();
    AddSC_world_elite_scaling();
    AddSC_nekolog();
    AddSC_nekocore_challenge_run();
    AddSC_nekocore_challenge_scaling();
    AddSC_nekocore_patch_check();
    AddSC_cc_stagger();
    AddSC_era_consumables();
    AddSC_era_hit_crit();
}

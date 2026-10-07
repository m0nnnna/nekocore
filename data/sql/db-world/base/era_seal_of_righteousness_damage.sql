-- Binds src/EraSpellScripts.cpp's spell_era_pal_seal_of_righteousness_damage
-- to 25742, the hit spell every Seal of Righteousness casts. It is not an era
-- copy, so build_era_spell_sql.py's ERA_SCRIPTS cannot bind it. The script
-- only acts on hits from a Vanilla seal: it scales Judgement of the Crusader's
-- bonus down from the core's default 43% to the seal's 10%.

DELETE FROM `spell_script_names` WHERE `spell_id` = 25742 AND `ScriptName` = 'spell_era_pal_seal_of_righteousness_damage';
INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`) VALUES (25742, 'spell_era_pal_seal_of_righteousness_damage');

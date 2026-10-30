-- Soul Tap (16430): spell_nekocore_soul_tap_mana_scaling in
-- src/AutoBalanceManaBurnFix.cpp scales the unscaled mana-leech half.
DELETE FROM `spell_script_names` WHERE `ScriptName` = 'spell_nekocore_soul_tap_mana_scaling';
INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`) VALUES
(16430, 'spell_nekocore_soul_tap_mana_scaling');

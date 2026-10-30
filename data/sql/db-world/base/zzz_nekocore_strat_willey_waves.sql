-- Cannon Master Willey (10997) cast Summon Crimson Rifleman (17279) on a flat
-- 20 s timer, so a slow kill (a solo player, scaled health) saw 4 waves
-- before he reached 70%. Waves now come from his health instead: one as the
-- fight opens, then at 70%, 40% and 15% (each once per fight).
UPDATE `smart_scripts` SET `event_flags` = 1, `event_param3` = 0, `event_param4` = 0,
  `comment` = 'Cannon Master Willey - In Combat - Cast Summon Crimson Rifleman (opening wave)'
  WHERE `source_type` = 0 AND `entryorguid` = 10997 AND `id` = 2;
DELETE FROM `smart_scripts` WHERE `source_type` = 0 AND `entryorguid` = 10997 AND `id` IN (7,8,9);
INSERT INTO `smart_scripts` (`entryorguid`, `source_type`, `id`, `link`, `event_type`, `event_phase_mask`, `event_chance`, `event_flags`,
`event_param1`, `event_param2`, `event_param3`, `event_param4`, `event_param5`, `event_param6`,
`action_type`, `action_param1`, `action_param2`, `action_param3`, `action_param4`, `action_param5`, `action_param6`,
`target_type`, `target_param1`, `target_param2`, `target_param3`, `target_param4`, `target_x`, `target_y`, `target_z`, `target_o`, `comment`) VALUES
(10997, 0, 7, 0, 2, 0, 100, 1, 0, 70, 0, 0, 0, 0, 11, 17279, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Cannon Master Willey - Between Health 0-70% - Cast Summon Crimson Rifleman'),
(10997, 0, 8, 0, 2, 0, 100, 1, 0, 40, 0, 0, 0, 0, 11, 17279, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Cannon Master Willey - Between Health 0-40% - Cast Summon Crimson Rifleman'),
(10997, 0, 9, 0, 2, 0, 100, 1, 0, 15, 0, 0, 0, 0, 11, 17279, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Cannon Master Willey - Between Health 0-15% - Cast Summon Crimson Rifleman');

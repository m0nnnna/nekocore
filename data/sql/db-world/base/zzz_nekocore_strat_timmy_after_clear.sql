-- Timmy the Cruel (Stratholme) used to appear the moment one gate Crimson
-- Guardsman (guid 54069) died, i.e. while the door pull was still going.
-- Now Timmy watches for himself: once no live Crimson Guardsman (10418) is
-- within 65 yd of him he turns visible, hostile and starts his walk.
-- Guid script -54069: the death no longer touches Timmy (say + call for help stay).
UPDATE `smart_scripts` SET `link` = 0 WHERE `source_type` = 0 AND `entryorguid` = -54069 AND `id` = 5;
DELETE FROM `smart_scripts` WHERE `source_type` = 0 AND `entryorguid` = -54069 AND `id` IN (6,7,8);
DELETE FROM `smart_scripts` WHERE `source_type` = 0 AND `entryorguid` = 10808 AND `id` IN (5,6,7);
INSERT INTO `smart_scripts` (`entryorguid`, `source_type`, `id`, `link`, `event_type`, `event_phase_mask`, `event_chance`, `event_flags`,
`event_param1`, `event_param2`, `event_param3`, `event_param4`, `event_param5`, `event_param6`,
`action_type`, `action_param1`, `action_param2`, `action_param3`, `action_param4`, `action_param5`, `action_param6`,
`target_type`, `target_param1`, `target_param2`, `target_param3`, `target_param4`, `target_x`, `target_y`, `target_z`, `target_o`, `comment`) VALUES
(10808, 0, 5, 6, 1, 0, 100, 1, 2000, 2000, 2000, 2000, 0, 0, 47, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Timmy the Cruel - Out of Combat, no Guardsman alive nearby - Set Visible'),
(10808, 0, 6, 7, 61, 0, 100, 0, 0, 0, 0, 0, 0, 0, 2, 21, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Timmy the Cruel - Linked - Set Faction'),
(10808, 0, 7, 0, 61, 0, 100, 0, 0, 0, 0, 0, 0, 0, 232, 2472270, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'Timmy the Cruel - Linked - Start Waypoints');
DELETE FROM `conditions` WHERE `SourceTypeOrReferenceId` = 22 AND `SourceEntry` = 10808 AND `SourceId` = 0 AND `SourceGroup` = 6;
INSERT INTO `conditions` (`SourceTypeOrReferenceId`,`SourceGroup`,`SourceEntry`,`SourceId`,`ElseGroup`,`ConditionTypeOrReference`,`ConditionTarget`,`ConditionValue1`,`ConditionValue2`,`ConditionValue3`,`NegativeCondition`,`ErrorType`,`ErrorTextId`,`ScriptName`,`Comment`) VALUES
(22, 6, 10808, 0, 0, 29, 1, 10418, 65, 0, 1, 0, 0, '', 'Timmy the Cruel - only once no Crimson Guardsman is alive within 65 yd');

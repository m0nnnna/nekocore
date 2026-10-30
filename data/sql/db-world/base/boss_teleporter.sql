-- Boss Teleporter (src/BossTeleport.cpp, ScriptName item_nekocore_boss_teleporter):
-- use it, pick an instance, pick a boss, arrive at that boss.
--
-- Not sold or dropped anywhere; hand it out with `.additem 9000102`.
-- Cloned from the Hearthstone row (6948) so every column the client cares about
-- is known-good (it needs a use-spell for the client to show it as usable); the
-- script takes the use over, so the Hearthstone spell on it is never cast.

DELETE FROM `item_template` WHERE `entry` = 9000102;
DROP TEMPORARY TABLE IF EXISTS `tmp_boss_teleporter`;
CREATE TEMPORARY TABLE `tmp_boss_teleporter` SELECT * FROM `item_template` WHERE `entry` = 6948;
UPDATE `tmp_boss_teleporter` SET
    `entry` = 9000102, `name` = 'Boss Teleporter', `Quality` = 4,
    `description` = 'Teleports you to any boss in any dungeon.',
    `ScriptName` = 'item_nekocore_boss_teleporter';
INSERT INTO `item_template` SELECT * FROM `tmp_boss_teleporter`;
DROP TEMPORARY TABLE `tmp_boss_teleporter`;

DELETE FROM `npc_text` WHERE `ID` = 9000102;
INSERT INTO `npc_text` (`ID`, `text0_0`) VALUES
    (9000102, 'Where to?$B$BPick a dungeon, then the boss you want to stand in front of.');

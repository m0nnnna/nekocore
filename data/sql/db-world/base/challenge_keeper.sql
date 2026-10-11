-- The Challenge Keeper (src/ChallengeRun.cpp, ScriptName
-- npc_nekocore_challenge_keeper): the one place a challenge run is started.
--
-- Deliberately a separate NPC rather than extra gossip on Dungeon Dan
-- (mod-dungeonmaster, entry 197762): that module is third-party and
-- unpinned in this tree, so any gossip we bolted onto it would be lost the
-- next time it is updated. The Keeper stands next to him because the two go
-- together -- arm the run here, take his portal in.
--
-- Display 3437 is the same model every other service NPC on this realm uses
-- (Dungeon Dan, the XP Guide); it is known-good on a stock 3.3.5a client.
-- Swap `CreatureDisplayID` below if you want the Keeper to look distinct.

DELETE FROM `creature_template` WHERE `entry` = 9000101;
INSERT INTO `creature_template`
    (`entry`, `name`, `subname`, `gossip_menu_id`, `minlevel`, `maxlevel`, `exp`,
     `faction`, `npcflag`, `speed_walk`, `speed_run`, `speed_swim`, `speed_flight`,
     `rank`, `unit_class`, `unit_flags`, `type`, `type_flags`,
     `RegenHealth`, `flags_extra`, `ScriptName`, `VerifiedBuild`)
VALUES
    (9000101, 'Challenge Keeper', 'Dungeon Challenges', 0, 80, 80, 0,
     35, 1, 1, 1.14286, 1, 1,
     0, 1, 0, 7, 0,
     1, 2, 'npc_nekocore_challenge_keeper', 0);

DELETE FROM `creature_template_model` WHERE `CreatureID` = 9000101;
INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`, `VerifiedBuild`)
VALUES (9000101, 0, 3437, 1, 1, 0);

-- The greeting. Everything level-, era- and tier-specific is built into the
-- gossip ITEMS at run time (it depends on who is asking), so this text is
-- only the part that never changes.
DELETE FROM `npc_text` WHERE `ID` = 9000101;
INSERT INTO `npc_text` (`ID`, `text0_0`) VALUES
    (9000101, 'Outgrown a place, have you? Bring it back up to your level, then.$B$BI can set a dungeon''s inhabitants to fight you as equals -- no easier for being old. Clear one and I will have them ready for you, harder, the next time you come asking. Fail, and they will remember that too.$B$BPick your ground.');

-- Beside Dungeon Dan in both capitals, continuing the service row that
-- service_npcs.sql lays out (guids 5300700-5300725 are that file's, bar 5300722-3).
DELETE FROM `creature` WHERE `guid` BETWEEN 5300722 AND 5300723;
INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `spawnMask`, `phaseMask`, `equipment_id`, `position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, `currentwaypoint`, `curhealth`, `curmana`, `MovementType`, `npcflag`, `unit_flags`, `dynamicflags`, `ScriptName`, `VerifiedBuild`, `CreateObject`, `Comment`) VALUES
-- Stormwind, Trade District
(5300722, 9000101, 0, 0, 0, 1, 1, 0, -8812.97, 646.70, 94.56, 4.4795, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Challenge Keeper'),
-- Orgrimmar, Valley of Strength
(5300723, 9000101, 1, 0, 0, 1, 1, 0, 1607.26, -4445.65, 10.87, 1.7380, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Challenge Keeper');

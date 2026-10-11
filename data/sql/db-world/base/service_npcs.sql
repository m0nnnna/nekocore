-- Service NPC row in each faction capital, next to Gabriella (mod-assistant,
-- entry 9000000, whose own SQL spawns her): Transmogrifier (mod-transmog),
-- Dungeon Dan (mod-dungeonmaster), XP Guide (mod-xp-changer). Those modules
-- ship the creature_template but no spawn. The exchange NPCs (1116001/2)
-- stand in the same row but are spawned by ExchangeNpc.lua itself
-- (third-party-patches/Acore_ExchangeNpc sets their coordinates); Chromie
-- (Prestige) is spawned by that mod's own SQL near the Orgrimmar/Ironforge
-- gates.
DELETE FROM `creature` WHERE `guid` BETWEEN 5300700 AND 5300705;
INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `spawnMask`, `phaseMask`, `equipment_id`, `position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, `currentwaypoint`, `curhealth`, `curmana`, `MovementType`, `npcflag`, `unit_flags`, `dynamicflags`, `ScriptName`, `VerifiedBuild`, `CreateObject`, `Comment`) VALUES
-- Stormwind, Trade District
(5300700, 190010, 0, 0, 0, 1, 1, 0, -8821.73, 648.77, 94.56, 4.4795, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Transmogrifier'),
(5300701, 197762, 0, 0, 0, 1, 1, 0, -8818.81, 648.08, 94.56, 4.4795, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan'),
(5300702, 629100, 0, 0, 0, 1, 1, 0, -8815.89, 647.39, 94.56, 4.4795, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: XP Guide'),
-- Orgrimmar, Valley of Strength
(5300703, 190010, 1, 0, 0, 1, 1, 0, 1616.12, -4444.15, 10.87, 1.7380, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Transmogrifier'),
(5300704, 197762, 1, 0, 0, 1, 1, 0, 1613.16, -4444.65, 10.87, 1.7380, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan'),
(5300705, 629100, 1, 0, 0, 1, 1, 0, 1610.21, -4445.15, 10.87, 1.7380, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: XP Guide');

-- XP Guide (mod-xp-changer, 629100) at every race's spawn point (5 yards
-- ahead of where a new character appears, facing them) and beside Gabriella
-- in the remaining capitals + Shattrath/Dalaran.
DELETE FROM `creature` WHERE `guid` BETWEEN 5300706 AND 5300721;
INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `spawnMask`, `phaseMask`, `equipment_id`, `position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, `currentwaypoint`, `curhealth`, `curmana`, `MovementType`, `npcflag`, `unit_flags`, `dynamicflags`, `ScriptName`, `VerifiedBuild`, `CreateObject`, `Comment`) VALUES
(5300706, 629100, 0, 0, 0, 1, 1, 0, -8944.95, -132.49, 83.53, 3.142, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Human start, Northshire'),
(5300707, 629100, 1, 0, 0, 1, 1, 0, -613.52, -4251.67, 38.72, 3.142, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Orc/Troll start, Valley of Trials'),
(5300708, 629100, 0, 0, 0, 1, 1, 0, -6235.35, 330.50, 382.76, 3.035, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Dwarf/Gnome start, Coldridge Valley'),
(5300709, 629100, 1, 0, 0, 1, 1, 0, 10315.46, 829.69, 1326.41, 2.554, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Night Elf start, Shadowglen'),
(5300710, 629100, 0, 0, 0, 1, 1, 0, 1672.18, 1680.42, 121.67, 5.847, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Undead start, Deathknell'),
(5300711, 629100, 1, 0, 0, 1, 1, 0, -2912.58, -257.98, 53.00, 3.142, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Tauren start, Red Cloud Mesa'),
(5300712, 629100, 530, 0, 0, 1, 1, 0, 10352.44, -6361.41, 33.40, 2.174, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Blood Elf start, Sunstrider Isle'),
(5300713, 629100, 530, 0, 0, 1, 1, 0, -3964.09, -13926.84, 100.61, 5.226, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Draenei start, Ammen Vale'),
(5300714, 629100, 0, 0, 0, 1, 1, 0, -4953.92, -932.18, 501.66, 4.775, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Ironforge, next to Gabriella'),
(5300715, 629100, 0, 0, 0, 1, 1, 0, 1589.60, 275.33, -55.34, 0.361, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Undercity, next to Gabriella'),
(5300716, 629100, 1, 0, 0, 1, 1, 0, 9932.70, 2507.81, 1318.17, 4.787, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Darnassus, next to Gabriella'),
(5300717, 629100, 1, 0, 0, 1, 1, 0, -1290.68, 119.54, 131.18, 5.784, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Thunder Bluff, next to Gabriella'),
(5300718, 629100, 530, 0, 0, 1, 1, 0, -3954.62, -11672.97, -138.76, 3.291, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Exodar, next to Gabriella'),
(5300719, 629100, 530, 0, 0, 1, 1, 0, 9469.52, -7291.46, 14.31, 0.105, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Silvermoon, next to Gabriella'),
(5300720, 629100, 530, 0, 0, 1, 1, 0, -1815.28, 5423.08, -12.43, 2.875, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Shattrath, next to Gabriella'),
(5300721, 629100, 571, 0, 0, 1, 1, 0, 5788.78, 559.80, 650.66, 1.793, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore XP Guide: Dalaran, next to Gabriella');

-- Dungeon Dan (mod-dungeonmaster, 197762) in the two capitals that lacked
-- him (every capital has one now), three yards past the XP Guide in the same
-- row as Gabriella.
DELETE FROM `creature` WHERE `guid` BETWEEN 5300724 AND 5300731;
INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `spawnMask`, `phaseMask`, `equipment_id`, `position_x`, `position_y`, `position_z`, `orientation`, `spawntimesecs`, `wander_distance`, `currentwaypoint`, `curhealth`, `curmana`, `MovementType`, `npcflag`, `unit_flags`, `dynamicflags`, `ScriptName`, `VerifiedBuild`, `CreateObject`, `Comment`) VALUES
(5300724, 197762, 0, 0, 0, 1, 1, 0, -4950.92, -932.00, 501.66, 4.775, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Ironforge'),
(5300725, 197762, 1, 0, 0, 1, 1, 0, 9935.69, 2508.00, 1318.17, 4.787, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Darnassus'),
(5300726, 197762, 0, 0, 0, 1, 1, 0, 1588.54, 278.14, -55.34, 0.361, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Undercity'),
(5300727, 197762, 1, 0, 0, 1, 1, 0, -1289.24, 122.17, 131.18, 5.784, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Thunder Bluff'),
(5300728, 197762, 530, 0, 0, 1, 1, 0, -3954.17, -11675.94, -138.76, 3.291, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Exodar'),
(5300729, 197762, 530, 0, 0, 1, 1, 0, 9469.21, -7288.48, 14.31, 0.105, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Silvermoon'),
(5300730, 197762, 530, 0, 0, 1, 1, 0, -1816.07, 5420.19, -12.43, 2.875, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Shattrath'),
(5300731, 197762, 571, 0, 0, 1, 1, 0, 5785.85, 559.14, 650.66, 1.793, 300, 0, 0, 1, 0, 0, 0, 0, 0, '', 0, 0, 'nekocore service row: Dungeon Dan, Dalaran');

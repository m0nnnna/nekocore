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

-- XP Changer NPC (entry 629100)
DELETE FROM `creature_template` WHERE `entry` = 629100;
INSERT INTO `creature_template`
    (`entry`, `name`, `subname`, `gossip_menu_id`, `minlevel`, `maxlevel`, `exp`,
     `faction`, `npcflag`, `speed_walk`, `speed_run`, `speed_swim`, `speed_flight`,
     `scale`, `rank`, `unit_class`, `unit_flags`, `type`, `type_flags`,
     `RegenHealth`, `flags_extra`, `ScriptName`, `VerifiedBuild`)
VALUES
    (629100, 'XP Guide', 'Experience Advisor', 0, 80, 80, 0,
     35, 1, 1, 1.14286, 1, 1,
     1, 0, 1, 0, 7, 0,
     1, 2, 'npc_xp_changer', 0);

DELETE FROM `creature_template_model` WHERE `CreatureID` = 629100;
INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`, `VerifiedBuild`)
VALUES (629100, 0, 3437, 1, 1, 0);

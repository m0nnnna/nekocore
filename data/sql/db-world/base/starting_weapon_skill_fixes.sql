-- Starting weapon skills that the outfits hand out but nothing grants.
-- Applies in filename order AFTER mod-individual-progression's
-- player_starting_weapon_skills.sql (which DELETEs whole skills and
-- re-inserts its pre-3.3 rows) and mod-uac's mod_uac_playercreateinfo_skills.sql,
-- so these rows survive both. If either of those files changes (re-applied by
-- hash), this one must be re-applied too -- bump the comment below to force it.

DELETE FROM `playercreateinfo_skills` WHERE `comment` LIKE 'nekocore: %';

-- mod-uac gives Orc/Undead/Tauren/Troll paladins Blood Elf's starter set
-- (Battleworn Claymore 23346, a 2H sword) but only Blood Elf paladins get
-- Two-Handed Swords at creation. raceMask 178 = Orc|Undead|Tauren|Troll.
INSERT INTO `playercreateinfo_skills` (`raceMask`, `classMask`, `skill`, `rank`, `comment`) VALUES
(178, 2, 55, 0, 'nekocore: mod-uac horde paladin 2H swords');

-- Every warlock outfit (stock races too) contains a Bent Staff (35), but
-- individual-progression's Staves row is classMask 1216 (druid|mage|shaman)
-- -- warlocks are left with Daggers only and an unequippable staff.
INSERT INTO `playercreateinfo_skills` (`raceMask`, `classMask`, `skill`, `rank`, `comment`) VALUES
(0, 256, 136, 0, 'nekocore: warlock Staves (outfit gives Bent Staff)');

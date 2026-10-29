-- Shield spike procs (Iron 9784, Mithril 9782, Thorium 16624, Felsteel 29455,
-- Titanium 56355) are physical damage-shield procs, so target armor was
-- shaving the Mithril 16-20 down to ~10-11. Flag them SPELL_ATTR0_CU_IGNORE_ARMOR
-- (0x8000) so they deal their listed damage. Loaded at worldserver start.
DELETE FROM `spell_custom_attr` WHERE `spell_id` IN (9784,9782,16624,29455,56355);
INSERT INTO `spell_custom_attr` (`spell_id`,`attributes`) VALUES
(9784,32768),(9782,32768),(16624,32768),(29455,32768),(56355,32768);

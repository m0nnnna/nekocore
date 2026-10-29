-- Profession cooldowns (transmutes, Mooncloth family, spheres, Glacial Bag, Salt
-- Shaker...) capped at 5 minutes. Stock values live in spell_cooldown_overrides (the
-- era ones) or in Spell.dbc (the WotLK ones), so every spell is forced via that table.
UPDATE `spell_cooldown_overrides`
   SET `RecoveryTime` = 300000, `CategoryRecoveryTime` = 300000
 WHERE `RecoveryTime` >= 3600000 OR `CategoryRecoveryTime` >= 3600000;

INSERT INTO `spell_cooldown_overrides` (`Id`, `RecoveryTime`, `CategoryRecoveryTime`, `StartRecoveryTime`, `StartRecoveryCategory`, `Comment`) VALUES
(28580, 300000, 300000, 0, 0, 'Transmute: Primal Shadow to Water - 5 minutes'),
(28581, 300000, 300000, 0, 0, 'Transmute: Primal Water to Shadow - 5 minutes'),
(28582, 300000, 300000, 0, 0, 'Transmute: Primal Mana to Fire - 5 minutes'),
(28583, 300000, 300000, 0, 0, 'Transmute: Primal Fire to Mana - 5 minutes'),
(28584, 300000, 300000, 0, 0, 'Transmute: Primal Life to Earth - 5 minutes'),
(28585, 300000, 300000, 0, 0, 'Transmute: Primal Earth to Life - 5 minutes'),
(53771, 300000, 300000, 0, 0, 'Transmute: Eternal Life to Shadow - 5 minutes'),
(53773, 300000, 300000, 0, 0, 'Transmute: Eternal Life to Fire - 5 minutes'),
(53774, 300000, 300000, 0, 0, 'Transmute: Eternal Fire to Water - 5 minutes'),
(53775, 300000, 300000, 0, 0, 'Transmute: Eternal Fire to Life - 5 minutes'),
(53776, 300000, 300000, 0, 0, 'Transmute: Eternal Air to Water - 5 minutes'),
(53777, 300000, 300000, 0, 0, 'Transmute: Eternal Air to Earth - 5 minutes'),
(53779, 300000, 300000, 0, 0, 'Transmute: Eternal Shadow to Earth - 5 minutes'),
(53780, 300000, 300000, 0, 0, 'Transmute: Eternal Shadow to Life - 5 minutes'),
(53781, 300000, 300000, 0, 0, 'Transmute: Eternal Earth to Air - 5 minutes'),
(53782, 300000, 300000, 0, 0, 'Transmute: Eternal Earth to Shadow - 5 minutes'),
(53783, 300000, 300000, 0, 0, 'Transmute: Eternal Water to Air - 5 minutes'),
(53784, 300000, 300000, 0, 0, 'Transmute: Eternal Water to Fire - 5 minutes'),
(54020, 300000, 300000, 0, 0, 'Transmute: Eternal Might - 5 minutes'),
(66658, 300000, 300000, 0, 0, 'Transmute: Ametrine - 5 minutes'),
(66659, 300000, 300000, 0, 0, 'Transmute: Cardinal Ruby - 5 minutes'),
(66660, 300000, 300000, 0, 0, 'Transmute: King''s Amber - 5 minutes'),
(66662, 300000, 300000, 0, 0, 'Transmute: Dreadstone - 5 minutes'),
(66663, 300000, 300000, 0, 0, 'Transmute: Majestic Zircon - 5 minutes'),
(66664, 300000, 300000, 0, 0, 'Transmute: Eye of Zul - 5 minutes'),
(60893, 300000, 300000, 0, 0, 'Northrend Alchemy Research - 5 minutes'),
(28027, 300000, 300000, 0, 0, 'Prismatic Sphere - 5 minutes'),
(28028, 300000, 300000, 0, 0, 'Void Sphere - 5 minutes'),
(47280, 300000, 300000, 0, 0, 'Brilliant Glass - 5 minutes'),
(62242, 300000, 300000, 0, 0, 'Icy Prism - 5 minutes'),
(56005, 300000, 300000, 0, 0, 'Glacial Bag - 5 minutes')
ON DUPLICATE KEY UPDATE `RecoveryTime` = VALUES(`RecoveryTime`),
    `CategoryRecoveryTime` = VALUES(`CategoryRecoveryTime`), `Comment` = VALUES(`Comment`);

-- Salt Shaker (item 15846): the cooldown sits on the item's use spell.
UPDATE `item_template` SET `spellcooldown_1` = 300000, `spellcategorycooldown_1` = 300000
 WHERE `entry` = 15846;

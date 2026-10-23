-- Turn-in quest items keep their WotLK stack sizes.
--
-- mod-individual-progression's zz_optional_item_stack_sizes.sql caps
-- Un'Goro's power crystals at 10 and the Scourgestones at 20. Both are
-- farmed in hundreds for repeatable turn-ins (the crystals for A-Me 01's
-- and the pylon quests, the stones for the Argent Dawn), so the cap is
-- only bag clutter. Back to the base item_template values. Runs after it
-- by name. Idempotent.
UPDATE `item_template` SET `stackable` = 100 WHERE `entry` IN (
    11184, -- Blue Power Crystal
    11185, -- Green Power Crystal
    11186, -- Red Power Crystal
    11188  -- Yellow Power Crystal
);
UPDATE `item_template` SET `stackable` = 250 WHERE `entry` IN (
    12840, -- Minion's Scourgestone
    12841, -- Invader's Scourgestone
    12843  -- Corruptor's Scourgestone
);

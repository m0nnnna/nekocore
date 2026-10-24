-- Deliberate departures from 1.12 mob behaviour, for playability.
--
-- zzz_nekocore_classic_dungeon_mobs.sql (generated) puts dungeon mobs back
-- on their 1.12 spells and timers. A few of those are fine for a five-man
-- group but lock a smaller or solo party out entirely. Overrides live here,
-- not in the generated file, so a rebuild of that file keeps them. Sorts
-- after it, so it applies last. Every statement checks the row's current
-- values, so it is safe to re-run.

-- Subterranean Diemetradon (Maraudon): 1.12 Sonic Burst (308281) is a
-- 10-yard AoE silence lasting 10 s, cast every 10-14 s while the target is
-- within 8 yards -- a permanent silence once two of them are pulled.
-- Reported by wyrd. The silence keeps its 1.12 length; the repeat goes to
-- 20-26 s so there is always a casting window between bursts.
UPDATE `smart_scripts` SET `event_param3` = 20000, `event_param4` = 26000
WHERE `source_type` = 0 AND `entryorguid` = 13323 AND `id` = 0
  AND `event_type` = 9 AND `action_type` = 11 AND `action_param1` = 308281
  AND `event_param3` = 10000 AND `event_param4` = 14000;

-- Shade of Hakkar (Sunken Temple egg event): a Nightmare Suppressor comes
-- in from each side, first at 10 s and 45 s, then each every 70 s -- one
-- every 35 s. Each one left standing at the altar adds to the counter that
-- fails the event, which a solo player cannot keep up with while also
-- lighting the braziers. Reported by wyrd. Spawns go ~40% slower: first at
-- 14 s and 64 s, then each every 100 s (one every 50 s). The Hakkari
-- Bloodkeepers (rows 19-20) keep their timers.
UPDATE `smart_scripts` SET `event_param1` = 14000, `event_param2` = 14000,
  `event_param3` = 100000, `event_param4` = 100000
WHERE `source_type` = 0 AND `entryorguid` = 8440 AND `id` = 21
  AND `event_type` = 60 AND `action_type` = 12 AND `action_param1` = 8497
  AND `event_param1` = 10000 AND `event_param3` = 70000;
UPDATE `smart_scripts` SET `event_param1` = 64000, `event_param2` = 64000,
  `event_param3` = 100000, `event_param4` = 100000
WHERE `source_type` = 0 AND `entryorguid` = 8440 AND `id` = 22
  AND `event_type` = 60 AND `action_type` = 12 AND `action_param1` = 8497
  AND `event_param1` = 45000 AND `event_param3` = 70000;

-- Ring of Law trash waves (Blackrock Depths): Grimstone's waves are
-- normal-rank mobs, but the base HealthModifier (up to 3.0) plus the
-- progression module's 1.12 DamageModifier (up to 3.7) puts them close to
-- elite strength even after AutoBalance's solo multiplier -- a Deep Stinger
-- still has ~3k HP and hits for over 100 solo. Reported by wyrd. The
-- heaviest modifiers come down; the weak ones (Dark Screecher, Borer Beetle)
-- keep theirs. Each statement only matches the values it replaces.
UPDATE `creature_template` SET `DamageModifier` = 1.5
WHERE `entry` = 8925 AND `DamageModifier` = 2.0;                            -- Dredge Worm
UPDATE `creature_template` SET `DamageModifier` = 2.0, `HealthModifier` = 2.0
WHERE `entry` = 8926 AND `DamageModifier` = 3.7 AND `HealthModifier` = 3;  -- Deep Stinger
UPDATE `creature_template` SET `DamageModifier` = 2.0, `HealthModifier` = 1.8
WHERE `entry` = 8928 AND `DamageModifier` = 3.0 AND `HealthModifier` = 2.5; -- Burrowing Thundersnout
UPDATE `creature_template` SET `DamageModifier` = 2.0, `HealthModifier` = 1.8
WHERE `entry` = 8933 AND `DamageModifier` = 3.0 AND `HealthModifier` = 2.5; -- Cave Creeper

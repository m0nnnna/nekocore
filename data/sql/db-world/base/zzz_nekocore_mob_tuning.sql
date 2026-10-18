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

-- Stratholme: the Rockwing Gargoyle/Screecher patrols (10408/10409) and the
-- Eyes of Naxxramas (10411) respawned on 30/15 min timers while every other
-- spawn in the instance is on 24 h (i.e. never within a run).
UPDATE `creature` SET `spawntimesecs` = 86400
WHERE `map` = 329 AND `id` IN (10408, 10409, 10411) AND `spawntimesecs` < 86400;

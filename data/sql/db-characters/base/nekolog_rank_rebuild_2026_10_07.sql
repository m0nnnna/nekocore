-- One-time rebuild of nekolog_rank (derived data; the website refills it from
-- nekolog_event on the next log or rankings view). Rows written before
-- 2026-10-07 judged "over-level" against each boss's own level rather than the
-- dungeon's (www/inc/logs.php nl_dungeon_level), so on-level Shadowfang Keep
-- kills of the level-20/22 bosses were left unranked. The updater applies this
-- once; keep the file unchanged so it is not re-run.

TRUNCATE TABLE `nekolog_rank`;

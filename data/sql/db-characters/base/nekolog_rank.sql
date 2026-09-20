-- NekoLog rankings summary: one row per (kill encounter, player). Filled by
-- the website (www/inc/logs.php nl_refresh_ranks) from nekolog_event the
-- first time a finished kill is seen, so rankings pages never aggregate raw
-- events on the fly. Pets are folded into their owner. Derived data only --
-- safe to TRUNCATE; it rebuilds itself.

CREATE TABLE IF NOT EXISTS `nekolog_rank` (
  `enc_id`      BIGINT UNSIGNED NOT NULL,
  `guid`        BIGINT UNSIGNED NOT NULL,             -- player actor guid (raw)
  `run_id`      BIGINT UNSIGNED NOT NULL,
  `boss_entry`  INT UNSIGNED NOT NULL,
  `map_id`      INT UNSIGNED NOT NULL,
  `char_guid`   INT UNSIGNED NOT NULL DEFAULT 0,
  `name`        VARCHAR(100) NOT NULL DEFAULT '',
  `class`       TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `spec`        TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `level`       TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `players`     TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `era`         TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- encounter max_era
  `duration_ms` INT UNSIGNED NOT NULL,
  `damage`      BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `healing`     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `dps`         FLOAT NOT NULL DEFAULT 0,
  `hps`         FLOAT NOT NULL DEFAULT 0,
  `killed_at`   INT UNSIGNED NOT NULL,                -- unix time of the kill
  `eligible`    TINYINT UNSIGNED NOT NULL DEFAULT 1,  -- 0 = someone in the kill was over-level; logged, never ranked
  `boss_level`  TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `max_level`   TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- highest participant level
  PRIMARY KEY (`enc_id`, `guid`),
  KEY `boss_dps` (`boss_entry`, `eligible`, `dps`),
  KEY `boss_hps` (`boss_entry`, `eligible`, `hps`),
  KEY `boss_speed` (`boss_entry`, `eligible`, `duration_ms`),
  KEY `char` (`char_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

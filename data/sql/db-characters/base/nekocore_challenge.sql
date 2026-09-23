-- Challenge runs (src/ChallengeRun.cpp, src/ChallengeScaling.cpp). Lives in
-- the characters DB for the same two reasons nekolog.sql does: the website's
-- existing chars connection can read it, and it survives world-DB reimports.
-- Every row here is written by the worldserver itself -- the Challenge Keeper
-- NPC and the instance hooks are the only writers, nothing is uploaded.
--
-- Deliberately separate tables from nekolog_*, not extra columns on them: a
-- challenge run is a different THING from a combat log (it has a tier, a
-- bracket, a pass/fail, and it exists from the moment the instance is flagged,
-- before any boss is pulled and therefore before NekoLog has opened a run at
-- all). The two are joined by `log_run_id` when NekoLog does open one, which
-- is what lets the website show a challenge run's full combat log through the
-- same log.php page while listing challenge runs on their own page.

-- One row per (character, dungeon, bracket). The tier IS the difficulty: the
-- multipliers are derived from it at run time (1 + step * tier), never stored,
-- so retuning Nekocore.Challenge.HealthStep/DamageStep retunes every existing
-- tier instead of leaving old rows on old numbers.
CREATE TABLE IF NOT EXISTS `nekocore_challenge_tier` (
  `char_guid`  INT UNSIGNED NOT NULL,                  -- characters.guid
  `map_id`     INT UNSIGNED NOT NULL,
  `bracket`    TINYINT UNSIGNED NOT NULL,              -- 60 Vanilla / 70 TBC / 80 WotLK
  `tier`       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `best_tier`  SMALLINT UNSIGNED NOT NULL DEFAULT 0,   -- highest tier ever CLEARED (a wipe can't take this away)
  `clears`     INT UNSIGNED NOT NULL DEFAULT 0,
  `fails`      INT UNSIGNED NOT NULL DEFAULT 0,
  `updated_at` INT UNSIGNED NOT NULL DEFAULT 0,        -- unix time
  PRIMARY KEY (`char_guid`, `map_id`, `bracket`),
  KEY `ladder` (`map_id`, `bracket`, `best_tier`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One row per flagged challenge instance. Created when the instance is
-- flagged (on the leader's entry), closed when it is cleared, wiped or
-- abandoned.
CREATE TABLE IF NOT EXISTS `nekocore_challenge_run` (
  `id`           BIGINT UNSIGNED NOT NULL,
  `map_id`       INT UNSIGNED NOT NULL,
  `instance_id`  INT UNSIGNED NOT NULL,
  `map_name`     VARCHAR(64) NOT NULL DEFAULT '',
  `bracket`      TINYINT UNSIGNED NOT NULL,
  `tier`         SMALLINT UNSIGNED NOT NULL,           -- the tier this run was set to
  `health_mult`  FLOAT NOT NULL DEFAULT 1,             -- what the tier worked out to, recorded so a
  `damage_mult`  FLOAT NOT NULL DEFAULT 1,             --   later retune doesn't rewrite history
  `era`          TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- mod-individual-progression state of the leader
  `leader_guid`  INT UNSIGNED NOT NULL DEFAULT 0,      -- characters.guid of whoever armed it
  `leader_name`  VARCHAR(100) NOT NULL DEFAULT '',
  `log_run_id`   BIGINT UNSIGNED NOT NULL DEFAULT 0,   -- nekolog_run.id once a boss is pulled, else 0
  `started_at`   INT UNSIGNED NOT NULL,                -- unix time
  `ended_at`     INT UNSIGNED NOT NULL DEFAULT 0,
  `result`       TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- 0 in progress, 1 cleared, 2 wiped, 3 abandoned
  `bosses`       SMALLINT UNSIGNED NOT NULL DEFAULT 0, -- boss kills during the run
  `deaths`       SMALLINT UNSIGNED NOT NULL DEFAULT 0, -- player deaths during the run
  PRIMARY KEY (`id`),
  KEY `map_bracket` (`map_id`, `bracket`, `started_at`),
  KEY `result_tier` (`result`, `tier`),
  KEY `started` (`started_at`),
  KEY `log_run` (`log_run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Who was in the instance for a challenge run. Recorded on entry (not at the
-- end), so someone who dies and releases is still a participant, and so the
-- tier change on clear/wipe hits everyone who was actually there.
CREATE TABLE IF NOT EXISTS `nekocore_challenge_member` (
  `run_id`     BIGINT UNSIGNED NOT NULL,
  `char_guid`  INT UNSIGNED NOT NULL,
  `name`       VARCHAR(100) NOT NULL DEFAULT '',
  `class`      TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `race`       TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `level`      TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `spec`       TINYINT UNSIGNED NOT NULL DEFAULT 0,    -- Player::GetMostPointsTalentTree()
  `tier_before` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `tier_after`  SMALLINT UNSIGNED NOT NULL DEFAULT 0,  -- filled when the run closes
  PRIMARY KEY (`run_id`, `char_guid`),
  KEY `char` (`char_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

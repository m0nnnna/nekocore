-- NekoLog: server-side combat logging (src/NekoLog.cpp). Lives in the
-- characters DB so the website's existing chars connection can read it and
-- so it survives world-DB reimports. Every row is written by the worldserver
-- itself -- nothing here ever comes from a client upload.

CREATE TABLE IF NOT EXISTS `nekolog_run` (
  `id`          BIGINT UNSIGNED NOT NULL,
  `map_id`      INT UNSIGNED NOT NULL,
  `instance_id` INT UNSIGNED NOT NULL,
  `map_name`    VARCHAR(64) NOT NULL DEFAULT '',
  `spawn_mode`  TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- Map::GetSpawnMode(): 0 normal/10, 1 heroic/25 ...
  `is_raid`     TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `max_players` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `started_at`  INT UNSIGNED NOT NULL,                  -- unix time
  `ended_at`    INT UNSIGNED NOT NULL DEFAULT 0,        -- 0 while the instance is still alive
  `kills`       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `wipes`       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `map_started` (`map_id`, `started_at`),
  KEY `started` (`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `nekolog_encounter` (
  `id`          BIGINT UNSIGNED NOT NULL,
  `run_id`      BIGINT UNSIGNED NOT NULL,
  `boss_entry`  INT UNSIGNED NOT NULL,
  `boss_guid`   BIGINT UNSIGNED NOT NULL,
  `boss_name`   VARCHAR(100) NOT NULL DEFAULT '',
  `start_ms`    INT UNSIGNED NOT NULL,                  -- ms since run start
  `end_ms`      INT UNSIGNED NOT NULL DEFAULT 0,
  `result`      TINYINT UNSIGNED NOT NULL DEFAULT 0,    -- 0 in progress, 1 kill, 2 wipe/reset
  `players`     TINYINT UNSIGNED NOT NULL DEFAULT 0,    -- players in the instance when it started
  `min_era`     TINYINT UNSIGNED NOT NULL DEFAULT 0,    -- lowest / highest mod-individual-progression
  `max_era`     TINYINT UNSIGNED NOT NULL DEFAULT 0,    --   state among those players
  PRIMARY KEY (`id`),
  KEY `run` (`run_id`),
  KEY `boss_result` (`boss_entry`, `result`, `end_ms`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Everything that acted or was acted on during a run, once per run.
-- kind: 1 player, 2 pet/guardian/totem (owner set), 3 creature
CREATE TABLE IF NOT EXISTS `nekolog_actor` (
  `run_id`  BIGINT UNSIGNED NOT NULL,
  `guid`    BIGINT UNSIGNED NOT NULL,                   -- ObjectGuid raw value
  `kind`    TINYINT UNSIGNED NOT NULL,
  `entry`   INT UNSIGNED NOT NULL DEFAULT 0,            -- creature entry / 0 for players
  `name`    VARCHAR(100) NOT NULL DEFAULT '',
  `class`   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `race`    TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `level`   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `spec`    TINYINT UNSIGNED NOT NULL DEFAULT 0,        -- Player::GetMostPointsTalentTree()
  `owner`   BIGINT UNSIGNED NOT NULL DEFAULT 0,         -- for pets: the player's guid
  `char_guid` INT UNSIGNED NOT NULL DEFAULT 0,          -- characters.guid for players
  PRIMARY KEY (`run_id`, `guid`),
  KEY `char_guid` (`char_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Who was in the instance when an encounter began (era snapshot per player).
CREATE TABLE IF NOT EXISTS `nekolog_participant` (
  `enc_id`    BIGINT UNSIGNED NOT NULL,
  `guid`      BIGINT UNSIGNED NOT NULL,
  `era`       TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`enc_id`, `guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- kind: 1 damage, 2 heal, 3 death, 4 cast, 5 aura apply, 6 aura remove
-- amount: final damage / effective heal.  extra: mitigated (damage) / overheal (heal)
-- flags: bit0 periodic
CREATE TABLE IF NOT EXISTS `nekolog_event` (
  `id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `run_id`  BIGINT UNSIGNED NOT NULL,
  `enc_id`  BIGINT UNSIGNED NOT NULL,                   -- only boss encounters are logged
  `t_ms`    INT UNSIGNED NOT NULL,                      -- ms since run start
  `kind`    TINYINT UNSIGNED NOT NULL,
  `src`     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `dst`     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `spell`   INT UNSIGNED NOT NULL DEFAULT 0,
  `amount`  INT NOT NULL DEFAULT 0,
  `extra`   INT NOT NULL DEFAULT 0,
  `school`  TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `flags`   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `enc_kind` (`enc_id`, `kind`),
  KEY `run_t` (`run_id`, `t_ms`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Spell names, filled lazily by the server the first time a spell shows up
-- (the site has no DBC access).
CREATE TABLE IF NOT EXISTS `nekolog_spell` (
  `id`     INT UNSIGNED NOT NULL,
  `name`   VARCHAR(100) NOT NULL DEFAULT '',
  `school` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

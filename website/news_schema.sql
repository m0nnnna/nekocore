-- News posts for the NekoCore website.
-- Run once against the auth database (acore_auth), next to the other web_* tables:
--   mysql -u acore -p acore_auth < news_schema.sql

CREATE TABLE IF NOT EXISTS `web_news` (
  `id`           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `slug`         VARCHAR(120)  NOT NULL,
  `title`        VARCHAR(200)  NOT NULL,
  `category`     VARCHAR(32)   NOT NULL DEFAULT 'announcement',
  `summary`      VARCHAR(500)  DEFAULT NULL,
  `body`         MEDIUMTEXT    NOT NULL,
  `author`       VARCHAR(32)   NOT NULL DEFAULT 'NekoCore',
  `status`       ENUM('draft','published') NOT NULL DEFAULT 'draft',
  `pinned`       TINYINT(1)    NOT NULL DEFAULT 0,
  `published_at` DATETIME      DEFAULT NULL,
  `created_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_slug` (`slug`),
  KEY `idx_published` (`status`, `published_at`),
  KEY `idx_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

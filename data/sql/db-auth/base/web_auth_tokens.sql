-- Backs the website's email verification and password reset flows
-- (website/www/index.php registration, verify_email.php, forgot_password.php,
-- reset_password.php). Neither AzerothCore itself nor any of its existing
-- `account` columns are touched -- these are two new, independent tables in
-- acore_auth, since that's the database the website already talks to and
-- both features are keyed off account data that lives there.
--
-- Only a SHA-256 hash of each token is ever stored; the raw token exists
-- only in the emailed link and briefly in PHP memory, so a database leak
-- alone never yields a usable token.

CREATE TABLE IF NOT EXISTS `web_email_verification` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `username` VARCHAR(32) NOT NULL,
    `email` VARCHAR(255) NOT NULL,
    `salt` VARBINARY(32) NOT NULL,
    `verifier` VARBINARY(32) NOT NULL,
    `token_hash` CHAR(64) NOT NULL,
    `last_ip` VARCHAR(45) NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `expires_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_web_email_verification_username` (`username`),
    UNIQUE KEY `uq_web_email_verification_email` (`email`),
    KEY `idx_web_email_verification_token_hash` (`token_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `web_password_reset` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `account_id` INT UNSIGNED NOT NULL,
    `token_hash` CHAR(64) NOT NULL,
    `used` TINYINT(1) NOT NULL DEFAULT 0,
    `last_ip` VARCHAR(45) NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `expires_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_web_password_reset_account_id` (`account_id`),
    KEY `idx_web_password_reset_token_hash` (`token_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

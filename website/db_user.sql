-- A limited MySQL account for the website, instead of root.
--
-- The site only needs to read the world and character databases, write its
-- own web_* tables, create/update game accounts, and clean up combat logs.
-- If PHP or the site is ever compromised, this is all an attacker gets.
--
-- Run as root, after changing the password:
--   docker exec -i ac-database mysql -uroot -p < db_user.sql
-- then set NEKO_DB_USER=neko_web and NEKO_DB_PASS=... in docker.env and
-- remove the NEKO_DB_USER/NEKO_DB_PASS lines from the neko-website service's
-- `environment:` block (they override docker.env), and restart the site.
--
-- '%' because the container connects from whatever address Docker gives it on
-- ac-network. Keep the database port off the public internet.
--
-- Database names are the AzerothCore defaults; change them if NEKO_DB_AUTH,
-- NEKO_DB_CHARS or NEKO_DB_WORLD say otherwise. Run news_schema.sql and the
-- web_auth_tokens.sql migration first: GRANT on a table needs it to exist.

CREATE USER IF NOT EXISTS 'neko_web'@'%' IDENTIFIED BY 'change-me';

-- auth: sign-in checks, registration, password reset, news.
GRANT SELECT, INSERT                 ON acore_auth.account                TO 'neko_web'@'%';
GRANT UPDATE (salt, verifier)        ON acore_auth.account                TO 'neko_web'@'%';
GRANT SELECT                         ON acore_auth.account_access         TO 'neko_web'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON acore_auth.web_news               TO 'neko_web'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON acore_auth.web_email_verification TO 'neko_web'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON acore_auth.web_password_reset     TO 'neko_web'@'%';

-- characters: read everything the pages show; the log pages also fill
-- nekolog_rank and staff can wipe a deleted character's logs.
GRANT SELECT                         ON acore_characters.*                   TO 'neko_web'@'%';
GRANT INSERT, DELETE                 ON acore_characters.nekolog_rank        TO 'neko_web'@'%';
GRANT UPDATE, DELETE                 ON acore_characters.nekolog_run         TO 'neko_web'@'%';
GRANT DELETE                         ON acore_characters.nekolog_event       TO 'neko_web'@'%';
GRANT DELETE                         ON acore_characters.nekolog_actor       TO 'neko_web'@'%';
GRANT DELETE                         ON acore_characters.nekolog_participant TO 'neko_web'@'%';
GRANT DELETE                         ON acore_characters.nekolog_encounter   TO 'neko_web'@'%';

-- world: drop search, item names (also joined from the leaderboard).
GRANT SELECT                         ON acore_world.*                        TO 'neko_web'@'%';

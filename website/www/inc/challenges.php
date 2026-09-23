<?php
declare(strict_types=1);

/*
 * Challenge-run repository + formatting helpers. The nekocore_challenge_*
 * tables (characters DB) are written only by the worldserver (nekocore module,
 * src/ChallengeRun.cpp); this file only reads them. Table layout:
 * data/sql/db-characters/base/nekocore_challenge.sql.
 *
 * Kept separate from inc/logs.php on purpose, the same way the tables are kept
 * separate from nekolog_*: a challenge run is a different thing from a boss
 * pull. Where the two do meet -- nekocore_challenge_run.log_run_id -- this file
 * hands out the id and log.php renders it with the ordinary log pages, so a
 * challenge's combat detail costs no duplicated code.
 */

const CH_IN_PROGRESS = 0;
const CH_CLEARED     = 1;
const CH_WIPED       = 2;
const CH_ABANDONED   = 3;

const CH_BRACKETS = [60 => 'Vanilla', 70 => 'TBC', 80 => 'WotLK'];

function ch_bracket_name(int $bracket): string { return CH_BRACKETS[$bracket] ?? (string)$bracket; }

function ch_result_label(int $r): string
{
    return [CH_IN_PROGRESS => 'In progress', CH_CLEARED => 'Cleared', CH_WIPED => 'Wiped', CH_ABANDONED => 'Abandoned'][$r] ?? '?';
}

/** Reuses the combat-log result badge styles -- cleared reads like a kill, wiped like a wipe. */
function ch_result_class(int $r): string
{
    return [CH_IN_PROGRESS => 'is-open', CH_CLEARED => 'is-kill', CH_WIPED => 'is-wipe', CH_ABANDONED => ''][$r] ?? '';
}

/** "+45% health, +30% damage", from the multipliers the run actually used. */
function ch_bonus(float $health, float $damage): string
{
    if ($health <= 1.0 && $damage <= 1.0) {
        return 'no bonus';
    }
    return sprintf('+%d%% health, +%d%% damage', (int)round(($health - 1) * 100), (int)round(($damage - 1) * 100));
}

/** Instances that have been challenged, for the filter row. */
function ch_maps(PDO $db): array
{
    return $db->query("SELECT map_id, map_name, COUNT(*) AS runs, MAX(CASE WHEN result = 1 THEN tier END) AS top_tier
                       FROM nekocore_challenge_run
                       GROUP BY map_id, map_name
                       ORDER BY runs DESC, map_name")->fetchAll(PDO::FETCH_ASSOC);
}

/** Challenge runs, newest first, with how many people were in each. */
function ch_recent_runs(PDO $db, ?int $mapId, ?int $bracket, int $limit, int $offset = 0): array
{
    $where = [];
    if ($mapId)   $where[] = 'r.map_id = :map';
    if ($bracket) $where[] = 'r.bracket = :bracket';
    $sql = "SELECT r.*, (SELECT COUNT(*) FROM nekocore_challenge_member m WHERE m.run_id = r.id) AS members
            FROM nekocore_challenge_run r"
        . ($where ? ' WHERE ' . implode(' AND ', $where) : '')
        . " ORDER BY r.started_at DESC LIMIT :lim OFFSET :off";

    $st = $db->prepare($sql);
    if ($mapId)   $st->bindValue('map', $mapId, PDO::PARAM_INT);
    if ($bracket) $st->bindValue('bracket', $bracket, PDO::PARAM_INT);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/** Who was in one run, with what the run did to their tier. */
function ch_run_members(PDO $db, int $runId): array
{
    $st = $db->prepare("SELECT * FROM nekocore_challenge_member WHERE run_id = :run ORDER BY name");
    $st->bindValue('run', $runId, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/**
 * The ladder: highest tier each character has actually CLEARED, so a bad night
 * can't cost anyone their place. `tier` (what they are currently set to) is
 * shown alongside it, which is the number their next run will use.
 */
function ch_ladder(PDO $db, ?int $mapId, ?int $bracket, int $limit): array
{
    $where = ['t.best_tier > 0'];
    if ($mapId)   $where[] = 't.map_id = :map';
    if ($bracket) $where[] = 't.bracket = :bracket';

    $sql = "SELECT t.*, c.name, c.class, c.race, r.map_name
            FROM nekocore_challenge_tier t
            JOIN characters c ON c.guid = t.char_guid
            LEFT JOIN (SELECT map_id, MAX(map_name) AS map_name FROM nekocore_challenge_run GROUP BY map_id) r
                 ON r.map_id = t.map_id
            WHERE " . implode(' AND ', $where) . "
            ORDER BY t.best_tier DESC, t.clears DESC, c.name
            LIMIT :lim";

    $st = $db->prepare($sql);
    if ($mapId)   $st->bindValue('map', $mapId, PDO::PARAM_INT);
    if ($bracket) $st->bindValue('bracket', $bracket, PDO::PARAM_INT);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/** The challenge run a combat log belongs to, or null if it was an ordinary one. */
function ch_run_for_log(PDO $db, int $logRunId): ?array
{
    if ($logRunId <= 0) {
        return null;
    }
    try {
        $st = $db->prepare("SELECT * FROM nekocore_challenge_run WHERE log_run_id = :run LIMIT 1");
        $st->bindValue('run', $logRunId, PDO::PARAM_INT);
        $st->execute();
    } catch (PDOException $e) {
        return null;   // database predates the challenge tables
    }
    $row = $st->fetch(PDO::FETCH_ASSOC);
    return $row ?: null;
}

/** Totals for the page header. */
function ch_totals(PDO $db): array
{
    $row = $db->query("SELECT COUNT(*) AS runs, SUM(result = 1) AS cleared, SUM(result = 2) AS wiped,
                              MAX(CASE WHEN result = 1 THEN tier END) AS top_tier
                       FROM nekocore_challenge_run")->fetch(PDO::FETCH_ASSOC);
    return $row ?: ['runs' => 0, 'cleared' => 0, 'wiped' => 0, 'top_tier' => null];
}

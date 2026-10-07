<?php
declare(strict_types=1);

/*
 * NekoLog repository + formatting helpers. The nekolog_* tables (characters
 * DB) are written only by the worldserver (nekocore module, src/NekoLog.cpp);
 * this file only reads them. Table layout: data/sql/db-characters/base/nekolog.sql.
 */

const NL_DAMAGE = 1;
const NL_HEAL = 2;
const NL_DEATH = 3;
const NL_CAST = 4;
const NL_AURA_APPLY = 5;
const NL_AURA_REMOVE = 6;

const NL_CLASS = [
    1 => ['Warrior', '#c79c6e'], 2 => ['Paladin', '#f58cba'], 3 => ['Hunter', '#abd473'],
    4 => ['Rogue', '#fff569'],   5 => ['Priest', '#ffffff'],  6 => ['Death Knight', '#c41f3b'],
    7 => ['Shaman', '#0070de'],  8 => ['Mage', '#69ccf0'],    9 => ['Warlock', '#9482c9'],
    11 => ['Druid', '#ff7d0a'],
];

const NL_SPEC = [
    1 => ['Arms', 'Fury', 'Protection'],      2 => ['Holy', 'Protection', 'Retribution'],
    3 => ['Beast Mastery', 'Marksmanship', 'Survival'], 4 => ['Assassination', 'Combat', 'Subtlety'],
    5 => ['Discipline', 'Holy', 'Shadow'],    6 => ['Blood', 'Frost', 'Unholy'],
    7 => ['Elemental', 'Enhancement', 'Restoration'], 8 => ['Arcane', 'Fire', 'Frost'],
    9 => ['Affliction', 'Demonology', 'Destruction'], 11 => ['Balance', 'Feral', 'Restoration'],
];

const NL_ERA = [
    0 => 'Vanilla', 1 => 'Vanilla', 2 => 'Vanilla', 3 => 'Vanilla', 4 => 'Vanilla', 5 => 'Vanilla',
    6 => 'Vanilla', 7 => 'Vanilla', 8 => 'TBC', 9 => 'TBC', 10 => 'TBC', 12 => 'TBC',
    13 => 'WotLK', 14 => 'WotLK', 15 => 'WotLK', 16 => 'WotLK', 17 => 'WotLK', 18 => 'WotLK',
];

/** A kill counts for rankings only if every participant is at most this many levels above the dungeon's highest boss (nl_dungeon_level). */
const NL_LEVEL_TOLERANCE = 3;

/** Leaderboard points for holding a rank position, per boss and metric (speed points go to every member of the kill). */
const NL_RANK_POINTS = [1 => 10, 2 => 6, 3 => 3];

const NL_SCHOOL = [1 => 'Physical', 2 => 'Holy', 4 => 'Fire', 8 => 'Nature', 16 => 'Frost', 32 => 'Shadow', 64 => 'Arcane'];

function nl_class_name(int $c): string { return NL_CLASS[$c][0] ?? ''; }
function nl_class_color(int $c): string { return NL_CLASS[$c][1] ?? 'var(--cream)'; }
function nl_spec_name(int $c, int $spec): string { return NL_SPEC[$c][$spec] ?? ''; }
function nl_era_name(int $era): string { return NL_ERA[$era] ?? 'WotLK'; }

function nl_school_name(int $mask): string
{
    $parts = [];
    foreach (NL_SCHOOL as $bit => $name) {
        if ($mask & $bit) $parts[] = $name;
    }
    return $parts ? implode('/', $parts) : 'Physical';
}

/** "4:12" from milliseconds. */
function nl_duration(int $ms): string
{
    $s = intdiv($ms, 1000);
    $h = intdiv($s, 3600); $m = intdiv($s % 3600, 60); $s %= 60;
    return $h ? sprintf('%d:%02d:%02d', $h, $m, $s) : sprintf('%d:%02d', $m, $s);
}

/** 1234567 -> "1.23M" for tables. */
function nl_num(int|float $n): string
{
    $n = (float)$n;
    if ($n >= 1e6) return number_format($n / 1e6, 2) . 'M';
    if ($n >= 1e4) return number_format($n / 1e3, 1) . 'K';
    return number_format($n);
}

function nl_result_label(int $r): string { return [0 => 'In progress', 1 => 'Kill', 2 => 'Wipe'][$r] ?? '?'; }
function nl_result_class(int $r): string { return [0 => 'is-open', 1 => 'is-kill', 2 => 'is-wipe'][$r] ?? ''; }

/** Difficulty label from Map spawn mode; the WotLK client uses 10/25 masks for every raid, so old raids report their real size via max_players. */
function nl_difficulty(array $run): string
{
    if ($run['is_raid']) {
        return (int)$run['max_players'] . '-player';
    }
    return ((int)$run['spawn_mode'] === 1 ? 'Heroic ' : '') . '5-player';
}

/**
 * SQL fragment excluding challenge runs from the ordinary log and ranking
 * views. Challenge runs (src/ChallengeRun.cpp) are recorded by NekoLog through
 * exactly the same tables -- that is deliberate, it is what lets log.php render
 * a challenge's combat detail with no duplicated code -- but they are a
 * different thing from a normal clear, at a different difficulty, and mixing
 * them into "recent runs" or into a boss's DPS ranking would compare two games.
 * They get their own page: challenges.php.
 *
 * Returns "1" (a no-op) if the challenge tables aren't present, so this file
 * still works against a database that predates them.
 */
function nl_not_challenge(PDO $db, string $runIdColumn): string
{
    static $present = null;
    if ($present === null) {
        try {
            $db->query("SELECT 1 FROM nekocore_challenge_run LIMIT 0");
            $present = true;
        } catch (PDOException $e) {
            $present = false;
        }
    }
    return $present
        ? "NOT EXISTS (SELECT 1 FROM nekocore_challenge_run cr WHERE cr.log_run_id = $runIdColumn)"
        : '1';
}

/** Recent runs, newest first. */
function nl_recent_runs(PDO $db, ?int $mapId, int $limit, int $offset = 0): array
{
    $notChallenge = nl_not_challenge($db, 'nekolog_run.id');
    $sql = "SELECT * FROM nekolog_run WHERE $notChallenge" . ($mapId ? " AND map_id = :map" : "")
        . " ORDER BY started_at DESC LIMIT :lim OFFSET :off";
    $st = $db->prepare($sql);
    if ($mapId) $st->bindValue('map', $mapId, PDO::PARAM_INT);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

function nl_maps(PDO $db): array
{
    $notChallenge = nl_not_challenge($db, 'nekolog_run.id');
    return $db->query("SELECT map_id, map_name, COUNT(*) AS runs FROM nekolog_run WHERE $notChallenge
                       GROUP BY map_id, map_name ORDER BY runs DESC")->fetchAll(PDO::FETCH_ASSOC);
}

/** Distinct bosses with pull counts, for the boss filter. */
function nl_bosses(PDO $db): array
{
    $notChallenge = nl_not_challenge($db, 'r.id');
    return $db->query("SELECT e.boss_entry, e.boss_name, r.map_name, COUNT(*) AS pulls, SUM(e.result = 1) AS kills
                       FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                       WHERE $notChallenge
                       GROUP BY e.boss_entry, e.boss_name, r.map_name ORDER BY r.map_name, e.boss_name")->fetchAll(PDO::FETCH_ASSOC);
}

/** Every pull of one boss, newest first, with its run. */
function nl_boss_pulls(PDO $db, int $bossEntry, int $limit, int $offset = 0): array
{
    $st = $db->prepare("SELECT e.*, r.map_name, r.started_at, r.is_raid, r.spawn_mode, r.max_players
                        FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                        WHERE e.boss_entry = :boss AND " . nl_not_challenge($db, 'r.id') . "
                        ORDER BY r.started_at DESC, e.start_ms DESC LIMIT :lim OFFSET :off");
    $st->bindValue('boss', $bossEntry, PDO::PARAM_INT);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/* ---------- rankings ---------- */

/**
 * Summarize any finished kills that nekolog_rank doesn't have yet (one row
 * per player, pets folded into their owner). Cheap when nothing is new.
 */
function nl_refresh_ranks(PDO $db, int $batch = 50): int
{
    $todo = $db->query("SELECT e.*, r.map_id, r.spawn_mode, r.started_at FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                        LEFT JOIN nekolog_rank k ON k.enc_id = e.id
                        WHERE e.result = 1 AND e.end_ms > e.start_ms AND k.enc_id IS NULL
                          AND " . nl_not_challenge($db, 'r.id') . "
                        ORDER BY e.id LIMIT $batch")->fetchAll(PDO::FETCH_ASSOC);
    if (!$todo) return 0;

    $agg = $db->prepare("SELECT COALESCE(NULLIF(a.owner, 0), a.guid) AS who, ev.kind, SUM(ev.amount) AS total
                         FROM nekolog_event ev JOIN nekolog_actor a ON a.run_id = ev.run_id AND a.guid = ev.src
                         WHERE ev.enc_id = :enc AND ev.kind IN (1, 2) AND a.kind IN (1, 2) GROUP BY who, ev.kind");
    $ins = $db->prepare("INSERT IGNORE INTO nekolog_rank (enc_id, guid, run_id, boss_entry, map_id, char_guid, name, class, spec, level, players, era, duration_ms, damage, healing, dps, hps, killed_at, eligible, boss_level, max_level)
                         VALUES (:enc, :guid, :run, :boss, :map, :cg, :name, :class, :spec, :level, :players, :era, :dur, :dmg, :heal, :dps, :hps, :at, :el, :bl, :ml)");
    $n = 0;
    foreach ($todo as $e) {
        $actors = nl_actors($db, (int)$e['run_id']);
        $participants = nl_participants($db, (int)$e['id']);
        $agg->execute(['enc' => $e['id']]);
        $totals = [];
        foreach ($agg->fetchAll(PDO::FETCH_ASSOC) as $r) {
            $totals[$r['who']][(int)$r['kind']] = (int)$r['total'];
        }
        // Everyone who was there gets a row, even at zero, so "was in the kill" is queryable.
        $who = array_unique(array_merge(array_keys($participants), array_keys($totals)));
        $dur = max(1, (int)$e['end_ms'] - (int)$e['start_ms']);
        // On-level gate: one over-level member (a carry) disqualifies the whole kill.
        // Measured against the dungeon, not this boss alone: Shadowfang Keep opens
        // with a level-20 boss in a level 22-30 dungeon, so a level-26 player was
        // "over-level" for the first two bosses of an on-level run.
        $ownLevel = (int)($actors[$e['boss_guid']]['level'] ?? 0);
        $bossLevel = $ownLevel > 0 ? max($ownLevel, nl_dungeon_level($db, (int)$e['map_id'], (int)$e['spawn_mode'])) : 0;
        $maxLevel = 0;
        foreach ($who as $g) if (($actors[$g]['kind'] ?? 0) == 1) $maxLevel = max($maxLevel, (int)$actors[$g]['level']);
        $eligible = ($bossLevel > 0 && $maxLevel <= $bossLevel + NL_LEVEL_TOLERANCE) ? 1 : 0;
        $db->beginTransaction();
        $rows = 0;
        foreach ($who as $g) {
            $a = $actors[$g] ?? null;
            if (!$a || (int)$a['kind'] !== 1) continue;
            $dmg = $totals[$g][NL_DAMAGE] ?? 0;
            $heal = $totals[$g][NL_HEAL] ?? 0;
            $ins->execute([
                'enc' => $e['id'], 'guid' => $g, 'run' => $e['run_id'], 'boss' => $e['boss_entry'], 'map' => $e['map_id'],
                'cg' => $a['char_guid'], 'name' => $a['name'], 'class' => $a['class'], 'spec' => $a['spec'], 'level' => $a['level'],
                'players' => $e['players'], 'era' => $participants[$g] ?? $e['max_era'], 'dur' => $dur,
                'dmg' => $dmg, 'heal' => $heal, 'dps' => $dmg / ($dur / 1000), 'hps' => $heal / ($dur / 1000),
                'at' => (int)$e['started_at'] + intdiv((int)$e['end_ms'], 1000),
                'el' => $eligible, 'bl' => $bossLevel, 'ml' => $maxLevel,
            ]);
            $rows++;
        }
        $n += $rows;
        // A kill with no player rows (e.g. all GMs) still needs a marker so it isn't re-scanned forever.
        if (!$rows) {
            $ins->execute(['enc' => $e['id'], 'guid' => 0, 'run' => $e['run_id'], 'boss' => $e['boss_entry'], 'map' => $e['map_id'],
                'cg' => 0, 'name' => '', 'class' => 0, 'spec' => 0, 'level' => 0, 'players' => $e['players'], 'era' => $e['max_era'],
                'dur' => $dur, 'dmg' => 0, 'heal' => 0, 'dps' => 0, 'hps' => 0, 'at' => (int)$e['started_at'], 'el' => 0, 'bl' => $bossLevel, 'ml' => $maxLevel]);
        }
        $db->commit();
    }
    return $n;
}

/**
 * Ranking rows for one boss. $metric: 'speed' (one row per kill, fastest
 * first), 'dps' or 'hps' (one row per player). $filters: class, players, era
 * (era name: Vanilla/TBC/WotLK) -- each optional.
 */
function nl_rankings(PDO $db, int $bossEntry, string $metric, array $filters, int $limit = 50): array
{
    $where = ['k.boss_entry = :boss', 'k.guid <> 0', 'k.eligible = 1'];
    $args = ['boss' => $bossEntry];
    if (!empty($filters['class'])) { $where[] = 'k.class = :class'; $args['class'] = (int)$filters['class']; }
    if (!empty($filters['players'])) { $where[] = 'k.players = :players'; $args['players'] = (int)$filters['players']; }
    if (!empty($filters['era'])) {
        $ids = array_keys(array_filter(NL_ERA, fn($n) => $n === $filters['era']));
        if ($ids) $where[] = 'k.era IN (' . implode(',', $ids) . ')';
    }
    $w = implode(' AND ', $where);
    if ($metric === 'speed') {
        $sql = "SELECT k.enc_id, k.run_id, k.players, MAX(k.era) AS era, k.duration_ms, k.killed_at,
                       SUM(k.damage) AS damage, COUNT(*) AS members, r.map_name, r.is_raid, r.spawn_mode, r.max_players
                FROM nekolog_rank k JOIN nekolog_run r ON r.id = k.run_id WHERE $w
                GROUP BY k.enc_id, k.run_id, k.players, k.duration_ms, k.killed_at, r.map_name, r.is_raid, r.spawn_mode, r.max_players
                ORDER BY k.duration_ms ASC, k.killed_at ASC LIMIT $limit";
    } else {
        $col = $metric === 'hps' ? 'hps' : 'dps';
        $sql = "SELECT k.*, r.map_name, r.is_raid, r.spawn_mode, r.max_players FROM nekolog_rank k JOIN nekolog_run r ON r.id = k.run_id
                WHERE $w AND k.$col > 0 ORDER BY k.$col DESC, k.duration_ms ASC LIMIT $limit";
    }
    $st = $db->prepare($sql);
    $st->execute($args);
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/** Instances that have at least one kill, for the rankings landing page. */
function nl_rank_maps(PDO $db): array
{
    return $db->query("SELECT r.map_id, r.map_name, r.is_raid, COUNT(DISTINCT e.boss_entry) AS bosses, COUNT(*) AS kills,
                              MAX(r.started_at + FLOOR(e.end_ms / 1000)) AS last_kill
                       FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                       WHERE e.result = 1 AND " . nl_not_challenge($db, 'r.id') . "
                       GROUP BY r.map_id, r.map_name, r.is_raid ORDER BY r.is_raid, r.map_name")->fetchAll(PDO::FETCH_ASSOC);
}

/** Bosses of one instance with a one-line best: fastest kill and top DPS. */
function nl_rank_bosses(PDO $db, int $mapId): array
{
    $st = $db->prepare("SELECT e.boss_entry, e.boss_name, COUNT(*) AS pulls, SUM(e.result = 1) AS kills
                        FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                        WHERE r.map_id = :map AND " . nl_not_challenge($db, 'r.id') . "
                        GROUP BY e.boss_entry, e.boss_name ORDER BY MIN(e.id)");
    $st->execute(['map' => $mapId]);
    $bosses = $st->fetchAll(PDO::FETCH_ASSOC);
    $fast = $db->prepare("SELECT enc_id, run_id, duration_ms, players FROM nekolog_rank WHERE boss_entry = :b AND guid <> 0 AND eligible = 1 ORDER BY duration_ms ASC LIMIT 1");
    $top = $db->prepare("SELECT name, class, spec, dps FROM nekolog_rank WHERE boss_entry = :b AND guid <> 0 AND eligible = 1 ORDER BY dps DESC LIMIT 1");
    foreach ($bosses as &$b) {
        $fast->execute(['b' => $b['boss_entry']]); $b['fastest'] = $fast->fetch(PDO::FETCH_ASSOC) ?: null;
        $top->execute(['b' => $b['boss_entry']]);  $b['top'] = $top->fetch(PDO::FETCH_ASSOC) ?: null;
    }
    return $bosses;
}

/** Eligibility of one encounter's kill for the log pages: null if not a summarized kill. */
/**
 * Highest level any boss of this dungeon and difficulty has been logged at,
 * outside challenge runs (they raise creature levels). Learned from the logs,
 * since the world DB has no usable per-dungeon level table.
 */
function nl_dungeon_level(PDO $db, int $mapId, int $spawnMode): int
{
    static $cache = [];
    $key = "$mapId:$spawnMode";
    if (!isset($cache[$key])) {
        $st = $db->prepare("SELECT MAX(a.level) FROM nekolog_encounter e JOIN nekolog_run r ON r.id = e.run_id
                            JOIN nekolog_actor a ON a.run_id = e.run_id AND a.guid = e.boss_guid
                            WHERE r.map_id = :m AND r.spawn_mode = :s AND " . nl_not_challenge($db, 'r.id'));
        $st->execute(['m' => $mapId, 's' => $spawnMode]);
        $cache[$key] = (int)$st->fetchColumn();
    }
    return $cache[$key];
}

function nl_kill_eligibility(PDO $db, int $encId): ?array
{
    $st = $db->prepare("SELECT MAX(eligible) AS eligible, MAX(boss_level) AS boss_level, MAX(max_level) AS max_level FROM nekolog_rank WHERE enc_id = :e");
    $st->execute(['e' => $encId]);
    $r = $st->fetch(PDO::FETCH_ASSOC);
    return ($r && $r['eligible'] !== null) ? $r : null;
}

/**
 * Leaderboard points from CURRENT ranking positions, keyed by characters.guid.
 * Nothing is banked: lose the spot, lose the points. Per boss: top NL_RANK_POINTS
 * positions in fastest kill (every member of the kill), DPS and HPS.
 * Returns [char_guid => ['points' => n, 'spots' => [[boss_name, metric, position, points], ...]]].
 */
function nl_rank_points(PDO $db): array
{
    static $cache = null;
    if ($cache !== null) return $cache;
    $out = [];
    // Only a player's BEST position per boss and metric scores -- holding #1,
    // #2 and #3 on one boss through repeated kills is one spot, not three.
    $seen = [];
    $award = function ($cg, string $boss, string $metric, int $pos) use (&$out, &$seen) {
        $pts = NL_RANK_POINTS[$pos] ?? 0;
        if (!$pts || !$cg || isset($seen[$cg][$boss][$metric])) return;
        $seen[$cg][$boss][$metric] = true;
        $out[$cg] ??= ['points' => 0, 'spots' => []];
        $out[$cg]['points'] += $pts;
        $out[$cg]['spots'][] = [$boss, $metric, $pos, $pts];
    };
    $top = count(NL_RANK_POINTS);
    $bossNames = $db->query("SELECT boss_entry, MAX(boss_name) FROM nekolog_encounter GROUP BY boss_entry")->fetchAll(PDO::FETCH_KEY_PAIR);

    // Fastest kills: distinct encounters per boss, best first; every member scores.
    $kills = $db->query("SELECT boss_entry, enc_id, duration_ms FROM nekolog_rank WHERE guid <> 0 AND eligible = 1
                         GROUP BY boss_entry, enc_id, duration_ms ORDER BY boss_entry, duration_ms ASC, enc_id ASC")->fetchAll(PDO::FETCH_ASSOC);
    $members = $db->prepare("SELECT char_guid FROM nekolog_rank WHERE enc_id = :e AND guid <> 0");
    $pos = [];
    foreach ($kills as $k) {
        $b = $k['boss_entry'];
        $pos[$b] = ($pos[$b] ?? 0) + 1;
        if ($pos[$b] > $top) continue;
        $members->execute(['e' => $k['enc_id']]);
        foreach ($members->fetchAll(PDO::FETCH_COLUMN) as $cg) $award($cg, $bossNames[$b] ?? "Boss $b", 'speed', $pos[$b]);
    }
    // DPS / HPS: per boss, top rows; one position per row (a player can hold several with different kills).
    foreach (['dps', 'hps'] as $m) {
        $rows = $db->query("SELECT boss_entry, char_guid FROM nekolog_rank WHERE guid <> 0 AND eligible = 1 AND $m > 0 ORDER BY boss_entry, $m DESC, duration_ms ASC")->fetchAll(PDO::FETCH_ASSOC);
        $pos = [];
        foreach ($rows as $r) {
            $b = $r['boss_entry'];
            $pos[$b] = ($pos[$b] ?? 0) + 1;
            if ($pos[$b] > $top) continue;
            $award($r['char_guid'], $bossNames[$b] ?? "Boss $b", $m, $pos[$b]);
        }
    }
    return $cache = $out;
}

/* ---------- admin: deleted characters ---------- */

/**
 * Player actors whose character no longer exists: char_guid was zeroed by the
 * server on delete, or points at a guid that is gone (deleted before the
 * unlink hook existed). One row per distinct name, with what they left behind.
 */
function nl_deleted_players(PDO $db): array
{
    return $db->query("SELECT a.name, MAX(a.class) AS class, MAX(a.level) AS level, COUNT(DISTINCT a.run_id) AS runs,
                              (SELECT COUNT(*) FROM nekolog_rank k WHERE k.name = a.name AND k.guid <> 0
                                   AND (k.char_guid = 0 OR k.char_guid NOT IN (SELECT guid FROM characters))) AS kills,
                              MIN(r.started_at) AS first_seen, MAX(r.started_at) AS last_seen
                       FROM nekolog_actor a JOIN nekolog_run r ON r.id = a.run_id
                       WHERE a.kind = 1 AND (a.char_guid = 0 OR a.char_guid NOT IN (SELECT guid FROM characters))
                         AND NOT EXISTS (SELECT 1 FROM characters c WHERE c.name = a.name)
                       GROUP BY a.name ORDER BY last_seen DESC")->fetchAll(PDO::FETCH_ASSOC);
}

/**
 * Wipe everything a deleted character left in the logs: their events (as
 * source or target), their pets' events, their ranking rows and actor rows.
 * Encounters/runs left with no players at all are removed entirely. Other
 * people's kills stay, minus this character's contribution.
 * Returns counts for the flash message.
 */
function nl_wipe_deleted_player(PDO $db, string $name): array
{
    // Only characters that really are gone -- never a live one by name.
    $st = $db->prepare("SELECT COUNT(*) FROM characters WHERE name = :n");
    $st->execute(['n' => $name]);
    if ((int)$st->fetchColumn() > 0) {
        throw new RuntimeException("$name still exists; delete the character first.");
    }
    $st = $db->prepare("SELECT run_id, guid FROM nekolog_actor WHERE kind = 1 AND name = :n");
    $st->execute(['n' => $name]);
    $actors = $st->fetchAll(PDO::FETCH_ASSOC);
    $out = ['events' => 0, 'kills' => 0, 'encounters' => 0, 'runs' => 0];
    if (!$actors) return $out;

    $db->beginTransaction();
    try {
        foreach ($actors as $a) {
            $run = (int)$a['run_id']; $g = $a['guid'];
            // Their pets in this run share the wipe.
            $st = $db->prepare("SELECT guid FROM nekolog_actor WHERE run_id = :r AND owner = :g");
            $st->execute(['r' => $run, 'g' => $g]);
            $guids = array_merge([$g], $st->fetchAll(PDO::FETCH_COLUMN));
            $in = implode(',', array_fill(0, count($guids), '?'));

            $st = $db->prepare("DELETE FROM nekolog_event WHERE run_id = ? AND (src IN ($in) OR dst IN ($in))");
            $st->execute(array_merge([$run], $guids, $guids));
            $out['events'] += $st->rowCount();

            $st = $db->prepare("DELETE k FROM nekolog_rank k JOIN nekolog_encounter e ON e.id = k.enc_id WHERE e.run_id = ? AND k.guid = ?");
            $st->execute([$run, $g]);
            $out['kills'] += $st->rowCount();

            $st = $db->prepare("DELETE p FROM nekolog_participant p JOIN nekolog_encounter e ON e.id = p.enc_id WHERE e.run_id = ? AND p.guid = ?");
            $st->execute([$run, $g]);

            $st = $db->prepare("DELETE FROM nekolog_actor WHERE run_id = ? AND guid IN ($in)");
            $st->execute(array_merge([$run], $guids));

            // Encounters in this run with no player left: gone, with everything under them.
            $st = $db->prepare("SELECT e.id FROM nekolog_encounter e WHERE e.run_id = ?
                                AND NOT EXISTS (SELECT 1 FROM nekolog_participant p WHERE p.enc_id = e.id)
                                AND NOT EXISTS (SELECT 1 FROM nekolog_event ev JOIN nekolog_actor a ON a.run_id = ev.run_id AND a.guid = ev.src
                                                WHERE ev.enc_id = e.id AND a.kind IN (1, 2))");
            $st->execute([$run]);
            foreach ($st->fetchAll(PDO::FETCH_COLUMN) as $encId) {
                foreach (['nekolog_event' => 'enc_id', 'nekolog_participant' => 'enc_id', 'nekolog_rank' => 'enc_id', 'nekolog_encounter' => 'id'] as $tbl => $col) {
                    $db->prepare("DELETE FROM $tbl WHERE $col = ?")->execute([$encId]);
                }
                $out['encounters']++;
            }
            // Creatures nobody in the run fought any more.
            $db->prepare("DELETE a FROM nekolog_actor a WHERE a.run_id = ? AND a.kind = 3
                          AND NOT EXISTS (SELECT 1 FROM nekolog_event ev WHERE ev.run_id = a.run_id AND (ev.src = a.guid OR ev.dst = a.guid))")->execute([$run]);
            // Run with no encounters left: gone too.
            $st = $db->prepare("SELECT COUNT(*) FROM nekolog_encounter WHERE run_id = ?");
            $st->execute([$run]);
            if ((int)$st->fetchColumn() === 0) {
                $db->prepare("DELETE FROM nekolog_actor WHERE run_id = ?")->execute([$run]);
                $db->prepare("DELETE FROM nekolog_event WHERE run_id = ?")->execute([$run]);
                $db->prepare("DELETE FROM nekolog_run WHERE id = ?")->execute([$run]);
                $out['runs']++;
            } else {
                $st = $db->prepare("SELECT COUNT(*) FROM nekolog_encounter WHERE run_id = ? AND result = 1");
                $st->execute([$run]);
                $kills = (int)$st->fetchColumn();
                $st = $db->prepare("SELECT COUNT(*) FROM nekolog_encounter WHERE run_id = ? AND result = 2");
                $st->execute([$run]);
                $db->prepare("UPDATE nekolog_run SET kills = ?, wipes = ? WHERE id = ?")->execute([$kills, (int)$st->fetchColumn(), $run]);
            }
        }
        $db->commit();
    } catch (Throwable $t) {
        $db->rollBack();
        throw $t;
    }
    return $out;
}

/** Names of the players in a set of kills, for the speed table. */
function nl_kill_members(PDO $db, array $encIds): array
{
    $encIds = array_values(array_unique(array_map('intval', $encIds)));
    if (!$encIds) return [];
    $in = implode(',', array_fill(0, count($encIds), '?'));
    $st = $db->prepare("SELECT enc_id, name, class, spec FROM nekolog_rank WHERE guid <> 0 AND eligible = 1 AND enc_id IN ($in) ORDER BY damage DESC");
    $st->execute($encIds);
    $out = [];
    foreach ($st->fetchAll(PDO::FETCH_ASSOC) as $r) $out[$r['enc_id']][] = $r;
    return $out;
}

function nl_run(PDO $db, int $id): ?array
{
    $st = $db->prepare("SELECT * FROM nekolog_run WHERE id = :id");
    $st->execute(['id' => $id]);
    return $st->fetch(PDO::FETCH_ASSOC) ?: null;
}

function nl_encounters(PDO $db, int $runId): array
{
    $st = $db->prepare("SELECT * FROM nekolog_encounter WHERE run_id = :id ORDER BY start_ms");
    $st->execute(['id' => $runId]);
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

function nl_encounter(PDO $db, int $id): ?array
{
    $st = $db->prepare("SELECT * FROM nekolog_encounter WHERE id = :id");
    $st->execute(['id' => $id]);
    return $st->fetch(PDO::FETCH_ASSOC) ?: null;
}

/** Actors of a run keyed by guid; pets resolved to their owner via ['owner']. */
function nl_actors(PDO $db, int $runId): array
{
    $st = $db->prepare("SELECT * FROM nekolog_actor WHERE run_id = :id");
    $st->execute(['id' => $runId]);
    $out = [];
    foreach ($st->fetchAll(PDO::FETCH_ASSOC) as $a) {
        $out[$a['guid']] = $a;
    }
    return $out;
}

/** Players in the raid at the start of the encounter (guid => era). */
function nl_participants(PDO $db, int $encId): array
{
    $st = $db->prepare("SELECT guid, era FROM nekolog_participant WHERE enc_id = :id");
    $st->execute(['id' => $encId]);
    return $st->fetchAll(PDO::FETCH_KEY_PAIR);
}

/**
 * Per-actor, per-spell totals for one event kind within an encounter.
 * Returns [src_guid => ['total' => n, 'extra' => n, 'hits' => n, 'spells' => [spell_id => [...]]]].
 */
function nl_breakdown(PDO $db, int $encId, int $kind, string $by = 'src'): array
{
    $col = $by === 'dst' ? 'dst' : 'src';
    $st = $db->prepare("SELECT $col AS who, spell, SUM(amount) AS total, SUM(extra) AS extra, COUNT(*) AS hits, MAX(flags & 1) AS periodic
                        FROM nekolog_event WHERE enc_id = :id AND kind = :kind GROUP BY $col, spell");
    $st->execute(['id' => $encId, 'kind' => $kind]);
    $out = [];
    foreach ($st->fetchAll(PDO::FETCH_ASSOC) as $r) {
        $w = $r['who'];
        $out[$w] ??= ['total' => 0, 'extra' => 0, 'hits' => 0, 'spells' => []];
        $out[$w]['total'] += (int)$r['total'];
        $out[$w]['extra'] += (int)$r['extra'];
        $out[$w]['hits'] += (int)$r['hits'];
        $out[$w]['spells'][(int)$r['spell']] = ['total' => (int)$r['total'], 'extra' => (int)$r['extra'], 'hits' => (int)$r['hits'], 'periodic' => (int)$r['periodic']];
    }
    return $out;
}

/**
 * Fold pets into their owners and drop non-player rows, so the table is one
 * row per player. Spell keys for pet abilities are prefixed with the pet's
 * name so they stay distinguishable in the expanded breakdown.
 */
function nl_fold_to_players(array $breakdown, array $actors): array
{
    $out = [];
    foreach ($breakdown as $guid => $row) {
        $actor = $actors[$guid] ?? null;
        if (!$actor) continue;
        $ownerGuid = $guid;
        $prefix = '';
        if ((int)$actor['kind'] === 2 && !empty($actor['owner'])) {
            $ownerGuid = $actor['owner'];
            $prefix = $actor['name'] . ': ';
        } elseif ((int)$actor['kind'] !== 1) {
            continue;
        }
        $out[$ownerGuid] ??= ['total' => 0, 'extra' => 0, 'hits' => 0, 'spells' => []];
        $out[$ownerGuid]['total'] += $row['total'];
        $out[$ownerGuid]['extra'] += $row['extra'];
        $out[$ownerGuid]['hits'] += $row['hits'];
        foreach ($row['spells'] as $spell => $s) {
            $key = $prefix . $spell;
            $out[$ownerGuid]['spells'][$key] = $s + ['spell' => $spell, 'prefix' => $prefix];
        }
    }
    uasort($out, fn($a, $b) => $b['total'] <=> $a['total']);
    return $out;
}

/** Same, but only creature (enemy) rows -- for "damage taken from" style views. */
function nl_only_creatures(array $breakdown, array $actors): array
{
    $out = array_filter($breakdown, fn($row, $guid) => (int)($actors[$guid]['kind'] ?? 0) === 3, ARRAY_FILTER_USE_BOTH);
    uasort($out, fn($a, $b) => $b['total'] <=> $a['total']);
    return $out;
}

function nl_spell_names(PDO $db, array $ids): array
{
    $ids = array_values(array_unique(array_map('intval', $ids)));
    if (!$ids) return [];
    $in = implode(',', array_fill(0, count($ids), '?'));
    $st = $db->prepare("SELECT id, name FROM nekolog_spell WHERE id IN ($in)");
    $st->execute($ids);
    return $st->fetchAll(PDO::FETCH_KEY_PAIR);
}

function nl_spell_name(array $names, int $id, int $kind = NL_DAMAGE): string
{
    if ($id === 0) return $kind === NL_HEAL ? 'Heal' : 'Melee';
    return $names[$id] ?? ('Spell #' . $id);
}

function nl_deaths(PDO $db, int $encId): array
{
    $st = $db->prepare("SELECT t_ms, src, dst FROM nekolog_event WHERE enc_id = :id AND kind = :kind ORDER BY t_ms");
    $st->execute(['id' => $encId, 'kind' => NL_DEATH]);
    return $st->fetchAll(PDO::FETCH_ASSOC);
}

/** Actor display: name coloured by class, with spec on hover. */
function nl_actor_html(array $actors, $guid): string
{
    $a = $actors[$guid] ?? null;
    if (!$a) return '<span class="nl-unknown">Unknown</span>';
    $cls = (int)$a['class'];
    if ((int)$a['kind'] === 1) {
        $title = trim(nl_spec_name($cls, (int)$a['spec']) . ' ' . nl_class_name($cls));
        return '<span class="nl-name" style="color:' . nl_class_color($cls) . '" title="' . e($title) . '">' . e($a['name']) . '</span>';
    }
    return '<span class="nl-name nl-name--npc">' . e($a['name']) . '</span>';
}

/** Streams an encounter's raw events as CSV and exits. */
function nl_export_csv(PDO $db, array $run, array $enc, array $actors): void
{
    $names = [];
    $st = $db->prepare("SELECT t_ms, kind, src, dst, spell, amount, extra, school, flags FROM nekolog_event WHERE enc_id = :id ORDER BY t_ms, id");
    $st->execute(['id' => $enc['id']]);
    $rows = $st->fetchAll(PDO::FETCH_ASSOC);
    $names = nl_spell_names($db, array_column($rows, 'spell'));

    $kinds = [1 => 'DAMAGE', 2 => 'HEAL', 3 => 'DEATH', 4 => 'CAST', 5 => 'AURA_APPLY', 6 => 'AURA_REMOVE'];
    $file = preg_replace('/[^A-Za-z0-9]+/', '_', $run['map_name'] . '_' . $enc['boss_name']) . '_' . $enc['id'] . '.csv';
    header('Content-Type: text/csv; charset=UTF-8');
    header('Content-Disposition: attachment; filename="' . $file . '"');
    $out = fopen('php://output', 'w');
    fputcsv($out, ['# NekoCore server log', 'run ' . $run['id'], 'encounter ' . $enc['id'], $enc['boss_name'], nl_result_label((int)$enc['result']), date('c', (int)$run['started_at'])]);
    fputcsv($out, ['time_ms', 'event', 'source', 'target', 'spell_id', 'spell', 'amount', 'extra', 'school', 'periodic']);
    foreach ($rows as $r) {
        fputcsv($out, [
            $r['t_ms'] - $enc['start_ms'], $kinds[(int)$r['kind']] ?? $r['kind'],
            $actors[$r['src']]['name'] ?? '', $actors[$r['dst']]['name'] ?? '',
            $r['spell'], nl_spell_name($names, (int)$r['spell'], (int)$r['kind']),
            $r['amount'], $r['extra'], nl_school_name((int)$r['school']), (int)$r['flags'] & 1,
        ]);
    }
    fclose($out);
    exit;
}

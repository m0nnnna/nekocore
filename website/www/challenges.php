<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/logs.php';
require __DIR__ . '/inc/challenges.php';

$db = neko_db('chars');
$error = $db ? null : 'The character database is not reachable right now.';

$mapId   = (int)($_GET['map'] ?? 0) ?: null;
$bracket = (int)($_GET['bracket'] ?? 0) ?: null;
if ($bracket !== null && !isset(CH_BRACKETS[$bracket])) {
    $bracket = null;
}
$page    = max(1, (int)($_GET['page'] ?? 1));
$perPage = 40;

$runs = []; $maps = []; $ladder = []; $totals = ['runs' => 0, 'cleared' => 0, 'wiped' => 0, 'top_tier' => null];

if (!$error) {
    try {
        $maps   = ch_maps($db);
        $totals = ch_totals($db);
        $ladder = ch_ladder($db, $mapId, $bracket, 20);
        $runs   = ch_recent_runs($db, $mapId, $bracket, $perPage + 1, ($page - 1) * $perPage);
    } catch (PDOException $e) {
        neko_log_error('challenges', $e);
        $error = 'The database had a problem loading this page. Try again in a moment.';
    }
}

$hasMore = count($runs) > $perPage;
$runs = array_slice($runs, 0, $perPage);

$mapName = '';
foreach ($maps as $m) {
    if ((int)$m['map_id'] === $mapId) $mapName = $m['map_name'];
}
$pageQuery = fn(int $p) => http_build_query(array_filter(['map' => $mapId, 'bracket' => $bracket, 'page' => $p > 1 ? $p : null]));
$filterQuery = fn(?int $map, ?int $br) => http_build_query(array_filter(['map' => $map, 'bracket' => $br]));

neko_page_start(['title' => 'Challenges', 'active' => 'challenges',
    'description' => 'Challenge runs on NekoCore: old dungeons brought back up to your level, harder every time you clear one.']);
?>

<div class="page-head">
    <h1>Challenge runs</h1>
    <p>A challenge run takes a dungeon you have outgrown and brings it back up to your era's cap &mdash; level 60, 70 or 80, whichever yours is. Every creature in there fights you as an equal. Clear it and the next run comes back harder: more health, harder hits. Wipe and it eases back one step.</p>
    <p>Arm one at the <strong>Challenge Keeper</strong>, beside Dungeon Dan in Stormwind and Orgrimmar. You have to be at your era's cap, and only your group leader sets the tier. Every run here was recorded by the server as it happened, the same way the <a href="logs.php">combat logs</a> are &mdash; nothing is uploaded and nothing can be edited.</p>
</div>

<?php if ($error): ?>
    <div class="empty"><?= neko_icon('paw') ?><?= e($error) ?></div>
<?php else: ?>

<?php if ((int)$totals['runs'] > 0): ?>
<p class="notice-line">
    <?= (int)$totals['runs'] ?> run<?= (int)$totals['runs'] === 1 ? '' : 's' ?>,
    <?= (int)$totals['cleared'] ?> cleared, <?= (int)$totals['wiped'] ?> wiped<?php
    if ($totals['top_tier'] !== null): ?> &middot; highest tier cleared: <strong>tier <?= (int)$totals['top_tier'] ?></strong><?php endif; ?>
</p>
<?php endif; ?>

<?php if ($maps): ?>
<nav class="nl-filter" aria-label="Filter challenge runs">
    <a href="challenges.php"<?= ($mapId || $bracket) ? '' : ' aria-current="page"' ?>>All</a>
    <?php foreach ($maps as $m): ?>
        <a href="challenges.php?<?= e($filterQuery((int)$m['map_id'], $bracket)) ?>"<?= (int)$m['map_id'] === $mapId ? ' aria-current="page"' : '' ?>><?= e($m['map_name'] ?: 'Map ' . $m['map_id']) ?> <span><?= (int)$m['runs'] ?></span></a>
    <?php endforeach; ?>
</nav>
<nav class="nl-filter nl-filter--tight" aria-label="Filter by bracket">
    <a href="challenges.php?<?= e($filterQuery($mapId, null)) ?>"<?= $bracket ? '' : ' aria-current="page"' ?>>Every bracket</a>
    <?php foreach (CH_BRACKETS as $lvl => $name): ?>
        <a href="challenges.php?<?= e($filterQuery($mapId, (int)$lvl)) ?>"<?= (int)$lvl === $bracket ? ' aria-current="page"' : '' ?>><?= e($name) ?> <span><?= (int)$lvl ?></span></a>
    <?php endforeach; ?>
</nav>
<?php endif; ?>

<?php if ($ladder): ?>
<div class="sec-head">
    <h2>Ladder<?= $mapName ? ' &middot; ' . e($mapName) : '' ?></h2>
    <span class="notice-line">Highest tier actually cleared. A wipe never takes this away.</span>
</div>
<div class="tbl-wrap">
    <table class="tbl">
        <thead><tr><th class="num">#</th><th>Character</th><th>Instance</th><th>Bracket</th><th class="num">Best tier</th><th class="num">Next run</th><th class="num">Clears</th><th class="num">Fails</th></tr></thead>
        <tbody>
        <?php foreach ($ladder as $i => $row): ?>
            <tr>
                <td class="num"><?= $i + 1 ?></td>
                <td><span style="color: <?= e(nl_class_color((int)$row['class'])) ?>"><strong><?= e($row['name']) ?></strong></span>
                    <span class="nl-sub"><?= e(nl_class_name((int)$row['class'])) ?></span></td>
                <td><?= e($row['map_name'] ?: 'Map ' . $row['map_id']) ?></td>
                <td><?= e(ch_bracket_name((int)$row['bracket'])) ?> <span class="nl-sub"><?= (int)$row['bracket'] ?></span></td>
                <td class="num"><strong><?= (int)$row['best_tier'] ?></strong></td>
                <td class="num"><?= (int)$row['tier'] ?></td>
                <td class="num"><?= (int)$row['clears'] ?></td>
                <td class="num"><?= (int)$row['fails'] ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
</div>
<?php endif; ?>

<div class="sec-head">
    <h2>Runs<?= $mapName ? ' &middot; ' . e($mapName) : '' ?></h2>
</div>

<?php if (!$runs): ?>
    <div class="empty"><?= neko_icon('paw') ?>No challenge runs<?= $mapName ? ' in ' . e($mapName) : '' ?> yet. Go see the Keeper.</div>
<?php else: ?>
<div class="tbl-wrap">
    <table class="tbl nl-runs">
        <thead><tr><th>Result</th><th>Instance</th><th>Started</th><th class="num">Tier</th><th>Difficulty</th><th class="num">Party</th><th class="num">Bosses</th><th class="num">Deaths</th><th></th></tr></thead>
        <tbody>
        <?php foreach ($runs as $r):
            $result = (int)$r['result'];
            $ended = (int)$r['ended_at'];
            $dur = $ended ? nl_duration(($ended - (int)$r['started_at']) * 1000) : null;
        ?>
            <tr>
                <td><span class="nl-result <?= e(ch_result_class($result)) ?>"><?= e(ch_result_label($result)) ?></span></td>
                <td><strong><?= e($r['map_name'] ?: 'Map ' . $r['map_id']) ?></strong>
                    <span class="nl-sub"><?= e(ch_bracket_name((int)$r['bracket'])) ?> &middot; level <?= (int)$r['bracket'] ?> &middot; led by <?= e($r['leader_name']) ?></span></td>
                <td title="<?= e(date('Y-m-d H:i', (int)$r['started_at'])) ?>"><?= e(neko_relative_time((int)$r['started_at'])) ?>
                    <span class="nl-sub"><?= $dur ? e($dur) : '<span class="nl-live">live</span>' ?></span></td>
                <td class="num"><strong><?= (int)$r['tier'] ?></strong></td>
                <td><?= e(ch_bonus((float)$r['health_mult'], (float)$r['damage_mult'])) ?></td>
                <td class="num"><?= (int)$r['members'] ?></td>
                <td class="num"><?= (int)$r['bosses'] ?></td>
                <td class="num"><?= (int)$r['deaths'] ?></td>
                <td class="num"><?php if ((int)$r['log_run_id']): ?><a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$r['log_run_id'] ?>">Log</a><?php endif; ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
</div>
<?php endif; ?>

<?php if ($runs && ($page > 1 || $hasMore)): ?>
<nav class="nl-pager" aria-label="Pages">
    <?php if ($page > 1): ?><a class="btn btn--ghost btn--sm" href="challenges.php?<?= $pageQuery($page - 1) ?>">&larr; Newer</a><?php else: ?><span></span><?php endif; ?>
    <?php if ($hasMore): ?><a class="btn btn--ghost btn--sm" href="challenges.php?<?= $pageQuery($page + 1) ?>">Older &rarr;</a><?php endif; ?>
</nav>
<?php endif; ?>

<?php endif; ?>

<?php neko_page_end(); ?>

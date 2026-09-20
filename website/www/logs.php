<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/logs.php';

$db = neko_db('chars');
$error = $db ? null : 'The character database is not reachable right now.';

$mapId = (int)($_GET['map'] ?? 0) ?: null;
$bossId = (int)($_GET['boss'] ?? 0) ?: null;
$page = max(1, (int)($_GET['page'] ?? 1));
$perPage = 40;
$runs = []; $pulls = []; $maps = []; $bosses = [];

if (!$error) {
    try {
        $maps = nl_maps($db);
        $bosses = nl_bosses($db);
        if ($bossId) {
            $pulls = nl_boss_pulls($db, $bossId, $perPage + 1, ($page - 1) * $perPage);
        } else {
            $runs = nl_recent_runs($db, $mapId, $perPage + 1, ($page - 1) * $perPage);
        }
    } catch (PDOException $e) {
        $error = 'Database error: ' . $e->getMessage();
    }
}
$rows = $bossId ? $pulls : $runs;
$hasMore = count($rows) > $perPage;
$rows = array_slice($rows, 0, $perPage);
$mapName = '';
foreach ($maps as $m) if ((int)$m['map_id'] === $mapId) $mapName = $m['map_name'];
$boss = null;
foreach ($bosses as $b) if ((int)$b['boss_entry'] === $bossId) $boss = $b;
$pageQuery = fn(int $p) => http_build_query(array_filter(['map' => $mapId, 'boss' => $bossId, 'page' => $p > 1 ? $p : null]));

neko_page_start(['title' => $boss ? $boss['boss_name'] . ' pulls' : 'Logs', 'active' => 'logs',
    'description' => 'Every boss pull on NekoCore, logged by the server itself.']);
?>

<div class="page-head">
    <h1>Combat logs</h1>
    <p>Every boss pull on the realm is recorded by the server as it happens &mdash; damage, healing, deaths, casts and auras, from the pull to the kill or the wipe. Trash isn't logged. Nothing is uploaded and nothing can be edited, so what you see here is what actually happened.</p>
</div>

<?php if ($error): ?>
    <div class="empty"><?= neko_icon('paw') ?><?= e($error) ?></div>
<?php else: ?>

<?php if ($maps): ?>
<nav class="nl-filter" aria-label="Filter by instance">
    <a href="logs.php"<?= ($mapId || $bossId) ? '' : ' aria-current="page"' ?>>All instances</a>
    <?php foreach ($maps as $m): ?>
        <a href="logs.php?map=<?= (int)$m['map_id'] ?>"<?= (int)$m['map_id'] === $mapId && !$bossId ? ' aria-current="page"' : '' ?>><?= e($m['map_name'] ?: 'Map ' . $m['map_id']) ?> <span><?= (int)$m['runs'] ?></span></a>
    <?php endforeach; ?>
    <?php if ($bosses): ?>
    <form class="nl-bossform" method="get" action="logs.php">
        <label class="visually-hidden" for="nl-boss">Boss</label>
        <select id="nl-boss" name="boss" onchange="this.form.submit()">
            <option value="">By boss&hellip;</option>
            <?php $group = null; foreach ($bosses as $b):
                if ($b['map_name'] !== $group) { if ($group !== null) echo '</optgroup>'; $group = $b['map_name']; echo '<optgroup label="' . e($group) . '">'; } ?>
                <option value="<?= (int)$b['boss_entry'] ?>"<?= (int)$b['boss_entry'] === $bossId ? ' selected' : '' ?>><?= e($b['boss_name']) ?> (<?= (int)$b['kills'] ?>/<?= (int)$b['pulls'] ?>)</option>
            <?php endforeach; if ($group !== null) echo '</optgroup>'; ?>
        </select>
        <noscript><button class="btn btn--ghost btn--sm" type="submit">Go</button></noscript>
    </form>
    <?php endif; ?>
</nav>
<?php endif; ?>

<?php if ($bossId): ?>
    <div class="sec-head">
        <h2><?= e($boss ? $boss['boss_name'] : 'Boss #' . $bossId) ?></h2>
        <?php if ($boss): ?><span class="notice-line"><?= e($boss['map_name']) ?> &middot; <?= (int)$boss['kills'] ?> kill<?= (int)$boss['kills'] === 1 ? '' : 's' ?> in <?= (int)$boss['pulls'] ?> pull<?= (int)$boss['pulls'] === 1 ? '' : 's' ?></span><?php endif; ?>
    </div>
    <?php if (!$rows): ?>
        <div class="empty"><?= neko_icon('paw') ?>No pulls logged for this boss.</div>
    <?php else: ?>
    <div class="tbl-wrap">
        <table class="tbl nl-runs">
            <thead><tr><th>Result</th><th>When</th><th>Fight</th><th class="num">Players</th><th>Era</th><th></th></tr></thead>
            <tbody>
            <?php foreach ($rows as $p):
                $ms = ((int)$p['end_ms'] ?: (int)$p['start_ms']) - (int)$p['start_ms'];
                $at = (int)$p['started_at'] + intdiv((int)$p['start_ms'], 1000);
                $era = nl_era_name((int)$p['min_era']) . (nl_era_name((int)$p['min_era']) !== nl_era_name((int)$p['max_era']) ? '–' . nl_era_name((int)$p['max_era']) : '');
            ?>
                <tr>
                    <td><span class="nl-result <?= e(nl_result_class((int)$p['result'])) ?>"><?= e(nl_result_label((int)$p['result'])) ?></span></td>
                    <td title="<?= e(date('Y-m-d H:i', $at)) ?>"><?= e(neko_relative_time($at)) ?>
                        <span class="nl-sub"><?= e($p['map_name']) ?> &middot; <?= e(nl_difficulty($p)) ?></span></td>
                    <td><?= e(nl_duration($ms)) ?></td>
                    <td class="num"><?= (int)$p['players'] ?></td>
                    <td><?= e($era) ?></td>
                    <td class="num"><a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$p['run_id'] ?>&amp;enc=<?= (int)$p['id'] ?>">View</a></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
    <?php endif; ?>

<?php elseif (!$rows): ?>
    <div class="empty"><?= neko_icon('paw') ?>No runs logged yet<?= $mapName ? ' for ' . e($mapName) : '' ?>. Go pull something.</div>
<?php else: ?>
    <div class="tbl-wrap">
        <table class="tbl nl-runs">
            <thead><tr><th>Instance</th><th>Started</th><th>Duration</th><th class="num">Bosses</th><th class="num">Wipes</th><th></th></tr></thead>
            <tbody>
            <?php foreach ($rows as $r):
                $ended = (int)$r['ended_at'];
                $dur = $ended ? nl_duration(($ended - (int)$r['started_at']) * 1000) : 'live';
            ?>
                <tr>
                    <td><a href="log.php?id=<?= (int)$r['id'] ?>"><strong><?= e($r['map_name'] ?: 'Map ' . $r['map_id']) ?></strong></a>
                        <span class="nl-sub"><?= e(nl_difficulty($r)) ?></span></td>
                    <td title="<?= e(date('Y-m-d H:i', (int)$r['started_at'])) ?>"><?= e(neko_relative_time((int)$r['started_at'])) ?></td>
                    <td><?= $ended ? e($dur) : '<span class="nl-live">live</span>' ?></td>
                    <td class="num"><?= (int)$r['kills'] ?></td>
                    <td class="num"><?= (int)$r['wipes'] ?></td>
                    <td class="num"><a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$r['id'] ?>">View</a></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
<?php endif; ?>

<?php if ($rows && ($page > 1 || $hasMore)): ?>
<nav class="nl-pager" aria-label="Pages">
    <?php if ($page > 1): ?><a class="btn btn--ghost btn--sm" href="logs.php?<?= $pageQuery($page - 1) ?>">&larr; Newer</a><?php else: ?><span></span><?php endif; ?>
    <?php if ($hasMore): ?><a class="btn btn--ghost btn--sm" href="logs.php?<?= $pageQuery($page + 1) ?>">Older &rarr;</a><?php endif; ?>
</nav>
<?php endif; ?>

<?php endif; ?>

<?php neko_page_end(); ?>

<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/logs.php';

/*
 * Rankings drill-down: instances -> bosses of an instance -> one boss's tables.
 *   rankings.php                    list of instances with kills
 *   rankings.php?map=36             Deadmines: its bosses, best time + top DPS each
 *   rankings.php?map=36&boss=644    Rhahk'Zor: fastest kills / top damage / top healing
 */

$db = neko_db('chars');
$error = $db ? null : 'The character database is not reachable right now.';

$mapId = (int)($_GET['map'] ?? 0);
$bossId = (int)($_GET['boss'] ?? 0);
$metric = in_array($_GET['metric'] ?? '', ['speed', 'dps', 'hps'], true) ? $_GET['metric'] : 'speed';
$filters = [
    'class'   => (int)($_GET['class'] ?? 0) ?: null,
    'players' => (int)($_GET['players'] ?? 0) ?: null,
    'era'     => in_array($_GET['era'] ?? '', ['Vanilla', 'TBC', 'WotLK'], true) ? $_GET['era'] : null,
];

$maps = []; $map = null; $bosses = []; $boss = null; $rows = []; $members = []; $sizes = [];

if (!$error) {
    try {
        nl_refresh_ranks($db);
        $maps = nl_rank_maps($db);
        if ($bossId && !$mapId) {
            // Old-style link: find the boss's instance.
            $st = $db->prepare("SELECT map_id FROM nekolog_rank WHERE boss_entry = :b LIMIT 1");
            $st->execute(['b' => $bossId]);
            $mapId = (int)$st->fetchColumn();
        }
        foreach ($maps as $m) if ((int)$m['map_id'] === $mapId) $map = $m;
        if ($map) {
            $bosses = nl_rank_bosses($db, $mapId);
            foreach ($bosses as $b) if ((int)$b['boss_entry'] === $bossId) $boss = $b;
        }
        if ($boss) {
            $rows = nl_rankings($db, $bossId, $metric, $filters);
            if ($metric === 'speed') $members = nl_kill_members($db, array_column($rows, 'enc_id'));
            $st = $db->prepare("SELECT DISTINCT players FROM nekolog_rank WHERE boss_entry = :b AND guid <> 0 ORDER BY players");
            $st->execute(['b' => $bossId]);
            $sizes = $st->fetchAll(PDO::FETCH_COLUMN);
        }
    } catch (PDOException $e) {
        $error = 'Database error: ' . $e->getMessage();
    }
}

$q = function (array $over = []) use ($mapId, $bossId, $metric, $filters): string {
    return http_build_query(array_filter(array_merge(['map' => $mapId, 'boss' => $bossId, 'metric' => $metric], $filters, $over), fn($v) => $v !== null && $v !== 0 && $v !== ''));
};

$title = $boss ? $boss['boss_name'] . ' rankings' : ($map ? $map['map_name'] . ' rankings' : 'Rankings');
neko_page_start(['title' => $title, 'active' => 'rankings',
    'description' => 'Fastest kills and top damage/healing per boss on NekoCore, from server-side logs.']);
?>

<div class="page-head">
    <p class="nl-crumb">
        <a href="rankings.php">Rankings</a>
        <?php if ($map): ?> / <a href="rankings.php?map=<?= (int)$map['map_id'] ?>"><?= e($map['map_name']) ?></a><?php endif; ?>
        <?php if ($boss): ?> / <?= e($boss['boss_name']) ?><?php endif; ?>
    </p>
    <h1><?= $boss ? e($boss['boss_name']) : ($map ? e($map['map_name']) : 'Rankings') ?>
        <?php if ($boss): ?><span class="nl-sub"><?= e($map['map_name']) ?></span><?php endif; ?></h1>
    <p><?php if ($boss): ?>Best kills of this boss, straight from the server's own logs. Damage and healing are per player; speed is per kill. Filter by group size and era &mdash; a solo kill and a five-player kill face very different bosses here.
       <?php elseif ($map): ?>Pick a boss for the full tables. The one-liners below are the all-time best, any group size.
       <?php else: ?>Best kills per boss, straight from the server's own logs. Pick an instance, then a boss.<?php endif; ?></p>
</div>

<?php if ($error): ?>
    <div class="empty"><?= neko_icon('paw') ?><?= e($error) ?></div>
<?php elseif (!$maps): ?>
    <div class="empty"><?= neko_icon('paw') ?>No kills logged yet. Rankings appear after the first boss goes down.</div>

<?php elseif (!$map): ?>
    <div class="tbl-wrap"><table class="tbl nl-rank">
        <thead><tr><th>Instance</th><th>Type</th><th class="num">Bosses ranked</th><th class="num">Kills</th><th>Last kill</th><th></th></tr></thead>
        <tbody>
        <?php foreach ($maps as $m): ?>
            <tr>
                <td><a href="rankings.php?map=<?= (int)$m['map_id'] ?>"><strong><?= e($m['map_name']) ?></strong></a></td>
                <td><?= $m['is_raid'] ? 'Raid' : 'Dungeon' ?></td>
                <td class="num"><?= (int)$m['bosses'] ?></td>
                <td class="num"><?= (int)$m['kills'] ?></td>
                <td title="<?= e(date('Y-m-d H:i', (int)$m['last_kill'])) ?>"><?= e(neko_relative_time((int)$m['last_kill'])) ?></td>
                <td class="num"><a class="btn btn--ghost btn--sm" href="rankings.php?map=<?= (int)$m['map_id'] ?>">Bosses</a></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table></div>

<?php elseif (!$boss): ?>
    <div class="tbl-wrap"><table class="tbl nl-rank">
        <thead><tr><th>Boss</th><th class="num">Kills</th><th>Fastest kill</th><th>Top damage</th><th></th></tr></thead>
        <tbody>
        <?php foreach ($bosses as $b): $f = $b['fastest']; $t = $b['top']; ?>
            <tr>
                <td><?php if ((int)$b['kills']): ?><a href="rankings.php?<?= http_build_query(['map' => $mapId, 'boss' => (int)$b['boss_entry']]) ?>"><strong><?= e($b['boss_name']) ?></strong></a><?php else: ?><strong><?= e($b['boss_name']) ?></strong><?php endif; ?>
                    <span class="nl-sub"><?= (int)$b['pulls'] ?> pull<?= (int)$b['pulls'] === 1 ? '' : 's' ?></span></td>
                <td class="num"><?= (int)$b['kills'] ?></td>
                <td><?php if ($f): ?><a href="log.php?id=<?= (int)$f['run_id'] ?>&amp;enc=<?= (int)$f['enc_id'] ?>"><?= e(nl_duration((int)$f['duration_ms'])) ?></a> <span class="nl-sub"><?= (int)$f['players'] ?>p</span><?php else: ?><span class="nl-unknown">&mdash;</span><?php endif; ?></td>
                <td><?php if ($t): $c = (int)$t['class']; ?><span class="nl-name" style="color:<?= nl_class_color($c) ?>"><?= e($t['name']) ?></span> <span class="nl-sub"><?= e(nl_num((float)$t['dps'])) ?> DPS &middot; <?= e(trim(nl_spec_name($c, (int)$t['spec']) . ' ' . nl_class_name($c))) ?></span><?php else: ?><span class="nl-unknown">&mdash;</span><?php endif; ?></td>
                <td class="num"><?php if ((int)$b['kills']): ?><a class="btn btn--ghost btn--sm" href="rankings.php?<?= http_build_query(['map' => $mapId, 'boss' => (int)$b['boss_entry']]) ?>">Rankings</a><?php endif; ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table></div>

<?php else: ?>
<div class="cols nl-cols">
    <div>
        <nav class="nl-tabs" aria-label="Metric">
            <?php foreach (['speed' => 'Fastest kills', 'dps' => 'Top damage', 'hps' => 'Top healing'] as $k => $label): ?>
                <a href="rankings.php?<?= $q(['metric' => $k]) ?>"<?= $metric === $k ? ' aria-current="page"' : '' ?>><?= e($label) ?></a>
            <?php endforeach; ?>
        </nav>

        <nav class="nl-filter nl-filter--tight" aria-label="Filters">
            <a href="rankings.php?<?= $q(['players' => null]) ?>"<?= $filters['players'] ? '' : ' aria-current="page"' ?>>Any size</a>
            <?php foreach ($sizes as $n): ?>
                <a href="rankings.php?<?= $q(['players' => (int)$n]) ?>"<?= $filters['players'] === (int)$n ? ' aria-current="page"' : '' ?>><?= (int)$n ?>p</a>
            <?php endforeach; ?>
            <span class="nl-filter__gap"></span>
            <a href="rankings.php?<?= $q(['era' => null]) ?>"<?= $filters['era'] ? '' : ' aria-current="page"' ?>>Any era</a>
            <?php foreach (['Vanilla', 'TBC', 'WotLK'] as $era): ?>
                <a href="rankings.php?<?= $q(['era' => $era]) ?>"<?= $filters['era'] === $era ? ' aria-current="page"' : '' ?>><?= $era ?></a>
            <?php endforeach; ?>
        </nav>

        <?php if ($metric !== 'speed'): ?>
        <nav class="nl-filter nl-filter--tight" aria-label="Class">
            <a href="rankings.php?<?= $q(['class' => null]) ?>"<?= $filters['class'] ? '' : ' aria-current="page"' ?>>All classes</a>
            <?php foreach (NL_CLASS as $id => [$name, $color]): ?>
                <a href="rankings.php?<?= $q(['class' => $id]) ?>" style="--c:<?= $color ?>" class="nl-classchip"<?= $filters['class'] === $id ? ' aria-current="page"' : '' ?>><?= e($name) ?></a>
            <?php endforeach; ?>
        </nav>
        <?php endif; ?>

        <?php if (!$rows): ?>
            <div class="empty"><?= neko_icon('paw') ?>Nothing matches those filters yet.</div>

        <?php elseif ($metric === 'speed'): ?>
            <div class="tbl-wrap"><table class="tbl nl-rank">
                <thead><tr><th>#</th><th>Time</th><th>Group</th><th class="num">Size</th><th>Difficulty</th><th>Era</th><th>When</th><th></th></tr></thead>
                <tbody>
                <?php $i = 0; foreach ($rows as $r): $i++; ?>
                    <tr>
                        <td class="nl-rank-pos <?= $i <= 3 ? 'is-top' : '' ?>"><?= $i ?></td>
                        <td><strong><?= e(nl_duration((int)$r['duration_ms'])) ?></strong></td>
                        <td class="nl-members">
                            <?php foreach (array_slice($members[$r['enc_id']] ?? [], 0, 8) as $m): ?>
                                <span style="color:<?= nl_class_color((int)$m['class']) ?>" title="<?= e(trim(nl_spec_name((int)$m['class'], (int)$m['spec']) . ' ' . nl_class_name((int)$m['class']))) ?>"><?= e($m['name']) ?></span>
                            <?php endforeach; ?>
                            <?php if (count($members[$r['enc_id']] ?? []) > 8): ?><span class="nl-sub">+<?= count($members[$r['enc_id']]) - 8 ?></span><?php endif; ?>
                        </td>
                        <td class="num"><?= (int)$r['players'] ?></td>
                        <td><?= e(nl_difficulty($r)) ?></td>
                        <td><?= e(nl_era_name((int)$r['era'])) ?></td>
                        <td title="<?= e(date('Y-m-d H:i', (int)$r['killed_at'])) ?>"><?= e(neko_relative_time((int)$r['killed_at'])) ?></td>
                        <td class="num"><a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$r['run_id'] ?>&amp;enc=<?= (int)$r['enc_id'] ?>">Log</a></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table></div>

        <?php else: $col = $metric; $tot = $metric === 'hps' ? 'healing' : 'damage'; ?>
            <div class="tbl-wrap"><table class="tbl nl-rank">
                <thead><tr><th>#</th><th>Player</th><th class="num"><?= strtoupper($col) ?></th><th class="num">Total</th><th>Time</th><th class="num">Size</th><th>Difficulty</th><th>Era</th><th>When</th><th></th></tr></thead>
                <tbody>
                <?php $i = 0; foreach ($rows as $r): $i++; $cls = (int)$r['class']; ?>
                    <tr>
                        <td class="nl-rank-pos <?= $i <= 3 ? 'is-top' : '' ?>"><?= $i ?></td>
                        <td><span class="nl-name" style="color:<?= nl_class_color($cls) ?>"><?= e($r['name']) ?></span>
                            <span class="nl-sub"><?= e(trim(nl_spec_name($cls, (int)$r['spec']) . ' ' . nl_class_name($cls))) ?> &middot; L<?= (int)$r['level'] ?></span></td>
                        <td class="num"><strong><?= e(nl_num((float)$r[$col])) ?></strong></td>
                        <td class="num"><?= e(nl_num((int)$r[$tot])) ?></td>
                        <td><?= e(nl_duration((int)$r['duration_ms'])) ?></td>
                        <td class="num"><?= (int)$r['players'] ?></td>
                        <td><?= e(nl_difficulty($r)) ?></td>
                        <td><?= e(nl_era_name((int)$r['era'])) ?></td>
                        <td title="<?= e(date('Y-m-d H:i', (int)$r['killed_at'])) ?>"><?= e(neko_relative_time((int)$r['killed_at'])) ?></td>
                        <td class="num"><a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$r['run_id'] ?>&amp;enc=<?= (int)$r['enc_id'] ?>">Log</a></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table></div>
        <?php endif; ?>
    </div>

    <aside>
        <div class="sec-head"><h2><?= e($map['map_name']) ?></h2><a href="rankings.php?map=<?= (int)$map['map_id'] ?>">Overview</a></div>
        <ul class="nl-bosslist">
        <?php foreach ($bosses as $b): if (!(int)$b['kills']) continue; ?>
            <li<?= (int)$b['boss_entry'] === $bossId ? ' aria-current="true"' : '' ?>>
                <a href="rankings.php?<?= http_build_query(array_filter(['map' => $mapId, 'boss' => (int)$b['boss_entry'], 'metric' => $metric])) ?>">
                    <?= e($b['boss_name']) ?> <span class="nl-sub"><?= (int)$b['kills'] ?> kill<?= (int)$b['kills'] === 1 ? '' : 's' ?></span>
                </a>
            </li>
        <?php endforeach; ?>
        </ul>
        <p><a href="rankings.php">&larr; All instances</a></p>
    </aside>
</div>
<?php endif; ?>

<?php neko_page_end(); ?>

<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/logs.php';

$pdo_chars = neko_db('chars');
$error = $pdo_chars ? null : 'The character database is not reachable right now.';

$char_name = trim((string)($_GET['char'] ?? ''));
$char = null;
$chars = [];

$rank_points = [];
if (!$error) {
    try {
        // Ranking points come from CURRENT positions on rankings.php -- nothing is banked.
        try { nl_refresh_ranks($pdo_chars); $rank_points = nl_rank_points($pdo_chars); } catch (PDOException $e) { $rank_points = []; }
        if ($char_name !== '') {
            $stmt = $pdo_chars->prepare("SELECT guid, name, level, totaltime FROM characters WHERE name = :name");
            $stmt->execute(['name' => $char_name]);
            $char = $stmt->fetch(PDO::FETCH_ASSOC) ?: null;

            if ($char) {
                $stmt = $pdo_chars->prepare("SELECT it.name, it.Quality FROM character_inventory ci JOIN item_instance i ON ci.item = i.guid JOIN acore_world.item_template it ON i.itemEntry = it.entry WHERE ci.guid = :guid AND ci.bag = 0 AND ci.slot BETWEEN 0 AND 18 ORDER BY ci.slot");
                $stmt->execute(['guid' => $char['guid']]);
                $items = $stmt->fetchAll(PDO::FETCH_ASSOC);

                $stmt = $pdo_chars->prepare("SELECT COUNT(*) FROM character_achievement WHERE guid = :guid");
                $stmt->execute(['guid' => $char['guid']]);
                $achievement_points = (int)$stmt->fetchColumn();

                $hours = $char['totaltime'] / 3600;
                $time_points = $hours * 0.5;
                $gear_points = 0;
                foreach ($items as $item) {
                    $gear_points += [0, 0, 1, 2, 3, 4, 4, 5][(int)$item['Quality']] ?? 0;
                }
                $ranking = $rank_points[$char['guid']] ?? ['points' => 0, 'spots' => []];
                $total_points = (int)$char['level'] + $time_points + $gear_points + $achievement_points + $ranking['points'];
            }
        } else {
            $chars = $pdo_chars->query("
                SELECT c.guid, c.name, c.level, c.totaltime,
                    COALESCE((SELECT SUM(CASE it.Quality WHEN 2 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 3 WHEN 5 THEN 4 ELSE 0 END)
                        FROM character_inventory ci JOIN item_instance i ON ci.item=i.guid JOIN acore_world.item_template it ON i.itemEntry=it.entry
                        WHERE ci.guid=c.guid AND ci.bag=0 AND ci.slot BETWEEN 0 AND 18), 0) AS gear_points,
                    COALESCE((SELECT COUNT(*) FROM character_achievement ca WHERE ca.guid=c.guid), 0) AS achievement_points
                FROM characters c
                ORDER BY (c.level + (c.totaltime/7200.0) + gear_points + achievement_points) DESC
                LIMIT 500
            ")->fetchAll(PDO::FETCH_ASSOC);
            foreach ($chars as &$row) {
                $row['rank_points'] = $rank_points[$row['guid']]['points'] ?? 0;
                $row['total'] = $row['level'] + ($row['totaltime'] / 7200.0) + $row['gear_points'] + $row['achievement_points'] + $row['rank_points'];
            }
            unset($row);
            usort($chars, fn($a, $b) => $b['total'] <=> $a['total']);
            $chars = array_slice($chars, 0, 100);
        }
    } catch (PDOException $e) {
        neko_log_error('leaderboard', $e);
        $error = 'The database had a problem loading this page. Try again in a moment.';
    }
}

$quality_names = [0 => 'Poor', 1 => 'Common', 2 => 'Uncommon', 3 => 'Rare', 4 => 'Epic', 5 => 'Legendary', 6 => 'Artifact', 7 => 'Heirloom'];

neko_page_start(['title' => $char ? $char['name'] : 'Leaderboard', 'active' => 'leaderboard']);
?>

<?php if ($char): ?>
    <div class="page-head">
        <h1><?= e($char['name']) ?></h1>
        <p>Level <?= (int)$char['level'] ?> · <?= number_format($hours, 1) ?> hours played</p>
    </div>

    <div class="cols">
        <div>
            <div class="sec-head"><h2>Equipped gear</h2><span class="notice-line"><?= count($items) ?> items</span></div>
            <?php if (empty($items)): ?>
                <div class="empty"><?= neko_icon('paw') ?>Nothing equipped. Brave.</div>
            <?php else: ?>
                <div class="tbl-wrap">
                    <table class="tbl">
                        <thead><tr><th>Item</th><th>Quality</th><th class="num">Points</th></tr></thead>
                        <tbody>
                            <?php foreach ($items as $item): $q = (int)$item['Quality']; ?>
                                <tr>
                                    <td class="q-<?= $q ?>"><?= e($item['name']) ?></td>
                                    <td><?= e($quality_names[$q] ?? 'Unknown') ?></td>
                                    <td class="num"><?= [0, 0, 1, 2, 3, 4, 4, 5][$q] ?? 0 ?></td>
                                </tr>
                            <?php endforeach; ?>
                        </tbody>
                    </table>
                </div>
            <?php endif; ?>
            <p class="back-link"><a href="lb.php"><?= neko_icon('chev-l') ?> Back to the leaderboard</a></p>
        </div>

        <aside>
            <div class="panel breakdown">
                <h3 class="panel__title"><?= neko_icon('crown') ?> Score breakdown</h3>
                <dl>
                    <dt>Level</dt><dd><?= (int)$char['level'] ?> pts</dd>
                    <dt>Time played</dt><dd><?= number_format($time_points, 1) ?> pts</dd>
                    <dt>Achievements</dt><dd><?= number_format($achievement_points) ?> pts</dd>
                    <dt>Gear</dt><dd><?= $gear_points ?> pts</dd>
                    <dt>Rankings</dt><dd><?= number_format($ranking['points']) ?> pts</dd>
                </dl>
                <div class="total"><?= number_format($total_points, 1) ?> points</div>
            </div>
            <div class="panel">
                <h3 class="panel__title"><?= neko_icon('book') ?> How scoring works</h3>
                <p class="notice-line" style="margin: 0;">One point per level, half a point per hour played, one per achievement, and gear points by quality: green 1, blue 2, purple 3, orange 4. Plus ranking points for every boss where you currently hold a top spot: #1 <?= NL_RANK_POINTS[1] ?>, #2 <?= NL_RANK_POINTS[2] ?>, #3 <?= NL_RANK_POINTS[3] ?> &mdash; for fastest kill (everyone in the kill), top damage and top healing. Get knocked down a spot and the points go with it.</p>
            </div>
            <?php if (!empty($ranking['spots'])): ?>
            <div class="panel">
                <h3 class="panel__title"><?= neko_icon('crown') ?> Held ranks</h3>
                <ul class="nl-spots">
                    <?php foreach ($ranking['spots'] as [$bossName, $metric, $pos, $pts]): ?>
                        <li><span class="nl-rank-pos is-top">#<?= $pos ?></span> <?= e($bossName) ?> <span class="nl-sub"><?= ['speed' => 'fastest kill', 'dps' => 'damage', 'hps' => 'healing'][$metric] ?> &middot; <?= $pts ?> pts</span></li>
                    <?php endforeach; ?>
                </ul>
                <p class="notice-line"><a href="rankings.php">All rankings &rarr;</a></p>
            </div>
            <?php endif; ?>
        </aside>
    </div>

<?php else: ?>
    <div class="page-head">
        <h1>Leaderboard</h1>
        <p>The top hundred adventurers on NekoCore, scored on level, time played, achievements, gear and the <a href="rankings.php">boss rankings</a> they currently hold.</p>
    </div>

    <?php if ($error): ?>
        <div class="alert alert--error"><?= e($error) ?></div>
    <?php elseif ($char_name !== ''): ?>
        <div class="alert alert--warn">No character named “<?= e($char_name) ?>” exists.</div>
        <p class="back-link"><a href="lb.php"><?= neko_icon('chev-l') ?> Back to the leaderboard</a></p>
    <?php elseif (empty($chars)): ?>
        <div class="empty"><?= neko_icon('paw') ?>No characters yet. Be the first name on this list.</div>
    <?php else: ?>
        <div class="tbl-wrap">
            <table class="tbl">
                <thead><tr><th class="rank">#</th><th>Name</th><th class="num">Level</th><th class="num">Hours</th><th class="num">Ranks</th><th class="num">Points</th></tr></thead>
                <tbody>
                    <?php $rank = 1; foreach ($chars as $row): $total = $row['total']; ?>
                        <tr>
                            <td class="rank"><?= $rank++ ?></td>
                            <td><a href="lb.php?char=<?= rawurlencode($row['name']) ?>"><?= e($row['name']) ?></a></td>
                            <td class="num"><?= (int)$row['level'] ?></td>
                            <td class="num"><?= number_format($row['totaltime'] / 3600, 1) ?></td>
                            <td class="num"><?= $row['rank_points'] ? number_format($row['rank_points']) : '<span class="nl-unknown">&mdash;</span>' ?></td>
                            <td class="num"><?= number_format($total, 1) ?></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
    <?php endif; ?>
<?php endif; ?>

<?php neko_page_end(); ?>

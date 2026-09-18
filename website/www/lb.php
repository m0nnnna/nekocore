<?php
include 'C:\laragon\db_connect_chars.php';

$errors = [];
if (!isset($pdo_chars)) {
    $errors[] = 'Characters database connection failed. Leaderboard unavailable.';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Leaderboard</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">

        <!-- Navigation -->
        <nav class="nav-bar">
            <a href="index.php" class="nav-brand">
                <img src="images/logo3.png" alt="NekoCore">
                <span>NekoCore</span>
            </a>
            <div class="nav-links">
                <a href="index.php">Home</a>
                <a href="announcements.php">News</a>
                <a href="lb.php" class="active">Leaderboard</a>
                <a href="dropsearch.php">Drops</a>
                <a href="exchange.php">Exchange</a>
            </div>
        </nav>

        <!-- Page Header -->
        <div class="page-header">
            <h2>Leaderboard</h2>
            <p class="subtitle">Top adventurers of NekoCore</p>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <?php foreach ($errors as $error): ?>
                    <p><?= htmlspecialchars($error) ?></p>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>

        <?php if (isset($_GET['char']) && empty($errors)): ?>
            <?php
            $char_name = $_GET['char'];
            try {
                $stmt = $pdo_chars->prepare("SELECT guid, name, level, totaltime FROM characters WHERE name = :name");
                $stmt->execute(['name' => $char_name]);
                $char = $stmt->fetch(PDO::FETCH_ASSOC);

                if (!$char) {
                    echo '<div class="alert alert--error">Character not found.</div>';
                } else {
                    $guid = $char['guid'];

                    $stmt_items = $pdo_chars->prepare("SELECT it.name, it.Quality FROM character_inventory ci JOIN item_instance i ON ci.item = i.guid JOIN acore_world.item_template it ON i.itemEntry = it.entry WHERE ci.guid = :guid AND ci.bag = 0 AND ci.slot BETWEEN 0 AND 18");
                    $stmt_items->execute(['guid' => $guid]);
                    $items = $stmt_items->fetchAll(PDO::FETCH_ASSOC);

                    $ach = $pdo_chars->prepare("SELECT COUNT(*) FROM character_achievement WHERE guid = :guid");
                    $ach->execute(['guid' => $guid]);
                    $achievement_points = (int)$ach->fetchColumn();

                    $level_points = (int)$char['level'];
                    $hours = $char['totaltime'] / 3600;
                    $time_points = $hours * 0.5;
                    $gear_points = 0;
                    $item_list = '';

                    foreach ($items as $item) {
                        $q = (int)($item['Quality'] ?? 0);
                        $points = [0,0,1,2,3,4,4,5][$q] ?? 0;
                        $gear_points += $points;
                        $color = match($q) { 2=>'Green',3=>'Blue',4=>'Purple',5=>'Legendary',default=>'Trash' };
                        $item_list .= htmlspecialchars($item['name']) . " <strong>($color)</strong><br>";
                    }

                    $total_points = $level_points + $time_points + $gear_points + $achievement_points;
                    ?>

                    <div class="breakdown">
                        <h3><?= htmlspecialchars($char['name']) ?> - Point Breakdown</h3>
                        <p>Level: <strong><?= $char['level'] ?></strong> &#8594; <?= $level_points ?> pts</p>
                        <p>Time Played: <strong><?= round($hours,1) ?>h</strong> &#8594; <?= round($time_points,2) ?> pts</p>
                        <p>Achievement Points: <strong><?= number_format($achievement_points) ?></strong></p>
                        <p>Gear Points: <strong><?= $gear_points ?></strong></p>
                        <p>Equipped Items:<br><?= $item_list ?: '<em>None</em>' ?></p>
                        <p><strong>Total Points: <?= round($total_points,2) ?></strong></p>
                    </div>

                    <div class="back-link">
                        <a href="lb.php">&#8592; Back to Leaderboard</a>
                    </div>

                <?php }
            } catch (Exception $e) {
                echo '<div class="alert alert--error">Error: '.htmlspecialchars($e->getMessage()).'</div>';
            }
            ?>

        <?php else: ?>
            <?php
            if (empty($errors)) {
                try {
                    $stmt = $pdo_chars->query("
                        SELECT c.name, c.level, c.totaltime,
                            COALESCE((SELECT SUM(CASE it.Quality WHEN 2 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 3 WHEN 5 THEN 4 ELSE 0 END)
                                FROM character_inventory ci JOIN item_instance i ON ci.item=i.guid JOIN acore_world.item_template it ON i.itemEntry=it.entry
                                WHERE ci.guid=c.guid AND ci.bag=0 AND ci.slot BETWEEN 0 AND 18), 0) AS gear_points,
                            COALESCE((SELECT COUNT(*) FROM character_achievement ca WHERE ca.guid=c.guid), 0) AS achievement_points
                        FROM characters c
                        ORDER BY (c.level + (c.totaltime/7200.0) + gear_points + achievement_points) DESC
                        LIMIT 100
                    ");
                    $chars = $stmt->fetchAll(PDO::FETCH_ASSOC);

                    if ($chars) {
                        echo '<div class="table-wrapper"><table><thead><tr><th>Rank</th><th>Name</th><th>Total Points</th></tr></thead><tbody>';
                        $rank = 1;
                        foreach ($chars as $row) {
                            $total = $row['level'] + ($row['totaltime']/7200.0) + $row['gear_points'] + $row['achievement_points'];
                            echo '<tr>
                                <td class="rank-cell">'.$rank++.'</td>
                                <td><a href="?char='.urlencode($row['name']).'">'.htmlspecialchars($row['name']).'</a></td>
                                <td>'.round($total,2).'</td>
                            </tr>';
                        }
                        echo '</tbody></table></div>';
                    } else {
                        echo '<div class="empty-state"><span class="icon"><svg viewBox="0 0 24 24" fill="currentColor"><ellipse cx="12" cy="17" rx="6.5" ry="5.2"/><circle cx="4.8" cy="9.5" r="2.4"/><circle cx="10" cy="5" r="2.2"/><circle cx="15" cy="5" r="2.2"/><circle cx="19.2" cy="9.5" r="2.4"/></svg></span>No characters yet. Be the first!</div>';
                    }
                } catch (PDOException $e) {
                    echo '<div class="alert alert--error">DB error: '.htmlspecialchars($e->getMessage()).'</div>';
                }
            }
            ?>
        <?php endif; ?>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="https://wiki.nekos.farm/en/WoW">Wiki</a></p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>
</body>
</html>

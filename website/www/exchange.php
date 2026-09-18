<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\db_connect_chars.php';  // This should connect to ac_characters
include 'C:\laragon\db_connect_world.php';

$results = [];
$errors = [];

try {
    if (!$pdo_chars) {
        throw new Exception('Characters database connection failed.');
    }

    $sql = "
        SELECT
            id,
            subject,
            give_item,
            give_qty,
            receive_item,
            receive_qty,
            enabled,
            description
        FROM item_exchange_rates
        WHERE enabled = 1
        ORDER BY id ASC
    ";

    $stmt = $pdo_chars->query($sql);
    $results = $stmt->fetchAll(PDO::FETCH_ASSOC);

    if (empty($results)) {
        $errors[] = 'No active exchange rates found.';
    }

} catch (Exception $e) {
    $errors[] = 'Database error: ' . $e->getMessage();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Item Exchange</title>
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
                <a href="lb.php">Leaderboard</a>
                <a href="dropsearch.php">Drops</a>
                <a href="exchange.php" class="active">Exchange</a>
            </div>
        </nav>

        <!-- Page Header -->
        <div class="page-header">
            <h2>Item Exchange Rates</h2>
            <p class="subtitle">Current active item exchanges</p>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <?php foreach ($errors as $e): ?>
                    <p><?= htmlspecialchars($e) ?></p>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>

        <?php if (!empty($results)): ?>
            <p class="result-note">Currently Active Exchanges (<?= count($results) ?>)</p>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Subject</th>
                            <th>Give</th>
                            <th>Qty</th>
                            <th></th>
                            <th>Receive</th>
                            <th>Qty</th>
                            <th>Status</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ($results as $row): ?>
                            <tr>
                                <td><?= htmlspecialchars($row['id']) ?></td>
                                <td><?= htmlspecialchars($row['subject']) ?></td>
                                <td><?= htmlspecialchars($row['give_item']) ?></td>
                                <td><?= htmlspecialchars($row['give_qty']) ?></td>
                                <td style="text-align:center; color: var(--coral);">&#8594;</td>
                                <td><?= htmlspecialchars($row['receive_item']) ?></td>
                                <td><?= htmlspecialchars($row['receive_qty']) ?></td>
                                <td class="<?= $row['enabled'] ? 'badge--on' : 'badge--off' ?>">
                                    <?= $row['enabled'] ? 'ON' : 'OFF' ?>
                                </td>
                                <td style="text-align:left;"><?= htmlspecialchars($row['description']) ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        <?php endif; ?>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="https://wiki.nekos.farm/en/WoW">Wiki</a></p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>
</body>
</html>

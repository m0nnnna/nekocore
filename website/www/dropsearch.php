<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\db_connect_chars.php';
include 'C:\laragon\db_connect_world.php';  // Make sure this file exists!

$search_item = trim($_GET['item'] ?? '');
$results     = [];
$errors      = [];

if ($search_item !== '' && !ctype_digit($search_item)) {
    $errors[] = 'Please enter a valid numeric Item ID.';
}

if ($search_item !== '' && empty($errors)) {
    if (!$pdo_world) {
        $errors[] = 'World database connection failed.';
    } else {
        try {
			$all_results = [];

			// Query 1: Direct creature drops
			$sql1 = "
				SELECT DISTINCT
					clt.Entry,
					clt.Item,
					clt.Chance,
					CONCAT(ct.name, ' - ', it.name) AS Comment
				FROM creature_loot_template clt
				JOIN creature_template ct ON clt.Entry = ct.entry
				JOIN item_template it ON clt.Item = it.entry
				WHERE clt.Item = :item AND clt.Reference = 0
			";

			// Query 2: Referenced creature drops
			$sql2 = "
				SELECT DISTINCT
					clt.Entry,
					rlt.Item,
					rlt.Chance,
					CONCAT(ct.name, ' - ', it.name) AS Comment
				FROM creature_loot_template clt
				JOIN reference_loot_template rlt ON clt.Reference = rlt.Entry
				JOIN creature_template ct ON clt.Entry = ct.entry
				JOIN item_template it ON rlt.Item = it.entry
				WHERE rlt.Item = :item AND clt.Reference > 0
			";

			// Query 3a: Direct fishing drops
			$sql3a = "
				SELECT
					flt.Entry,
					flt.Item,
					flt.Chance,
					CONCAT('Fishing (Direct) - ', it.name, ' from pool ', flt.Entry) AS Comment
				FROM fishing_loot_template flt
				JOIN item_template it ON flt.Item = it.entry
				WHERE flt.Item = :item AND flt.Reference = 0
			";

			// Query 3b: Referenced fishing drops
			$sql3b = "
				SELECT
					flt.Entry,
					rlt.Item,
					rlt.Chance,
					CONCAT('Fishing (Ref) - ', it.name, ' from pool ', flt.Entry) AS Comment
				FROM fishing_loot_template flt
				JOIN reference_loot_template rlt ON flt.Reference = rlt.Entry
				JOIN item_template it ON rlt.Item = it.entry
				WHERE rlt.Item = :item AND flt.Reference > 0
			";

			// Execute all queries
			foreach ([$sql1, $sql2, $sql3a, $sql3b] as $sql) {
				$stmt = $pdo_world->prepare($sql);
				$stmt->execute(['item' => $search_item]);
				foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
					$all_results[] = $row;
				}
			}

			// Sort by chance descending
			usort($all_results, function($a, $b) {
				return $b['Chance'] <=> $a['Chance'];
			});

			$results = $all_results;

			if (empty($results)) {
				$errors[] = 'No drops found for Item ID ' . htmlspecialchars($search_item) . '.';
			}

		} catch (Exception $e) {
			$errors[] = 'Database error: ' . $e->getMessage();
		}
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Drop Search</title>
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
                <a href="dropsearch.php" class="active">Drops</a>
                <a href="exchange.php">Exchange</a>
            </div>
        </nav>

        <!-- Page Header -->
        <div class="page-header">
            <h2>Drop Chance Search</h2>
            <p class="subtitle">Find where items drop and their chances</p>
        </div>

        <!-- Search Box -->
        <div class="search-box">
            <form method="get">
                <input type="text" name="item" class="form-input" placeholder="Enter Item ID" value="<?= htmlspecialchars($search_item) ?>" required>
                <button type="submit" class="btn btn--primary">Search</button>
            </form>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <?php foreach ($errors as $e): ?>
                    <p><?= htmlspecialchars($e) ?></p>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>

        <?php if (!empty($results)): ?>
            <p class="result-note">Found <?= count($results) ?> drop source(s) for Item ID <?= htmlspecialchars($search_item) ?></p>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Entry</th>
                            <th>Item</th>
                            <th>Chance</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ($results as $row): ?>
                            <tr>
                                <td><?= htmlspecialchars($row['Entry']) ?></td>
                                <td><?= htmlspecialchars($row['Item']) ?></td>
                                <td><?= number_format((float)$row['Chance'], 4) ?>%</td>
                                <td style="text-align:left;"><?= htmlspecialchars($row['Comment']) ?></td>
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

<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

$search_item = trim((string)($_GET['item'] ?? ''));
$results = [];
$errors = [];
$item_name = null;

if ($search_item !== '' && !ctype_digit($search_item)) {
    $errors[] = 'Enter a numeric item ID (for example 19019).';
}

if ($search_item !== '' && empty($errors)) {
    $pdo_world = neko_db('world');
    if (!$pdo_world) {
        $errors[] = 'The world database is not reachable right now.';
    } else {
        try {
            $stmt = $pdo_world->prepare("SELECT name FROM item_template WHERE entry = :item");
            $stmt->execute(['item' => $search_item]);
            $item_name = $stmt->fetchColumn() ?: null;

            $queries = [
                // Direct creature drops
                "SELECT DISTINCT clt.Entry AS source_id, ct.name AS source, 'Creature' AS kind, clt.Chance
                 FROM creature_loot_template clt JOIN creature_template ct ON clt.Entry = ct.entry
                 WHERE clt.Item = :item AND clt.Reference = 0",
                // Referenced creature drops
                "SELECT DISTINCT clt.Entry AS source_id, ct.name AS source, 'Creature' AS kind, rlt.Chance
                 FROM creature_loot_template clt JOIN reference_loot_template rlt ON clt.Reference = rlt.Entry
                 JOIN creature_template ct ON clt.Entry = ct.entry
                 WHERE rlt.Item = :item AND clt.Reference > 0",
                // Fishing pools, direct and referenced
                "SELECT flt.Entry AS source_id, CONCAT('Fishing pool ', flt.Entry) AS source, 'Fishing' AS kind, flt.Chance
                 FROM fishing_loot_template flt WHERE flt.Item = :item AND flt.Reference = 0",
                "SELECT flt.Entry AS source_id, CONCAT('Fishing pool ', flt.Entry) AS source, 'Fishing' AS kind, rlt.Chance
                 FROM fishing_loot_template flt JOIN reference_loot_template rlt ON flt.Reference = rlt.Entry
                 WHERE rlt.Item = :item AND flt.Reference > 0",
            ];
            foreach ($queries as $sql) {
                $stmt = $pdo_world->prepare($sql);
                $stmt->execute(['item' => $search_item]);
                foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
                    $results[] = $row;
                }
            }
            usort($results, fn($a, $b) => $b['Chance'] <=> $a['Chance']);
        } catch (Exception $e) {
            $errors[] = 'Database error: ' . $e->getMessage();
        }
    }
}

neko_page_start(['title' => 'Drop search', 'active' => 'drops']);
?>

<div class="page-head">
    <h1>Drop search</h1>
    <p>Paste an item ID to see every creature and fishing pool that can drop it, with the roll chance.</p>
</div>

<form method="get" class="search" style="max-width: 420px; margin: 0 0 24px;" role="search">
    <input class="input" type="text" inputmode="numeric" name="item" value="<?= e($search_item) ?>" placeholder="Item ID, e.g. 19019" aria-label="Item ID" required autofocus>
    <button class="btn btn--coral" type="submit"><?= neko_icon('search') ?> Search</button>
</form>

<?php if (!empty($errors)): ?>
    <div class="alert alert--error"><?php foreach ($errors as $err): ?><p><?= e($err) ?></p><?php endforeach; ?></div>
<?php elseif ($search_item !== '' && empty($results)): ?>
    <div class="empty">
        <?= neko_icon('paw') ?>
        <?php if ($item_name): ?>
            <strong class="q-4"><?= e($item_name) ?></strong> exists but has no creature or fishing drops. It may come from a vendor, quest or chest.
        <?php else: ?>
            No item with ID <?= e($search_item) ?> exists.
        <?php endif; ?>
    </div>
<?php elseif (!empty($results)): ?>
    <p class="result-note"><?= count($results) ?> source<?= count($results) === 1 ? '' : 's' ?> for <strong><?= e($item_name ?? 'item ' . $search_item) ?></strong> (ID <?= e($search_item) ?>)</p>
    <div class="tbl-wrap">
        <table class="tbl">
            <thead><tr><th>Source</th><th>Type</th><th class="num">Entry</th><th class="num">Chance</th></tr></thead>
            <tbody>
                <?php foreach ($results as $row): ?>
                    <tr>
                        <td><?= e($row['source']) ?></td>
                        <td><?= e($row['kind']) ?></td>
                        <td class="num"><?= (int)$row['source_id'] ?></td>
                        <td class="num"><?= number_format(abs((float)$row['Chance']), 2) ?>%<?= (float)$row['Chance'] < 0 ? ' (quest)' : '' ?><?= (float)$row['Chance'] == 0 ? ' (grouped)' : '' ?></td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
    <p class="notice-line">A chance of 0% means the item rolls as part of a loot group; a negative chance marks quest-only drops.</p>
<?php else: ?>
    <p class="notice-line">Tip: item IDs are the number in a Wowhead URL, e.g. <code>wowhead.com/wotlk/item=<strong>19019</strong></code>.</p>
<?php endif; ?>

<?php neko_page_end(); ?>

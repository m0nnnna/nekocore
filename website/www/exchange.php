<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

$results = [];
$error = null;

$pdo_chars = neko_db('chars');
if (!$pdo_chars) {
    $error = 'The character database is not reachable right now.';
} else {
    try {
        $results = $pdo_chars->query("
            SELECT id, subject, give_item, give_qty, receive_item, receive_qty, description
            FROM item_exchange_rates
            WHERE enabled = 1
            ORDER BY id ASC
        ")->fetchAll(PDO::FETCH_ASSOC);
    } catch (Exception $e) {
        $error = 'Database error: ' . $e->getMessage();
    }
}

neko_page_start(['title' => 'Item exchange', 'active' => 'exchange']);
?>

<div class="page-head">
    <h1>Item exchange</h1>
    <p>Mail the items on the left with the listed subject and the exchange sends back what's on the right. These are the rates live on the realm right now.</p>
</div>

<?php if ($error): ?>
    <div class="alert alert--error"><?= e($error) ?></div>
<?php elseif (empty($results)): ?>
    <div class="empty"><?= neko_icon('coins') ?>No exchanges are open at the moment.</div>
<?php else: ?>
    <p class="result-note"><?= count($results) ?> active exchange<?= count($results) === 1 ? '' : 's' ?></p>
    <div class="tbl-wrap">
        <table class="tbl">
            <thead>
                <tr>
                    <th>Mail subject</th>
                    <th>You send</th>
                    <th class="arrow"></th>
                    <th>You get</th>
                    <th>Notes</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($results as $row): ?>
                    <tr>
                        <td><code><?= e($row['subject']) ?></code></td>
                        <td><?= (int)$row['give_qty'] ?> × <?= e($row['give_item']) ?></td>
                        <td class="arrow"><?= neko_icon('chev-r') ?></td>
                        <td><?= (int)$row['receive_qty'] ?> × <?= e($row['receive_item']) ?></td>
                        <td><?= e($row['description']) ?></td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
<?php endif; ?>

<?php neko_page_end(); ?>

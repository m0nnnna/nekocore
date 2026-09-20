<?php
require __DIR__ . '/../inc/bootstrap.php';
require __DIR__ . '/../inc/layout.php';
require __DIR__ . '/../inc/logs.php';
require __DIR__ . '/../inc/admin_auth.php';

/*
 * Staff: wipe the combat logs of characters that no longer exist. The server
 * keeps logs on character delete (they are the other players' history too)
 * and only unlinks the character; this is the manual "and now remove them"
 * step. Live characters can't be wiped from here.
 */

$admin = admin_require();
$db = neko_db('chars');
$error = $db ? null : 'The character database is not reachable right now.';

if (!$error && $_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_check();
    $name = trim((string)($_POST['name'] ?? ''));
    if ($name !== '' && ($_POST['action'] ?? '') === 'wipe') {
        try {
            $n = nl_wipe_deleted_player($db, $name);
            admin_flash(sprintf('Wiped %s: %d events, %d ranking rows, %d empty encounter%s and %d empty run%s removed.',
                $name, $n['events'], $n['kills'], $n['encounters'], $n['encounters'] === 1 ? '' : 's', $n['runs'], $n['runs'] === 1 ? '' : 's'));
        } catch (Throwable $t) {
            admin_flash('Could not wipe ' . $name . ': ' . $t->getMessage());
        }
    }
    header('Location: logs.php');
    exit;
}

$deleted = [];
if (!$error) {
    try { $deleted = nl_deleted_players($db); } catch (PDOException $e) { $error = 'Database error: ' . $e->getMessage(); }
}

neko_page_start(['title' => 'Log admin', 'base' => '../', 'active' => 'logs']);
require __DIR__ . '/_bar.php';
?>

<div class="sec-head">
    <h2>Deleted characters with logs</h2>
    <a class="btn btn--ghost btn--sm" href="../logs.php">Public logs</a>
</div>
<p class="notice-line">Deleting a character keeps its combat logs (they are everyone else's kill history too) and only unlinks the character. Wiping here removes that character's events, pets, ranking rows and leaderboard footprint; encounters and runs left with nobody in them are removed entirely. Other people's kills stay, minus this character's contribution. This cannot be undone.</p>

<?php if ($error): ?>
    <div class="alert alert--error"><?= e($error) ?></div>
<?php elseif (!$deleted): ?>
    <div class="empty"><?= neko_icon('paw') ?>No deleted characters have logs. Nothing to clean up.</div>
<?php else: ?>
    <div class="tbl-wrap">
        <table class="tbl">
            <thead><tr><th>Character</th><th class="num">Runs</th><th class="num">Ranked kills</th><th>Seen</th><th></th></tr></thead>
            <tbody>
            <?php foreach ($deleted as $d): $cls = (int)$d['class']; ?>
                <tr>
                    <td><span class="nl-name" style="color:<?= nl_class_color($cls) ?>"><?= e($d['name']) ?></span>
                        <span class="nl-sub"><?= e(nl_class_name($cls)) ?> &middot; L<?= (int)$d['level'] ?></span></td>
                    <td class="num"><?= (int)$d['runs'] ?></td>
                    <td class="num"><?= (int)$d['kills'] ?></td>
                    <td><?= e(date('M j, Y', (int)$d['first_seen'])) ?><?= $d['first_seen'] !== $d['last_seen'] ? ' &ndash; ' . e(date('M j, Y', (int)$d['last_seen'])) : '' ?></td>
                    <td class="num">
                        <form method="POST" action="logs.php" onsubmit="return confirm('Wipe every log of <?= e(addslashes($d['name'])) ?>? This cannot be undone.');">
                            <?= csrf_field() ?>
                            <input type="hidden" name="name" value="<?= e($d['name']) ?>">
                            <input type="hidden" name="action" value="wipe">
                            <button class="btn btn--danger btn--sm" type="submit">Wipe logs</button>
                        </form>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
<?php endif; ?>

<?php neko_page_end(); ?>

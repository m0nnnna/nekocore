<?php
/* Admin toolbar. Expects $admin (from admin_require()). */
$flash = admin_flash();
?>
<div class="admin-bar">
    <span>Signed in as <strong><?= e($admin['username']) ?></strong> (GM <?= (int)$admin['gmlevel'] ?>)</span>
    <a href="index.php">All posts</a>
    <a href="edit.php">New post</a>
    <a href="logs.php">Logs</a>
    <a href="../news.php">View site</a>
    <span class="spacer"></span>
    <form method="POST" action="logout.php"><?= csrf_field() ?><button class="btn btn--ghost btn--sm" type="submit">Sign out</button></form>
</div>
<?php if ($flash): ?>
    <div class="alert alert--success"><?= e($flash) ?></div>
<?php endif; ?>

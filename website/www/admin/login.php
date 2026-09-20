<?php
require __DIR__ . '/../inc/bootstrap.php';
require __DIR__ . '/../inc/layout.php';
require __DIR__ . '/../inc/admin_auth.php';

$next = (string)($_GET['next'] ?? $_POST['next'] ?? 'index.php');
// Only allow same-directory relative targets, never absolute URLs.
if ($next === '' || preg_match('#^(?:[a-z]+:|//)#i', $next) || str_contains($next, '..')) {
    $next = 'index.php';
}
$next = ltrim(preg_replace('#^/admin/?#', '', $next) ?? '', '/');
if ($next === '' || !preg_match('#^[a-z_]+\.php(\?[^\s]*)?$#', $next)) {
    $next = 'index.php';
}

if (admin_user()) {
    header('Location: ' . $next);
    exit;
}

$error = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $error = admin_login((string)($_POST['username'] ?? ''), (string)($_POST['password'] ?? ''));
    if ($error === null) {
        header('Location: ' . $next);
        exit;
    }
}

neko_page_start(['title' => 'Staff login', 'base' => '../']);
?>

<div class="narrow" style="margin: 0 auto;">
    <div class="page-head">
        <h1>Staff login</h1>
        <p>Sign in with your game account. It needs GM level <?= ADMIN_MIN_GMLEVEL ?> or higher.</p>
    </div>

    <?php if ($error): ?>
        <div class="alert alert--error"><?= e($error) ?></div>
    <?php endif; ?>

    <form method="POST" class="form-card">
        <input type="hidden" name="next" value="<?= e($next) ?>">
        <div class="field">
            <label for="username">Account name</label>
            <input class="input" type="text" id="username" name="username" required autocomplete="username" autofocus value="<?= e($_POST['username'] ?? '') ?>">
        </div>
        <div class="field">
            <label for="password">Password</label>
            <input class="input" type="password" id="password" name="password" required autocomplete="current-password">
        </div>
        <div class="form-actions">
            <button type="submit" class="btn btn--coral">Sign in</button>
            <span class="spacer"></span>
            <a href="../index.php">Back to the site</a>
        </div>
    </form>
</div>

<?php neko_page_end(); ?>

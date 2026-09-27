<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

neko_private('tokens.php');

$errors = [];
$success = false;
$token = trim($_GET['token'] ?? '');
$pdo = neko_db('auth');

if (!$pdo) {
    $errors[] = 'The account database is not reachable right now. Try the link again in a few minutes.';
} elseif (empty($token)) {
    $errors[] = 'This link is missing its verification token. Use the full link from the email.';
} else {
    $token_hash = hash_token($token);

    try {
        $pdo->beginTransaction();

        $stmt = $pdo->prepare("SELECT * FROM web_email_verification WHERE token_hash = :token_hash AND expires_at > NOW() FOR UPDATE");
        $stmt->execute(['token_hash' => $token_hash]);
        $pending = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$pending) {
            $pdo->rollBack();
            $errors[] = 'This verification link is invalid or has expired. Register again to get a fresh one.';
        } else {
            $stmt = $pdo->prepare("
                INSERT INTO account (username, salt, verifier, email, reg_mail, joindate, last_ip, expansion)
                VALUES (:username, :salt, :verifier, :email, :reg_mail, NOW(), :last_ip, 2)
            ");
            $stmt->execute([
                'username' => $pending['username'],
                'salt' => $pending['salt'],
                'verifier' => $pending['verifier'],
                'email' => $pending['email'],
                'reg_mail' => $pending['email'],
                'last_ip' => $pending['last_ip']
            ]);
            $pdo->prepare("DELETE FROM web_email_verification WHERE id = :id")->execute(['id' => $pending['id']]);
            $pdo->commit();
            $success = true;
        }
    } catch (PDOException $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        if (strpos($e->getMessage(), 'Duplicate entry') !== false) {
            $errors[] = 'That username or email was taken by another account while this link was waiting. Register again with a different username.';
        } else {
            $errors[] = 'Could not finish creating your account: ' . $e->getMessage();
        }
    }
}

neko_page_start(['title' => 'Verify email', 'active' => 'account']);
?>

<div class="narrow">
    <?php if ($success): ?>
        <div class="page-head">
            <h1>You're in!</h1>
            <p>Your account is verified and ready. Grab the patch and log in with the username and password you chose.</p>
        </div>
        <div class="panel panel--ice">
            <h3 class="panel__title"><?= neko_icon('download') ?> Start playing</h3>
            <?php neko_start_playing(); ?>
        </div>
        <p class="notice-line">New here? The <a href="<?= e($neko['wiki_url']) ?>">wiki</a> covers what's different on NekoCore, and <a href="<?= e($neko['discord_url']) ?>">Discord</a> is where everyone hangs out.</p>
    <?php else: ?>
        <div class="page-head">
            <h1>Verify your email</h1>
            <p>Finishing your registration.</p>
        </div>
        <div class="alert alert--error"><ul><?php foreach ($errors as $error): ?><li><?= e($error) ?></li><?php endforeach; ?></ul></div>
        <p><a class="btn btn--ice" href="register.php">Register again</a></p>
    <?php endif; ?>
</div>

<?php neko_page_end(); ?>

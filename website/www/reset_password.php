<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

neko_private('srp6.php');
neko_private('tokens.php');

$errors = [];
$success = false;
$token = trim($_GET['token'] ?? $_POST['token'] ?? '');
$valid_token = false;
$pdo = neko_db('auth');

if (!$pdo) {
    $errors[] = 'The account database is not reachable right now. Try again in a few minutes.';
} elseif (empty($token)) {
    $errors[] = 'This link is missing its reset token. Use the full link from the email.';
} else {
    $stmt = $pdo->prepare("SELECT * FROM web_password_reset WHERE token_hash = :token_hash AND used = 0 AND expires_at > NOW()");
    $stmt->execute(['token_hash' => hash_token($token)]);
    $reset_row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$reset_row) {
        $errors[] = 'This reset link is invalid or has expired. Request a new one below.';
    } else {
        $valid_token = true;

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $password = trim($_POST['password'] ?? '');
            $confirm_password = trim($_POST['confirm_password'] ?? '');

            if (empty($password) || strlen($password) < 6) {
                $errors[] = 'Password must be at least 6 characters.';
            }
            if ($password !== $confirm_password) {
                $errors[] = 'The two passwords don\'t match.';
            }

            if (empty($errors)) {
                try {
                    $pdo->beginTransaction();

                    // Re-check inside the transaction so two submissions of the
                    // same link (e.g. a double click) can't both succeed.
                    $stmt = $pdo->prepare("SELECT * FROM web_password_reset WHERE id = :id AND used = 0 AND expires_at > NOW() FOR UPDATE");
                    $stmt->execute(['id' => $reset_row['id']]);
                    $locked_row = $stmt->fetch(PDO::FETCH_ASSOC);

                    if (!$locked_row) {
                        $pdo->rollBack();
                        $errors[] = 'This reset link was already used or has expired. Request a new one below.';
                        $valid_token = false;
                    } else {
                        $stmt = $pdo->prepare("SELECT username FROM account WHERE id = :account_id");
                        $stmt->execute(['account_id' => $locked_row['account_id']]);
                        $username = $stmt->fetchColumn();

                        if (!$username) {
                            $pdo->rollBack();
                            $errors[] = 'That account no longer exists.';
                            $valid_token = false;
                        } else {
                            $srp_data = GetSRP6RegistrationData($username, $password);
                            $pdo->prepare("UPDATE account SET salt = :salt, verifier = :verifier WHERE id = :account_id")
                                ->execute(['salt' => $srp_data['salt'], 'verifier' => $srp_data['verifier'], 'account_id' => $locked_row['account_id']]);
                            $pdo->prepare("UPDATE web_password_reset SET used = 1 WHERE id = :id")->execute(['id' => $locked_row['id']]);
                            $pdo->commit();
                            $success = true;
                            $valid_token = false;
                        }
                    }
                } catch (Exception $e) {
                    if ($pdo->inTransaction()) {
                        $pdo->rollBack();
                    }
                    $errors[] = 'Could not reset your password: ' . $e->getMessage();
                }
            }
        }
    }
}

neko_page_start(['title' => 'Reset password', 'active' => 'account']);
?>

<div class="narrow">
    <div class="page-head">
        <h1>Choose a new password</h1>
        <p>You'll use it on the game's login screen right away.</p>
    </div>

    <?php if (!empty($errors)): ?>
        <div class="alert alert--error"><ul><?php foreach ($errors as $error): ?><li><?= e($error) ?></li><?php endforeach; ?></ul></div>
    <?php endif; ?>

    <?php if ($success): ?>
        <div class="alert alert--success">Your password is reset. Log in with the new one.</div>
        <p><a class="btn btn--ice" href="index.php">Back to home</a></p>
    <?php elseif ($valid_token): ?>
        <form method="POST" class="form-card">
            <input type="hidden" name="token" value="<?= e($token) ?>">
            <div class="field">
                <label for="password">New password</label>
                <input class="input" type="password" id="password" name="password" required minlength="6" autocomplete="new-password" placeholder="At least 6 characters" autofocus>
            </div>
            <div class="field">
                <label for="confirm_password">Confirm new password</label>
                <input class="input" type="password" id="confirm_password" name="confirm_password" required autocomplete="new-password" placeholder="Same again">
            </div>
            <div class="form-actions">
                <button type="submit" class="btn btn--coral">Set new password</button>
            </div>
        </form>
    <?php else: ?>
        <p><a class="btn btn--ice" href="forgot_password.php">Request a new reset link</a></p>
    <?php endif; ?>
</div>

<?php neko_page_end(); ?>

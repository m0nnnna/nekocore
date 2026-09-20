<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

neko_private('tokens.php');
neko_private('mailer.php');

$errors = [];
$submitted = false;
$reset_ttl_hours = 1;
$resend_cooldown_minutes = 5;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $identifier = trim($_POST['identifier'] ?? '');
    $pdo = neko_db('auth');

    if (empty($identifier)) {
        $errors[] = 'Enter your username or email.';
    } elseif (!$pdo) {
        $errors[] = 'The account database is not reachable right now. Try again in a few minutes.';
    } else {
        // Always show the same outcome whether or not an account matched,
        // so this form can't be used to check which usernames/emails exist.
        $submitted = true;

        try {
            $stmt = $pdo->prepare("SELECT id, email FROM account WHERE username = :username OR email = :email LIMIT 1");
            $stmt->execute(['username' => $identifier, 'email' => $identifier]);
            $account = $stmt->fetch(PDO::FETCH_ASSOC);

            if ($account) {
                $account_id = $account['id'];
                $pdo->exec("DELETE FROM web_password_reset WHERE expires_at < NOW()");

                $stmt = $pdo->prepare("SELECT COUNT(*) FROM web_password_reset WHERE account_id = :account_id AND used = 0 AND created_at > DATE_SUB(NOW(), INTERVAL :cooldown MINUTE)");
                $stmt->execute(['account_id' => $account_id, 'cooldown' => $resend_cooldown_minutes]);

                if ($stmt->fetchColumn() == 0) {
                    $token = generate_token();
                    $stmt = $pdo->prepare("
                        INSERT INTO web_password_reset (account_id, token_hash, last_ip, expires_at)
                        VALUES (:account_id, :token_hash, :last_ip, DATE_ADD(NOW(), INTERVAL :ttl HOUR))
                    ");
                    $stmt->execute([
                        'account_id' => $account_id,
                        'token_hash' => hash_token($token),
                        'last_ip' => $_SERVER['REMOTE_ADDR'] ?? '127.0.0.1',
                        'ttl' => $reset_ttl_hours
                    ]);

                    if (!empty($account['email'])) {
                        $reset_url = neko_base_url() . '/reset_password.php?token=' . urlencode($token);
                        try {
                            $mailer = new SmtpMailer(neko_mail_config());
                            $mailer->send(
                                $account['email'],
                                'Reset your NekoCore password',
                                "Someone (hopefully you) asked to reset the password for this account.\n\n" .
                                "Click the link below to set a new password:\n\n" .
                                "$reset_url\n\n" .
                                "This link expires in {$reset_ttl_hours} hour(s). If you didn't request this, just ignore this email -- your password won't change.\n"
                            );
                        } catch (Exception $e) {
                            // Swallow send failures too -- the response must not reveal
                            // whether an account/email existed.
                        }
                    }
                }
            }
        } catch (PDOException $e) {
            // Same reasoning: don't leak DB details or existence via error text.
        }
    }
}

neko_page_start(['title' => 'Forgot password', 'active' => 'account']);
?>

<div class="narrow">
    <div class="page-head">
        <h1>Forgot your password?</h1>
        <p>Tell us your username or email and we'll send a link to set a new one.</p>
    </div>

    <?php if (!empty($errors)): ?>
        <div class="alert alert--error"><ul><?php foreach ($errors as $error): ?><li><?= e($error) ?></li><?php endforeach; ?></ul></div>
    <?php endif; ?>

    <?php if ($submitted): ?>
        <div class="alert alert--success">
            If an account with that username or email exists, a reset link is on its way. It's valid for <?= $reset_ttl_hours ?> hour<?= $reset_ttl_hours === 1 ? '' : 's' ?> — check your spam folder if it doesn't show up.
        </div>
        <p><a class="btn btn--ice" href="index.php">Back to home</a></p>
    <?php else: ?>
        <form method="POST" class="form-card">
            <div class="field">
                <label for="identifier">Username or email</label>
                <input class="input" type="text" id="identifier" name="identifier" required autocomplete="username" placeholder="Your username or email" value="<?= e($_POST['identifier'] ?? '') ?>" autofocus>
            </div>
            <div class="form-actions">
                <button type="submit" class="btn btn--coral">Send reset link</button>
                <span class="spacer"></span>
                <a href="register.php">Need an account instead?</a>
            </div>
        </form>
    <?php endif; ?>
</div>

<?php neko_page_end(); ?>

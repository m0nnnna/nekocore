<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';

neko_private('srp6.php');
neko_private('tokens.php');
neko_private('mailer.php');

$verification_ttl_hours = 24;
$errors = [];
$pending_verification = false;

if ($neko['registrations_open'] && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $pdo = neko_db('auth');
    if (!$pdo) {
        $errors[] = 'The account database is not reachable right now. Try again in a few minutes.';
    } else {
        $username = trim($_POST['username'] ?? '');
        $password = trim($_POST['password'] ?? '');
        $confirm_password = trim($_POST['confirm_password'] ?? '');
        $email = trim($_POST['email'] ?? '');

        if (empty($username) || strlen($username) < 3 || strlen($username) > 16 || !preg_match('/^[a-zA-Z0-9]+$/', $username)) {
            $errors[] = 'Username must be 3–16 letters or numbers.';
        }
        if (empty($password) || strlen($password) < 6) {
            $errors[] = 'Password must be at least 6 characters.';
        }
        if ($password !== $confirm_password) {
            $errors[] = 'The two passwords don\'t match.';
        }
        if (empty($email) || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            $errors[] = 'Enter a valid email address.';
        }

        if (empty($errors)) {
            // Opportunistic cleanup: a stale, never-verified signup shouldn't
            // permanently squat a username or email.
            $pdo->exec("DELETE FROM web_email_verification WHERE expires_at < NOW()");

            $stmt = $pdo->prepare("SELECT COUNT(*) FROM account WHERE username = :username OR email = :email");
            $stmt->execute(['username' => $username, 'email' => $email]);
            if ($stmt->fetchColumn() > 0) {
                $errors[] = 'That username or email is already taken.';
            } else {
                $stmt = $pdo->prepare("SELECT COUNT(*) FROM web_email_verification WHERE username = :username OR email = :email");
                $stmt->execute(['username' => $username, 'email' => $email]);
                if ($stmt->fetchColumn() > 0) {
                    $errors[] = 'That username or email already has a verification email waiting. Check your inbox and spam folder, or try again once it expires.';
                } else {
                    try {
                        $srp_data = GetSRP6RegistrationData($username, $password);
                        $token = generate_token();

                        $stmt = $pdo->prepare("
                            INSERT INTO web_email_verification (username, email, salt, verifier, token_hash, last_ip, expires_at)
                            VALUES (:username, :email, :salt, :verifier, :token_hash, :last_ip, DATE_ADD(NOW(), INTERVAL :ttl HOUR))
                        ");
                        $stmt->execute([
                            'username' => $username,
                            'email' => $email,
                            'salt' => $srp_data['salt'],
                            'verifier' => $srp_data['verifier'],
                            'token_hash' => hash_token($token),
                            'last_ip' => $_SERVER['REMOTE_ADDR'] ?? '127.0.0.1',
                            'ttl' => $verification_ttl_hours
                        ]);

                        $verify_url = neko_base_url() . '/verify_email.php?token=' . urlencode($token);

                        $mailer = new SmtpMailer(neko_mail_config());
                        $mailer->send(
                            $email,
                            'Verify your NekoCore account',
                            "Welcome to NekoCore!\n\n" .
                            "Click the link below to verify your email and finish creating your account:\n\n" .
                            "$verify_url\n\n" .
                            "This link expires in {$verification_ttl_hours} hours. If you didn't request this, just ignore this email.\n"
                        );

                        $pending_verification = true;
                    } catch (Exception $e) {
                        // Don't leave an unreachable pending row behind if the email never went out.
                        $pdo->prepare("DELETE FROM web_email_verification WHERE username = :username")->execute(['username' => $username]);
                        $errors[] = 'The verification email couldn\'t be sent. Try again in a few minutes.';
                    }
                }
            }
        }
    }
}

neko_page_start(['title' => 'Create an account', 'active' => 'account']);
?>

<div class="cols">
    <div>
        <div class="page-head">
            <h1>Create an account</h1>
            <p>One account, all your characters. We'll email you a link to confirm it before it goes live.</p>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <ul><?php foreach ($errors as $error): ?><li><?= e($error) ?></li><?php endforeach; ?></ul>
            </div>
        <?php endif; ?>

        <?php if ($pending_verification): ?>
            <div class="alert alert--success">
                Almost there. Check your inbox for a verification link — it's good for <?= $verification_ttl_hours ?> hours. Once you click it, your account is ready to log in.
            </div>
            <p><a class="btn btn--ice" href="index.php">Back to home</a></p>
        <?php elseif (!$neko['registrations_open']): ?>
            <div class="alert alert--warn">Registrations are closed right now. Keep an eye on the <a href="news.php">news</a> for when they reopen.</div>
        <?php else: ?>
            <form method="POST" class="form-card narrow" autocomplete="on">
                <div class="field">
                    <label for="username">Username</label>
                    <input class="input" type="text" id="username" name="username" required minlength="3" maxlength="16" pattern="[A-Za-z0-9]+" autocomplete="username" placeholder="3–16 letters or numbers" value="<?= e($_POST['username'] ?? '') ?>">
                    <span class="help">This is what you type into the game's login screen.</span>
                </div>
                <div class="form-row">
                    <div class="field">
                        <label for="password">Password</label>
                        <input class="input" type="password" id="password" name="password" required minlength="6" autocomplete="new-password" placeholder="At least 6 characters">
                    </div>
                    <div class="field">
                        <label for="confirm_password">Confirm password</label>
                        <input class="input" type="password" id="confirm_password" name="confirm_password" required autocomplete="new-password" placeholder="Same again">
                    </div>
                </div>
                <div class="field">
                    <label for="email">Email</label>
                    <input class="input" type="email" id="email" name="email" required autocomplete="email" placeholder="you@example.com" value="<?= e($_POST['email'] ?? '') ?>">
                    <span class="help">Only used for verification and password resets. Never shown to anyone.</span>
                </div>
                <div class="form-actions">
                    <button type="submit" class="btn btn--coral">Create account</button>
                    <span class="spacer"></span>
                    <a href="forgot_password.php">Forgot your password?</a>
                </div>
            </form>
        <?php endif; ?>
    </div>

    <aside>
        <div class="panel">
            <h3 class="panel__title"><?= neko_icon('shield') ?> Keeping your account safe</h3>
            <p>Your password is never emailed and staff can't see it. Verification and reset links go to the email on file.</p>
            <p>Want two-factor login? In game, type <span class="kbd">.account 2fa setup</span>, scan the code with your authenticator app, then confirm with <span class="kbd">.account 2fa setup &lt;code&gt;</span>. 2FA lives entirely in game.</p>
        </div>
        <div class="panel panel--ice">
            <h3 class="panel__title"><?= neko_icon('download') ?> Then grab the patch</h3>
            <p>Once you're verified, set up your own 3.3.5a client:</p>
            <?php neko_start_playing(); ?>
        </div>
    </aside>
</div>

<?php neko_page_end(); ?>

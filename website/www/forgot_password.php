<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\tokens.php';
include 'C:\laragon\mailer.php';
include 'C:\laragon\mail_config.php';

$errors = [];
$submitted = false;
$reset_ttl_hours = 1;
$resend_cooldown_minutes = 5;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $identifier = trim($_POST['identifier'] ?? '');

    if (empty($identifier)) {
        $errors[] = 'Enter your username or email.';
    } elseif (!isset($pdo)) {
        $errors[] = 'Database connection failed. Please check your config.';
    } else {
        // Always show the same outcome whether or not an account matched,
        // so this form can't be used to check which usernames/emails exist.
        $submitted = true;

        try {
            $stmt = $pdo->prepare("SELECT id FROM account WHERE username = :username OR email = :email LIMIT 1");
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
                        SELECT email FROM account WHERE id = :account_id
                    ");
                    $stmt->execute(['account_id' => $account_id]);
                    $email = $stmt->fetchColumn();

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

                    if (!empty($email)) {
                        $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
                        $reset_url = $scheme . '://' . $_SERVER['HTTP_HOST'] . '/reset_password.php?token=' . urlencode($token);

                        try {
                            $mailer = new SmtpMailer($mail_config);
                            $mailer->send(
                                $email,
                                'Reset your NekoCore password',
                                "Someone (hopefully you) asked to reset the password for this account.\n\n" .
                                "Click the link below to set a new password:\n\n" .
                                "$reset_url\n\n" .
                                "This link expires in {$reset_ttl_hours} hour(s). If you didn't request this, just ignore this email -- your password won't change.\n"
                            );
                        } catch (Exception $e) {
                            // Swallow send failures here too -- the response to the visitor
                            // must not reveal whether an account/email existed.
                        }
                    }
                }
            }
        } catch (PDOException $e) {
            // Same reasoning: don't leak DB details or existence via error text.
        }
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Forgot Password</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container container--narrow">

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
                <a href="dropsearch.php">Drops</a>
                <a href="exchange.php">Exchange</a>
            </div>
        </nav>

        <div class="page-header">
            <h2>Forgot Password</h2>
            <p class="subtitle">We'll email you a link to set a new one</p>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <ul>
                    <?php foreach ($errors as $error): ?>
                        <li><?= htmlspecialchars($error) ?></li>
                    <?php endforeach; ?>
                </ul>
            </div>
        <?php endif; ?>

        <?php if ($submitted): ?>
            <div class="alert alert--success">
                If an account with that username or email exists, a password reset link is on its way. Check your inbox (and spam folder).
            </div>
        <?php else: ?>
            <form method="POST">
                <div class="form-group">
                    <label class="form-label" for="identifier">Username or Email</label>
                    <input type="text" id="identifier" name="identifier" class="form-input" required placeholder="Your username or email" value="<?= htmlspecialchars($_POST['identifier'] ?? '') ?>">
                </div>
                <button type="submit" class="btn btn--primary">Send Reset Link</button>
            </form>
        <?php endif; ?>

        <div class="back-link"><a href="index.php">&#8592; Back to home</a></div>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="https://wiki.nekos.farm/en/WoW">Wiki</a></p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>
</body>
</html>

<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\srp6.php';
include 'C:\laragon\tokens.php';

$errors = [];
$success = false;
$token = trim($_GET['token'] ?? $_POST['token'] ?? '');
$valid_token = false;

if (!isset($pdo)) {
    $errors[] = 'Database connection failed. Please check your config.';
} elseif (empty($token)) {
    $errors[] = 'Missing reset token.';
} else {
    $stmt = $pdo->prepare("SELECT * FROM web_password_reset WHERE token_hash = :token_hash AND used = 0 AND expires_at > NOW()");
    $stmt->execute(['token_hash' => hash_token($token)]);
    $reset_row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$reset_row) {
        $errors[] = 'This password reset link is invalid or has expired. Please request a new one.';
    } else {
        $valid_token = true;

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $password = trim($_POST['password'] ?? '');
            $confirm_password = trim($_POST['confirm_password'] ?? '');

            if (empty($password) || strlen($password) < 6) {
                $errors[] = 'Password must be at least 6 characters.';
            }
            if ($password !== $confirm_password) {
                $errors[] = 'Passwords do not match.';
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
                        $errors[] = 'This password reset link was already used or has expired. Please request a new one.';
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

                            $stmt = $pdo->prepare("UPDATE account SET salt = :salt, verifier = :verifier WHERE id = :account_id");
                            $stmt->execute([
                                'salt' => $srp_data['salt'],
                                'verifier' => $srp_data['verifier'],
                                'account_id' => $locked_row['account_id']
                            ]);

                            $stmt = $pdo->prepare("UPDATE web_password_reset SET used = 1 WHERE id = :id");
                            $stmt->execute(['id' => $locked_row['id']]);

                            $pdo->commit();
                            $success = true;
                            $valid_token = false;
                        }
                    }
                } catch (Exception $e) {
                    if ($pdo->inTransaction()) {
                        $pdo->rollBack();
                    }
                    $errors[] = 'Could not reset your password: ' . htmlspecialchars($e->getMessage());
                }
            }
        }
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Reset Password</title>
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
            <h2>Reset Password</h2>
            <p class="subtitle">Choose a new password</p>
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

        <?php if ($success): ?>
            <div class="alert alert--success">
                Your password has been reset. You can now log in with your new password.
            </div>
        <?php elseif ($valid_token): ?>
            <form method="POST">
                <input type="hidden" name="token" value="<?= htmlspecialchars($token) ?>">
                <div class="form-group">
                    <label class="form-label">New Password</label>
                    <input type="password" name="password" class="form-input" required minlength="6" placeholder="At least 6 characters">
                </div>
                <div class="form-group">
                    <label class="form-label">Confirm New Password</label>
                    <input type="password" name="confirm_password" class="form-input" required placeholder="Re-enter your new password">
                </div>
                <button type="submit" class="btn btn--primary">Reset Password</button>
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

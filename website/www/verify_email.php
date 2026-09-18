<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\tokens.php';

$errors = [];
$success = false;

$token = trim($_GET['token'] ?? '');

if (!isset($pdo)) {
    $errors[] = 'Database connection failed. Please check your config.';
} elseif (empty($token)) {
    $errors[] = 'Missing verification token.';
} else {
    $token_hash = hash_token($token);

    try {
        $pdo->beginTransaction();

        $stmt = $pdo->prepare("SELECT * FROM web_email_verification WHERE token_hash = :token_hash AND expires_at > NOW() FOR UPDATE");
        $stmt->execute(['token_hash' => $token_hash]);
        $pending = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$pending) {
            $pdo->rollBack();
            $errors[] = 'This verification link is invalid or has expired. Please register again.';
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

            $stmt = $pdo->prepare("DELETE FROM web_email_verification WHERE id = :id");
            $stmt->execute(['id' => $pending['id']]);

            $pdo->commit();
            $success = true;
        }
    } catch (PDOException $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        if (strpos($e->getMessage(), 'Duplicate entry') !== false) {
            $errors[] = 'That username or email was taken by another account while this link was waiting to be used. Please register again with a different username.';
        } else {
            $errors[] = 'Could not finish creating your account: ' . htmlspecialchars($e->getMessage());
        }
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Verify Email</title>
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
            <h2>Verify Email</h2>
            <p class="subtitle">Finishing your registration</p>
        </div>

        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <ul>
                    <?php foreach ($errors as $error): ?>
                        <li><?= htmlspecialchars($error) ?></li>
                    <?php endforeach; ?>
                </ul>
            </div>
            <div class="back-link"><a href="index.php">&#8592; Back to home</a></div>
        <?php elseif ($success): ?>
            <div class="alert alert--success">
                Your account is verified and ready! You can now log in.
            </div>
            <div class="cta-box">
                <p>Ready to connect? <a href="realmlist.wtf" download>Download Connection File</a></p>
                <small>Place this realmlist.wtf in your WoW/Data/enUS/ folder to connect.</small>
                <br><br>
                <p><a href="nekocore.zip" download>Download Client</a></p>
                <small>Extract the client zip and use it to play on the server.</small>
            </div>
        <?php endif; ?>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="https://wiki.nekos.farm/en/WoW">Wiki</a></p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>
</body>
</html>

<?php
include 'C:\laragon\db_connect.php';
include 'C:\laragon\db_connect_chars.php';
include 'C:\laragon\srp6.php';
include 'C:\laragon\tokens.php';
include 'C:\laragon\mailer.php';
include 'C:\laragon\mail_config.php';

$registrations_open = true;
$server_host = '108.174.48.199';
$auth_port = 3724;
$world_port = 8085;
$verification_ttl_hours = 24;

function isServerOnline($host, $port, $timeout = 1) {
    $fp = @fsockopen($host, $port, $errno, $errstr, $timeout);
    if ($fp) {
        fclose($fp);
        return true;
    }
    return false;
}

$auth_online = isServerOnline($server_host, $auth_port);
$world_online = isServerOnline($server_host, $world_port);

$errors = [];
$pending_verification = false;

if ($registrations_open && $_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!isset($pdo)) {
        $errors[] = 'Database connection failed. Please check your config.';
    } else {
        $username = trim($_POST['username'] ?? '');
        $password = trim($_POST['password'] ?? '');
        $confirm_password = trim($_POST['confirm_password'] ?? '');
        $email = trim($_POST['email'] ?? '');

        if (empty($username) || strlen($username) < 3 || strlen($username) > 16 || !preg_match('/^[a-zA-Z0-9]+$/', $username)) {
            $errors[] = 'Username must be 3-16 alphanumeric characters.';
        }
        if (empty($password) || strlen($password) < 6) {
            $errors[] = 'Password must be at least 6 characters.';
        }
        if ($password !== $confirm_password) {
            $errors[] = 'Passwords do not match.';
        }
        if (empty($email) || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            $errors[] = 'Invalid email address.';
        }

        if (empty($errors)) {
            // Opportunistic cleanup: a stale, never-verified signup shouldn't
            // permanently squat a username or email.
            $pdo->exec("DELETE FROM web_email_verification WHERE expires_at < NOW()");

            $stmt = $pdo->prepare("SELECT COUNT(*) FROM account WHERE username = :username OR email = :email");
            $stmt->execute(['username' => $username, 'email' => $email]);
            if ($stmt->fetchColumn() > 0) {
                $errors[] = 'Username or email already taken.';
            } else {
                $stmt = $pdo->prepare("SELECT COUNT(*) FROM web_email_verification WHERE username = :username OR email = :email");
                $stmt->execute(['username' => $username, 'email' => $email]);
                if ($stmt->fetchColumn() > 0) {
                    $errors[] = 'That username or email already has a pending verification email. Check your inbox (and spam folder), or try again once it expires.';
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

                        $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
                        $verify_url = $scheme . '://' . $_SERVER['HTTP_HOST'] . '/verify_email.php?token=' . urlencode($token);

                        $mailer = new SmtpMailer($mail_config);
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
                        $errors[] = 'Could not send the verification email. Please try again later.';
                    }
                }
            }
        }
    }
}

// Fetch most recent announcement from file
$recent_announcement = null;
$announcements_dir = __DIR__ . '/data/';
if (is_dir($announcements_dir)) {
    $files = glob($announcements_dir . '*.json');
    if (!empty($files)) {
        rsort($files);
        $latest_file = $files[0];
        $data = json_decode(file_get_contents($latest_file), true);
        if ($data) {
            $recent_announcement = $data;
        }
    }
}

$lb_errors = [];
$top_chars = [];
if (isset($pdo_chars) && $pdo_chars) {
    try {
        $stmt_lb = $pdo_chars->query("
            SELECT c.guid, c.name, c.level, c.totaltime,
                COALESCE((
                    SELECT SUM(CASE it.Quality
                        WHEN 2 THEN 1
                        WHEN 3 THEN 2
                        WHEN 4 THEN 3
                        WHEN 5 THEN 4
                        ELSE 0 END)
                    FROM character_inventory ci
                    JOIN item_instance i ON ci.item = i.guid
                    JOIN acore_world.item_template it ON i.itemEntry = it.entry
                    WHERE ci.guid = c.guid AND ci.bag = 0 AND ci.slot BETWEEN 0 AND 18
                ), 0) AS gear_points,
                COALESCE((
                    SELECT COUNT(ca.achievement)
                    FROM character_achievement ca
                    WHERE ca.guid = c.guid
                ), 0) AS achievement_points
            FROM characters c
            ORDER BY (c.level + (c.totaltime / 7200.0) + gear_points + achievement_points) DESC
            LIMIT 5
        ");
        $top_chars = $stmt_lb->fetchAll(PDO::FETCH_ASSOC);
    } catch (PDOException $e) {
        $lb_errors[] = 'Leaderboard database error: ' . $e->getMessage();
    }
} else {
    $lb_errors[] = 'Characters database connection failed. Leaderboard unavailable.';
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Welcome Home</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">

        <!-- Navigation -->
        <nav class="nav-bar">
            <a href="index.php" class="nav-brand">
                <img src="images/logo3.png" alt="NekoCore">
                <span>NekoCore</span>
            </a>
            <div class="nav-links">
                <a href="index.php" class="active">Home</a>
                <a href="announcements.php">News</a>
                <a href="lb.php">Leaderboard</a>
                <a href="dropsearch.php">Drops</a>
                <a href="exchange.php">Exchange</a>
            </div>
        </nav>

        <!-- Server Status Card -->
        <div class="card">
            <div class="card__title">
                <span class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s7-3.5 7-10V5l-7-3-7 3v6c0 6.5 7 10 7 10z"/></svg></span> Server Status
            </div>
            <div class="status-row">
                <div class="status-item">
                    <span class="status-dot <?php echo $auth_online ? 'status-dot--online' : 'status-dot--offline'; ?>"></span>
                    Auth Server: <strong class="<?php echo $auth_online ? 'server-online' : 'server-offline'; ?>"><?php echo $auth_online ? 'Online' : 'Offline'; ?></strong>
                </div>
                <div class="status-item">
                    <span class="status-dot <?php echo $world_online ? 'status-dot--online' : 'status-dot--offline'; ?>"></span>
                    World Server: <strong class="<?php echo $world_online ? 'server-online' : 'server-offline'; ?>"><?php echo $world_online ? 'Online' : 'Offline'; ?></strong>
                </div>
            </div>
        </div>

        <!-- Page Header -->
        <div class="page-header">
            <h1>Welcome to NekoCore</h1>
            <p class="subtitle">Your cozy WoW adventure starts here, nya~</p>
        </div>

        <!-- Beta Notice -->
        <div class="notice notice--warning">
            NekoCore is currently in beta. Please expect issues and report bugs on Discord!
        </div>

        <!-- Latest Announcement -->
        <?php if ($recent_announcement): ?>
        <div class="announcement-preview card">
            <div class="card__title">
                <span class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></span> Latest Announcement
            </div>
            <p><a href="announcements.php"><?= htmlspecialchars($recent_announcement['title']) ?></a></p>
            <p style="margin-top: 8px; font-size: 0.85em;"><a href="announcements.php">View all announcements</a></p>
        </div>
        <?php endif; ?>

        <!-- Error Messages -->
        <?php if (!empty($errors)): ?>
            <div class="alert alert--error">
                <ul>
                    <?php foreach ($errors as $error): ?>
                        <li><?= htmlspecialchars($error) ?></li>
                    <?php endforeach; ?>
                </ul>
            </div>
        <?php endif; ?>

        <!-- Success Message -->
        <?php if ($pending_verification): ?>
            <div class="alert alert--success">
                Almost there! Check your email for a verification link to finish creating your account.
            </div>
        <?php endif; ?>

        <!-- Registration Form -->
        <?php if ($registrations_open): ?>
            <button class="collapsible-trigger" id="reg-trigger">
                <span>New User Registration</span>
                <span class="arrow">&#9660;</span>
            </button>
            <div class="collapsible-body" id="reg-body">
                <div class="collapsible-body__inner">
                    <form method="POST">
                        <div class="form-group">
                            <label class="form-label">Username</label>
                            <input type="text" name="username" class="form-input" required maxlength="16" placeholder="3-16 alphanumeric characters" value="<?= htmlspecialchars($_POST['username'] ?? '') ?>">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Password</label>
                            <input type="password" name="password" class="form-input" required minlength="6" placeholder="At least 6 characters">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Confirm Password</label>
                            <input type="password" name="confirm_password" class="form-input" required placeholder="Re-enter your password">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Email</label>
                            <input type="email" name="email" class="form-input" required placeholder="your@email.com" value="<?= htmlspecialchars($_POST['email'] ?? '') ?>">
                        </div>
                        <button type="submit" class="btn btn--primary">Register</button>
                    </form>
                </div>
            </div>
        <?php else: ?>
            <div class="alert alert--error">Registrations are currently closed. Please check back later.</div>
        <?php endif; ?>

        <p style="text-align: center; font-size: 0.9em; margin-top: 12px;"><a href="forgot_password.php">Forgot your password?</a></p>

        <div class="info-box">
            <p>Account security: your password is never emailed or shown to staff. Verification and password reset links are sent to the email on file.</p>
            <p>Want two-factor login? Log in-game and type <strong>.account 2fa setup</strong>, follow the prompt with the code from your authenticator app, then confirm with <strong>.account 2fa setup &lt;code&gt;</strong>. 2FA is managed entirely in-game, not on this site.</p>
        </div>

        <!-- Downloads -->
        <div class="neko-divider"><span><svg viewBox="0 0 24 24"><ellipse cx="12" cy="17" rx="6.5" ry="5.2"/><circle cx="4.8" cy="9.5" r="2.4"/><circle cx="10" cy="5" r="2.2"/><circle cx="15" cy="5" r="2.2"/><circle cx="19.2" cy="9.5" r="2.4"/></svg></span></div>

        <div class="cta-box">
            <p>Ready to connect? <a href="realmlist.wtf" download>Download Connection File</a></p>
            <small>Place this realmlist.wtf in your WoW/Data/enUS/ folder to connect.</small>
            <br><br>
            <p><a href="nekocore.zip" download>Download Client</a></p>
            <small>Extract the client zip and use it to play on the server.</small>
        </div>

        <!-- Hall of Fame: NekoCore v1 Legends -->
        <div class="card card--highlight">
            <div class="card__title">
                <span class="icon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2 Z"/></svg></span> NekoCore v1 Legends
            </div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Rank</th>
                            <th>Name</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td class="rank-cell">1</td><td>Heil</td></tr>
                        <tr><td class="rank-cell">2</td><td>Noc</td></tr>
                        <tr><td class="rank-cell">3</td><td>Wyrd</td></tr>
                        <tr><td class="rank-cell">4</td><td>Pantsu</td></tr>
                        <tr><td class="rank-cell">5</td><td>Sieg</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Top 5 Leaderboard -->
        <div class="card">
            <div class="card__title">
                <span class="icon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M3,8 L7,12 L12,5 L17,12 L21,8 L19,18 L5,18 Z"/></svg></span> Top 5 Leaderboard
            </div>

            <?php if (!empty($lb_errors)): ?>
                <div class="alert alert--error">
                    <ul>
                        <?php foreach ($lb_errors as $error): ?>
                            <li><?= htmlspecialchars($error) ?></li>
                        <?php endforeach; ?>
                    </ul>
                </div>
            <?php elseif (empty($top_chars)): ?>
                <div class="empty-state">
                    <span class="icon"><svg viewBox="0 0 24 24" fill="currentColor"><ellipse cx="12" cy="17" rx="6.5" ry="5.2"/><circle cx="4.8" cy="9.5" r="2.4"/><circle cx="10" cy="5" r="2.2"/><circle cx="15" cy="5" r="2.2"/><circle cx="19.2" cy="9.5" r="2.4"/></svg></span>
                    No characters found yet. Be the first adventurer!
                </div>
            <?php else: ?>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Name</th>
                                <th>Total Points</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php
                            $rank = 1;
                            foreach ($top_chars as $row) {
                                $level_points = (int)$row['level'];
                                $time_points = $row['totaltime'] / 7200.0;
                                $gear_points = (float) ($row['gear_points'] ?? 0);
                                $achievement_points = (float) ($row['achievement_points'] ?? 0);
                                $total_points = $level_points + $time_points + $gear_points + $achievement_points;
                            ?>
                                <tr>
                                    <td class="rank-cell"><?= $rank ?></td>
                                    <td><?= htmlspecialchars($row['name']) ?></td>
                                    <td><?= round($total_points, 2) ?></td>
                                </tr>
                            <?php
                                $rank++;
                            }
                            ?>
                        </tbody>
                    </table>
                </div>
                <p style="text-align: center; font-size: 0.9em;"><a href="lb.php">View full leaderboard</a></p>
            <?php endif; ?>
        </div>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="exchange.php">Item Exchange</a> &#8226; <a href="dropsearch.php">Drop Search</a> &#8226; <a href="https://discord.gg/Qdwtxews27">Discord</a></p>
            <p>Need help? Check out the <a href="https://wiki.nekos.farm/en/WoW">wiki</a>.</p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>

    <script>
        // Collapsible functionality
        document.getElementById('reg-trigger').addEventListener('click', function() {
            this.classList.toggle('active');
            var body = document.getElementById('reg-body');
            if (body.style.maxHeight) {
                body.style.maxHeight = null;
                body.classList.remove('open');
            } else {
                body.style.maxHeight = body.scrollHeight + 'px';
                body.classList.add('open');
            }
        });
    </script>
</body>
</html>

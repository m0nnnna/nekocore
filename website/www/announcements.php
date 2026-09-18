<?php
$errors = [];
$announcements = [];

// Read announcements from JSON files
$announcements_dir = __DIR__ . '/data/';
if (is_dir($announcements_dir)) {
    $files = glob($announcements_dir . '*.json');
    if (!empty($files)) {
        // Sort by filename (timestamp) descending
        rsort($files);
        foreach ($files as $file) {
            $data = json_decode(file_get_contents($file), true);
            if ($data) {
                $announcements[] = $data;
            }
        }
    }
} else {
    $errors[] = 'Announcements directory not found. Path: ' . $announcements_dir;
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NekoCore ~ Announcements</title>
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
                <a href="index.php">Home</a>
                <a href="announcements.php" class="active">News</a>
                <a href="lb.php">Leaderboard</a>
                <a href="dropsearch.php">Drops</a>
                <a href="exchange.php">Exchange</a>
            </div>
        </nav>

        <!-- Page Header -->
        <div class="page-header">
            <h2>Announcements</h2>
            <p class="subtitle">Stay up to date with the latest NekoCore news</p>
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

        <?php if (empty($announcements) && empty($errors)): ?>
            <div class="empty-state">
                <span class="icon"><svg viewBox="0 0 24 24" fill="currentColor"><ellipse cx="12" cy="17" rx="6.5" ry="5.2"/><circle cx="4.8" cy="9.5" r="2.4"/><circle cx="10" cy="5" r="2.2"/><circle cx="15" cy="5" r="2.2"/><circle cx="19.2" cy="9.5" r="2.4"/></svg></span>
                No announcements yet. Check back soon, nya~
            </div>
        <?php else: ?>
            <?php foreach ($announcements as $announcement): ?>
                <div class="announcement-item">
                    <button class="announcement-trigger">
                        <span class="title"><?= htmlspecialchars($announcement['title']) ?></span>
                        <span class="date"><?= date('M j, Y', $announcement['timestamp']) ?></span>
                        <span class="arrow">&#9660;</span>
                    </button>
                    <div class="announcement-body">
                        <div class="announcement-body__inner">
<?= nl2br(htmlspecialchars(preg_replace('/\r/', '', preg_replace('/^[ \t]{4,}/m', '', $announcement['body'])))) ?>
                        </div>
                    </div>
                </div>
            <?php endforeach; ?>
        <?php endif; ?>

        <!-- Footer -->
        <footer class="footer">
            <p><a href="https://wiki.nekos.farm/en/WoW">Wiki</a></p>
            <div class="neko-footer-art">&#128049;&#128062;&#128049;</div>
        </footer>

    </div>

    <script>
        // Collapsible announcements
        var triggers = document.getElementsByClassName('announcement-trigger');
        for (var i = 0; i < triggers.length; i++) {
            triggers[i].addEventListener('click', function() {
                this.classList.toggle('active');
                var body = this.nextElementSibling;
                if (body.style.maxHeight) {
                    body.style.maxHeight = null;
                } else {
                    body.style.maxHeight = body.scrollHeight + 'px';
                }
            });
        }
    </script>
</body>
</html>

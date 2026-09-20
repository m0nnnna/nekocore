<?php
/*
 * One-shot import of the old JSON announcements (www/data/*.json) into the
 * web_news table. Safe to re-run: posts whose slug already exists are skipped.
 *
 *   php import_announcements.php [path/to/www]
 *
 * Lives in the private directory next to db_connect.php.
 */

require __DIR__ . '/db_connect.php';
date_default_timezone_set('America/Chicago');
$pdo->exec("SET time_zone = " . $pdo->quote(date('P'))); // match the website's clock

$www = $argv[1] ?? (__DIR__ . '/www');
$data_dir = rtrim($www, '/\\') . '/data';
$files = glob($data_dir . '/*.json') ?: [];

if (!$files) {
    echo "No announcement JSON files found in $data_dir\n";
    exit(1);
}

$slugify = function (string $text): string {
    $text = mb_strtolower(trim($text));
    $text = preg_replace('/[^\p{L}\p{N}]+/u', '-', $text) ?? '';
    return mb_substr(trim($text, '-') ?: 'post', 0, 100);
};

$exists = $pdo->prepare("SELECT COUNT(*) FROM web_news WHERE slug = :slug");
$insert = $pdo->prepare("
    INSERT INTO web_news (slug, title, category, body, author, status, pinned, published_at, created_at)
    VALUES (:slug, :title, 'announcement', :body, 'NekoCore', 'published', 0, :published_at, :published_at)
");

sort($files);
$imported = 0;
foreach ($files as $file) {
    $data = json_decode((string)file_get_contents($file), true);
    if (!$data || empty($data['title'])) {
        echo "skip (unreadable): $file\n";
        continue;
    }
    $ts = (int)($data['timestamp'] ?? filemtime($file));
    $slug = $slugify($data['title']);
    $base = $slug;
    $n = 2;

    $exists->execute(['slug' => $slug]);
    if ((int)$exists->fetchColumn() > 0) {
        echo "skip (already imported): {$data['title']}\n";
        continue;
    }

    // Normalise the old body: strip the 4-space indentation the old page trimmed at render time.
    $body = str_replace("\r", '', (string)($data['body'] ?? ''));
    $body = preg_replace('/^[ \t]{4,}/m', '', $body) ?? $body;

    $insert->execute([
        'slug' => $slug,
        'title' => trim($data['title']),
        'body' => trim($body),
        'published_at' => date('Y-m-d H:i:s', $ts),
    ]);
    $imported++;
    echo "imported: {$data['title']} (" . date('Y-m-d', $ts) . ")\n";
}

echo "\nDone. $imported post(s) imported.\n";

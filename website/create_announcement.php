<?php
/*
 * Post news from the command line (the web admin at /admin/ is the nicer way).
 *
 *   php create_announcement.php "Title" "Body in Markdown" [category] [--draft] [--pin]
 *   php create_announcement.php "Title" path/to/body.md patch-notes
 *
 * Categories: announcement (default), patch-notes, event, maintenance, community.
 * Lives in the private directory next to db_connect.php.
 */

require __DIR__ . '/db_connect.php';
date_default_timezone_set('America/Chicago');
$pdo->exec("SET time_zone = " . $pdo->quote(date('P'))); // match the website's clock

$args = array_values(array_filter(array_slice($argv, 1), fn($a) => !str_starts_with($a, '--')));
$flags = array_filter(array_slice($argv, 1), fn($a) => str_starts_with($a, '--'));

$title = $args[0] ?? '';
$body = $args[1] ?? '';
$category = $args[2] ?? 'announcement';

if ($title === '' || $body === '') {
    fwrite(STDERR, "usage: php create_announcement.php \"Title\" \"Body or body.md\" [category] [--draft] [--pin]\n");
    exit(1);
}
if (is_file($body)) {
    $body = (string)file_get_contents($body);
}
$allowed = ['announcement', 'patch-notes', 'event', 'maintenance', 'community'];
if (!in_array($category, $allowed, true)) {
    fwrite(STDERR, "unknown category '$category'; use one of: " . implode(', ', $allowed) . "\n");
    exit(1);
}

$slug = mb_strtolower(trim($title));
$slug = mb_substr(trim(preg_replace('/[^\p{L}\p{N}]+/u', '-', $slug) ?? 'post', '-'), 0, 100) ?: 'post';
$base = $slug;
$n = 2;
$check = $pdo->prepare("SELECT COUNT(*) FROM web_news WHERE slug = :slug");
while (true) {
    $check->execute(['slug' => $slug]);
    if ((int)$check->fetchColumn() === 0) break;
    $slug = $base . '-' . $n++;
}

$status = in_array('--draft', $flags, true) ? 'draft' : 'published';
$pdo->prepare("
    INSERT INTO web_news (slug, title, category, body, author, status, pinned, published_at)
    VALUES (:slug, :title, :category, :body, 'NekoCore', :status, :pinned, :published_at)
")->execute([
    'slug' => $slug,
    'title' => trim($title),
    'category' => $category,
    'body' => trim($body),
    'status' => $status,
    'pinned' => in_array('--pin', $flags, true) ? 1 : 0,
    'published_at' => $status === 'published' ? date('Y-m-d H:i:s') : null,
]);

echo ucfirst($status) . ": $title\n";
echo "URL: /post.php?slug=$slug\n";

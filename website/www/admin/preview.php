<?php
/* Live Markdown preview endpoint for the editor. Returns an HTML fragment. */
require __DIR__ . '/../inc/bootstrap.php';
require __DIR__ . '/../inc/news.php';
require __DIR__ . '/../inc/admin_auth.php';

if (!admin_user()) {
    http_response_code(403);
    exit('Sign in to preview.');
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    exit;
}
csrf_check();

header('Content-Type: text/html; charset=UTF-8');
header('X-Content-Type-Options: nosniff');
echo news_render_markdown((string)($_POST['body'] ?? ''));

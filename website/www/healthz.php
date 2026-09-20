<?php
// Container health check: PHP runs and the auth database answers.
require __DIR__ . '/inc/bootstrap.php';

header('Content-Type: text/plain; charset=UTF-8');
header('Cache-Control: no-store');

try {
    $db = neko_db('auth');
    if (!$db) {
        throw new RuntimeException('no auth db');
    }
    $db->query('SELECT 1')->fetchColumn();
    echo "ok\n";
} catch (Throwable $e) {
    http_response_code(503);
    echo "db unavailable\n";
}

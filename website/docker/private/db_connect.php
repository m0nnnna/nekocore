<?php
// Docker: connection settings come from the environment (see docker.env).
$host   = getenv('NEKO_DB_HOST') ?: 'ac-database';
$port   = getenv('NEKO_DB_PORT') ?: '3306';
$dbname = getenv('NEKO_DB_AUTH') ?: 'acore_auth';
$user   = getenv('NEKO_DB_USER') ?: 'root';
$pass   = getenv('NEKO_DB_PASS') ?: '';

try {
    $pdo = new PDO("mysql:host=$host;port=$port;dbname=$dbname;charset=utf8mb4", $user, $pass);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch (PDOException $e) {
    http_response_code(503);
    die("Database connection failed.");
}

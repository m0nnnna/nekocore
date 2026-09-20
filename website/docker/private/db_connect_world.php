<?php
$host   = getenv('NEKO_DB_HOST') ?: 'ac-database';
$port   = getenv('NEKO_DB_PORT') ?: '3306';
$dbname = getenv('NEKO_DB_WORLD') ?: 'acore_world';
$user   = getenv('NEKO_DB_USER') ?: 'root';
$pass   = getenv('NEKO_DB_PASS') ?: '';

try {
    $pdo_world = new PDO("mysql:host=$host;port=$port;dbname=$dbname;charset=utf8mb4", $user, $pass, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
} catch (PDOException $e) {
    $pdo_world = null;
}

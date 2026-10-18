<?php
declare(strict_types=1);

/*
 * Shared site bootstrap. Every public page requires this first.
 *
 * Private config (database credentials, SMTP, SRP6 helpers) lives OUTSIDE the
 * web root in NEKO_PRIVATE, exactly as before. Nothing in this directory
 * contains a secret.
 */

/** Environment override with a default (Docker sets these; Laragon uses the defaults). */
function neko_env(string $name, string $default): string
{
    $v = getenv($name);
    return ($v === false || $v === '') ? $default : $v;
}

define('NEKO_PRIVATE', neko_env('NEKO_PRIVATE_DIR', 'C:\laragon'));

$neko = [
    'site_name'          => 'NekoCore',
    'tagline'            => 'A cozy little Azeroth, nya~',
    // Where the realm status probe connects. In Docker these are the
    // ac-authserver / ac-worldserver service names on the shared network.
    'auth_host'          => neko_env('NEKO_AUTH_HOST', '127.0.0.1'),
    'auth_port'          => (int)neko_env('NEKO_AUTH_PORT', '3724'),
    'world_host'         => neko_env('NEKO_WORLD_HOST', '127.0.0.1'),
    'world_port'         => (int)neko_env('NEKO_WORLD_PORT', '8085'),
    'registrations_open' => neko_env('NEKO_REGISTRATIONS_OPEN', '1') !== '0',
    'discord_url'        => neko_env('NEKO_DISCORD_URL', 'https://discord.gg/W9cMwT4Ar9'),
    'wiki_url'           => neko_env('NEKO_WIKI_URL', 'https://wiki.nekos.farm/en/WoW'),
    // what realmlist.wtf points at -- the patch zip bakes in the same address
    // (tools/install_patch/install_client.py REALM_ADDRESS)
    'realm_address'      => neko_env('NEKO_REALM_ADDRESS', 'wow1.nekos.farm'),
    // NekoCore patch (patch-Z.mpq + addons) players extract over their own 3.3.5a client
    'patch_url'          => neko_env('NEKO_PATCH_URL', 'downloads/nekocore-patch.zip'),
    // NekoCore Launcher (m0nnnna/wotlk-client-tools): installs and updates
    // the patch above, sets the realm, starts the game
    'launcher_url'       => neko_env('NEKO_LAUNCHER_URL',
        'https://github.com/m0nnnna/wotlk-client-tools/releases/latest/download/NekoCoreLauncher.exe'),
];

date_default_timezone_set(neko_env('NEKO_TZ', 'America/Chicago'));
mb_internal_encoding('UTF-8');

/** HTML-escape for output. */
function e($value): string
{
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/** Require a file from the private (non-web) directory. */
function neko_private(string $file): void
{
    require_once NEKO_PRIVATE . DIRECTORY_SEPARATOR . $file;
}

/**
 * The SMTP settings from the private mail_config.php. That file just sets
 * $mail_config, and a require inside neko_private() would leave it in that
 * function's scope -- so it is read here and handed back explicitly.
 */
function neko_mail_config(): array
{
    static $config = null;
    if ($config === null) {
        require NEKO_PRIVATE . DIRECTORY_SEPARATOR . 'mail_config.php';
        $config = $mail_config;
    }
    return $config;
}

/**
 * Lazily open one of the three AzerothCore databases.
 * $which is 'auth', 'chars' or 'world'. Returns null when the connection
 * file is missing or (for world) the connection failed.
 */
function neko_db(string $which): ?PDO
{
    static $cache = [];
    if (array_key_exists($which, $cache)) {
        return $cache[$which];
    }

    $map = [
        'auth'  => ['db_connect.php', 'pdo'],
        'chars' => ['db_connect_chars.php', 'pdo_chars'],
        'world' => ['db_connect_world.php', 'pdo_world'],
    ];
    if (!isset($map[$which])) {
        throw new InvalidArgumentException("Unknown database: $which");
    }
    [$file, $var] = $map[$which];

    $path = NEKO_PRIVATE . DIRECTORY_SEPARATOR . $file;
    if (is_file($path)) {
        include $path; // defines $pdo / $pdo_chars / $pdo_world in this scope
    }
    $db = $$var ?? null;
    if ($db instanceof PDO) {
        // MySQL runs in UTC; make NOW() and DATETIME columns agree with PHP's
        // clock so publish dates and scheduling line up.
        try {
            $db->exec("SET time_zone = " . $db->quote(date('P')));
        } catch (PDOException $e) {
            // Non-fatal: dates may be offset, but the page still works.
        }
    }
    return $cache[$which] = $db;
}

/** Probe both realm ports once per request. */
function neko_realm_status(): array
{
    static $status = null;
    if ($status !== null) {
        return $status;
    }
    global $neko;

    $probe = static function (string $host, int $port): bool {
        $fp = @fsockopen($host, $port, $errno, $errstr, 1);
        if ($fp) {
            fclose($fp);
            return true;
        }
        return false;
    };

    return $status = [
        'auth'  => $probe($neko['auth_host'], $neko['auth_port']),
        'world' => $probe($neko['world_host'], $neko['world_port']),
    ];
}

/** Absolute base URL of the site (scheme + host), for feeds and share links. */
function neko_base_url(): string
{
    $https = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    return ($https ? 'https' : 'http') . '://' . $host;
}

/** "3 days ago" style relative time for a unix timestamp. */
function neko_relative_time(int $ts): string
{
    $diff = time() - $ts;
    if ($diff < 60) return 'just now';
    if ($diff < 3600) { $m = intdiv($diff, 60); return $m . ' minute' . ($m === 1 ? '' : 's') . ' ago'; }
    if ($diff < 86400) { $h = intdiv($diff, 3600); return $h . ' hour' . ($h === 1 ? '' : 's') . ' ago'; }
    if ($diff < 86400 * 14) { $d = intdiv($diff, 86400); return $d . ' day' . ($d === 1 ? '' : 's') . ' ago'; }
    return date('M j, Y', $ts);
}

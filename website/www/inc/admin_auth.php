<?php
declare(strict_types=1);

/*
 * Admin sessions for the news panel.
 *
 * Staff log in with their *game* account. The password is verified against
 * the SRP6 verifier stored in acore_auth.account (the same math the client
 * uses), and the account must hold gmlevel >= ADMIN_MIN_GMLEVEL in
 * account_access. No extra password store to maintain.
 */

const ADMIN_MIN_GMLEVEL = 3;
const ADMIN_SESSION_TTL = 60 * 60 * 8;

function admin_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $https = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => $https,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_name('nekoadmin');
    session_start();

    if (isset($_SESSION['admin']) && (time() - ($_SESSION['admin']['seen'] ?? 0)) > ADMIN_SESSION_TTL) {
        unset($_SESSION['admin']);
    }
    if (isset($_SESSION['admin'])) {
        $_SESSION['admin']['seen'] = time();
    }
}

/** @return array{id:int, username:string, gmlevel:int}|null */
function admin_user(): ?array
{
    admin_session_start();
    return $_SESSION['admin'] ?? null;
}

/** Redirect to the login page unless an admin session is active. */
function admin_require(): array
{
    $user = admin_user();
    if (!$user) {
        $next = $_SERVER['REQUEST_URI'] ?? 'index.php';
        header('Location: login.php?next=' . rawurlencode($next));
        exit;
    }
    return $user;
}

/**
 * Attempt a login. Returns null on success, or an error string.
 */
function admin_login(string $username, string $password): ?string
{
    admin_session_start();

    // Gentle throttle: the delay grows with consecutive failures in this session.
    $fails = (int)($_SESSION['admin_fails'] ?? 0);
    if ($fails > 0) {
        usleep(min(5, $fails) * 400_000);
    }

    $fail = function (string $msg) use (&$fails): string {
        $_SESSION['admin_fails'] = $fails + 1;
        return $msg;
    };

    $username = trim($username);
    if ($username === '' || $password === '' || !preg_match('/^[a-zA-Z0-9]{1,32}$/', $username)) {
        return $fail('Enter your game account username and password.');
    }

    $db = neko_db('auth');
    if (!$db) {
        return 'The account database is not reachable right now.';
    }
    neko_private('srp6.php');

    $stmt = $db->prepare("SELECT id, username, salt, verifier, locked FROM account WHERE username = :u");
    $stmt->execute(['u' => strtoupper($username)]);
    $account = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!$account) {
        return $fail('That username and password don\'t match.');
    }

    try {
        $computed = CalculateSRP6Verifier($account['username'], $password, $account['salt']);
    } catch (Exception $e) {
        return 'Password check unavailable: ' . $e->getMessage();
    }
    if (!hash_equals((string)$account['verifier'], $computed)) {
        return $fail('That username and password don\'t match.');
    }

    $stmt = $db->prepare("SELECT MAX(gmlevel) FROM account_access WHERE id = :id AND (RealmID = -1 OR RealmID = 1)");
    $stmt->execute(['id' => $account['id']]);
    $gmlevel = (int)$stmt->fetchColumn();
    if ($gmlevel < ADMIN_MIN_GMLEVEL) {
        return $fail('This account isn\'t staff. Ask an admin for access.');
    }

    session_regenerate_id(true);
    unset($_SESSION['admin_fails']);
    $_SESSION['admin'] = [
        'id'       => (int)$account['id'],
        'username' => $account['username'],
        'gmlevel'  => $gmlevel,
        'seen'     => time(),
    ];
    $_SESSION['csrf'] = bin2hex(random_bytes(16));
    return null;
}

function admin_logout(): void
{
    admin_session_start();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $p['path'], $p['domain'], $p['secure'], $p['httponly']);
    }
    session_destroy();
}

function csrf_token(): string
{
    admin_session_start();
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    return $_SESSION['csrf'];
}

function csrf_field(): string
{
    return '<input type="hidden" name="csrf" value="' . e(csrf_token()) . '">';
}

/** Abort the request unless the posted CSRF token matches. */
function csrf_check(): void
{
    admin_session_start();
    $sent = $_POST['csrf'] ?? '';
    if (!is_string($sent) || empty($_SESSION['csrf']) || !hash_equals($_SESSION['csrf'], $sent)) {
        http_response_code(400);
        exit('The form expired. Go back, reload the page, and try again.');
    }
}

/** One-shot status message shown after a redirect. */
function admin_flash(?string $msg = null): ?string
{
    admin_session_start();
    if ($msg !== null) {
        $_SESSION['flash'] = $msg;
        return null;
    }
    $out = $_SESSION['flash'] ?? null;
    unset($_SESSION['flash']);
    return $out;
}

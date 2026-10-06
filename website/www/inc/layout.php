<?php
declare(strict_types=1);

/*
 * Page chrome shared by every public page: <head>, site header/nav, footer.
 *
 *   neko_page_start(['title' => 'News', 'active' => 'news']);
 *   ... page body ...
 *   neko_page_end();
 */

function neko_icon(string $name, string $class = 'ico'): string
{
    static $icons = [
        'paw'      => '<ellipse cx="12" cy="16.5" rx="5.5" ry="4.5"/><circle cx="5" cy="10" r="2.2"/><circle cx="9.5" cy="5.5" r="2.1"/><circle cx="14.5" cy="5.5" r="2.1"/><circle cx="19" cy="10" r="2.2"/>',
        'star'     => '<path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5L2.5 9.4l6.6-.9z"/>',
        'pin'      => '<path d="M14.5 3l6.5 6.5-2.2 2.2-.9-.3-4.2 4.2.4 4.3-1.9 1.9L8 17.6 3.5 22 2 20.5 6.4 16l-4.2-4.2 1.9-1.9 4.3.4 4.2-4.2-.3-.9z"/>',
        'rss'      => '<circle cx="5" cy="19" r="2.2"/><path d="M3 10.5a10.5 10.5 0 0 1 10.5 10.5h-3A7.5 7.5 0 0 0 3 13.5zM3 4a17 17 0 0 1 17 17h-3A14 14 0 0 0 3 7z"/>',
        'clock'    => '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2.5a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15zM11 7h2v5.4l3.6 2.1-1 1.7L11 13.6z"/>',
        'chev-l'   => '<path d="M15 4l2 2-6 6 6 6-2 2-8-8z"/>',
        'chev-r'   => '<path d="M9 4l8 8-8 8-2-2 6-6-6-6z"/>',
        'search'   => '<path d="M10 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 2.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM15.5 14l5.5 5.5-1.8 1.8L13.7 15.8z"/>',
        'download' => '<path d="M11 3h2v9.2l3.1-3.1 1.4 1.4L12 16l-5.5-5.5 1.4-1.4 3.1 3.1zM4 17h16v3H4z"/>',
        'discord'  => '<path d="M19.3 5.6A16 16 0 0 0 15.4 4.4l-.5 1a15 15 0 0 0-5.8 0l-.5-1a16 16 0 0 0-3.9 1.2C2.2 9.3 1.5 12.9 1.9 16.5A16 16 0 0 0 6.7 19l1-1.6a10 10 0 0 1-1.6-.8l.4-.3a11.4 11.4 0 0 0 11 0l.4.3-1.6.8 1 1.6a16 16 0 0 0 4.8-2.5c.5-4.2-.7-7.7-3.1-10.9zM8.7 14.3c-1 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2zm6.6 0c-1 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.7 2-1.7 2z"/>',
        'book'     => '<path d="M4 3h7a3 3 0 0 1 2 .8A3 3 0 0 1 15 3h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5.5a1.5 1.5 0 0 0-1.5 1.5h-2A1.5 1.5 0 0 0 9.5 19H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm1 2v12h4.5c.5 0 1 .1 1.5.4V6a1 1 0 0 0-1-1zm8 1v11.4c.5-.3 1-.4 1.5-.4H19V5h-4a1 1 0 0 0-1 1z"/>',
        'shield'   => '<path d="M12 2l8 3v6c0 5.5-3.4 9.4-8 11-4.6-1.6-8-5.5-8-11V5zm0 2.2L6 6.4V11c0 4.2 2.5 7.3 6 8.7 3.5-1.4 6-4.5 6-8.7V6.4z"/>',
        'edit'     => '<path d="M15.6 3.6l4.8 4.8L8.4 20.4H3.6v-4.8zm0 2.8L6 16v2h2l9.6-9.6z"/>',
        'x'        => '<path d="M6.2 4.8L12 10.6l5.8-5.8 1.4 1.4-5.8 5.8 5.8 5.8-1.4 1.4-5.8-5.8-5.8 5.8-1.4-1.4 5.8-5.8-5.8-5.8z"/>',
        'check'    => '<path d="M9.5 16.2L5.3 12l-1.4 1.4 5.6 5.6 12-12-1.4-1.4z"/>',
        'sword'    => '<path d="M20.5 2.1l1.4 1.4-9.9 9.9 1.4 1.4-1.4 1.4-1.4-1.4L7 18.4l1.4 1.4-1.4 1.4-1.4-1.4-1.4 1.4L2.8 20l1.4-1.4-1.4-1.4 1.4-1.4 1.4 1.4 3.6-3.6-1.4-1.4 1.4-1.4 1.4 1.4z"/>',
        'crown'    => '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-1.5 11h-15z"/>',
        'coins'    => '<path d="M9 3c3.9 0 7 1.3 7 3s-3.1 3-7 3-7-1.3-7-3 3.1-3 7-3zM2 9.5c1.5 1.2 4 1.9 7 1.9s5.5-.7 7-1.9V12c0 1.7-3.1 3-7 3s-7-1.3-7-3zm0 5.5c1.5 1.2 4 1.9 7 1.9s5.5-.7 7-1.9v2.5c0 1.7-3.1 3-7 3s-7-1.3-7-3zM17.5 10c2.6.4 4.5 1.5 4.5 2.9v6.1c0 1.7-3.1 3-7 3-.9 0-1.7-.1-2.5-.2 1.9-.5 3.3-1.4 3.3-2.8v-1.4c1.1-.6 1.7-1.3 1.7-2.1z"/>',
    ];
    $body = $icons[$name] ?? $icons['paw'];
    return '<svg class="' . e($class) . '" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">' . $body . '</svg>';
}

/**
 * @param array $opts  title, active (home|news|leaderboard|logs|challenges|rankings|drops|exchange|account),
 *                     description, head (extra HTML for <head>), body_class
 */
function neko_page_start(array $opts = []): void
{
    global $neko;

    $title       = $opts['title'] ?? '';
    $active      = $opts['active'] ?? '';
    $description = $opts['description'] ?? 'NekoCore is a small, cozy private World of Warcraft realm. Solo-friendly raids, custom content and a friendly community.';
    $full_title  = $title ? $title . ' ~ ' . $neko['site_name'] : $neko['site_name'] . ' ~ ' . $neko['tagline'];
    $body_class  = trim('page ' . ($opts['body_class'] ?? ''));
    $base        = $opts['base'] ?? '';   // '../' for pages in a subdirectory
    $GLOBALS['neko_base_path'] = $base;

    $nav = [
        'home'        => ['index.php', 'Home'],
        'news'        => ['news.php', 'News'],
        'leaderboard' => ['lb.php', 'Leaderboard'],
        'logs'        => ['logs.php', 'Logs'],
        'challenges'  => ['challenges.php', 'Challenges'],
        'rankings'    => ['rankings.php', 'Rankings'],
        'drops'       => ['dropsearch.php', 'Drops'],
        'exchange'    => ['exchange.php', 'Exchange'],
    ];
    ?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= e($full_title) ?></title>
    <meta name="description" content="<?= e($description) ?>">
    <meta name="theme-color" content="#11303b">
    <meta property="og:site_name" content="<?= e($neko['site_name']) ?>">
    <meta property="og:title" content="<?= e($full_title) ?>">
    <meta property="og:description" content="<?= e($description) ?>">
    <meta property="og:image" content="<?= e(neko_base_url()) ?>/images/logo3.png">
    <link rel="icon" href="<?= e($base) ?>images/logo3.png" type="image/png">
    <link rel="alternate" type="application/rss+xml" title="<?= e($neko['site_name']) ?> news" href="<?= e($base) ?>feed.php">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,400..800,0..100&family=Alegreya+Sans:ital,wght@0,400;0,500;0,700;1,400;1,500&display=swap">
    <link rel="stylesheet" href="<?= e($base) ?>styles.css?v=7">
    <?= $opts['head'] ?? '' ?>
</head>
<body class="<?= e($body_class) ?>">
<a class="skip-link" href="#main">Skip to content</a>

<header class="site-head">
    <div class="wrap site-head__row">
        <a href="<?= e($base) ?>index.php" class="brand" aria-label="<?= e($neko['site_name']) ?> home">
            <img src="<?= e($base) ?>images/logo3.png" alt="" width="44" height="44">
            <span class="brand__name"><?= e($neko['site_name']) ?></span>
        </a>
        <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">
            <span class="nav-toggle__bar"></span><span class="nav-toggle__bar"></span><span class="nav-toggle__bar"></span>
            <span class="visually-hidden">Menu</span>
        </button>
        <nav id="site-nav" class="site-nav" aria-label="Main">
            <?php foreach ($nav as $key => [$href, $label]): ?>
                <a href="<?= e($base . $href) ?>"<?= $active === $key ? ' aria-current="page"' : '' ?>><?= e($label) ?></a>
            <?php endforeach; ?>
            <a href="<?= e($base) ?>register.php" class="site-nav__cta<?= $active === 'account' ? ' is-active' : '' ?>">Create account</a>
        </nav>
    </div>
</header>

<main id="main" class="wrap site-main">
<?php
}

/** "You need the patch" warning -- on its own in the home hero, and above the buttons elsewhere. */
function neko_patch_warning(string $class = ''): void
{
    ?>
    <div class="alert alert--warn <?= e($class) ?>"><strong>You need the NekoCore patch to play.</strong> A plain 3.3.5a client will connect, but talents, spells and the extra race/class combos are broken without it.</div>
    <?php
}

/** The patch button and server address shared by every page that tells a player how to start. */
function neko_start_playing(bool $with_warning = true): void
{
    global $neko;
    if ($with_warning) {
        neko_patch_warning();
    }
    $line = 'set realmlist ' . $neko['realm_address'];
    ?>
    <ul class="dl">
        <li>
            <a class="btn btn--coral btn--block" href="<?= e($neko['launcher_url']) ?>"><?= neko_icon('download') ?> Get the launcher</a>
            <small>Windows. Point it at your 3.3.5a (enUS) WoW folder and press Play: it installs the patch, keeps it up to date and sets the server address. Windows may warn about an unknown publisher the first time.</small>
        </li>
        <li>
            <a class="btn btn--ghost btn--block" href="<?= e($neko['patch_url']) ?>" download><?= neko_icon('download') ?> Or just the patch</a>
            <small>Extract into your WoW folder, replacing files when asked. Re-download it after every update.</small>
        </li>
    </ul>
    <div class="server-addr">
        <h4 class="server-addr__title">Server address</h4>
        <div class="server-addr__row">
            <code><?= e($line) ?></code>
            <button type="button" class="btn btn--ghost server-addr__copy" data-copy="<?= e($line) ?>">Copy</button>
        </div>
        <small>The patch already writes this to <code>Data/enUS/realmlist.wtf</code>. Still reaching another server? Delete any <code>SET realmList</code> line in <code>WTF/Config.wtf</code>.</small>
    </div>
    <?php
}

function neko_page_end(): void
{
    global $neko;
    $base = $GLOBALS['neko_base_path'] ?? '';
    ?>
</main>

<footer class="site-foot">
    <div class="wrap site-foot__row">
        <div class="site-foot__brand">
            <img src="<?= e($base) ?>images/logo3.png" alt="" width="36" height="36">
            <div>
                <strong><?= e($neko['site_name']) ?></strong>
                <span>Bring a friend and a bag of catnip.</span>
            </div>
        </div>
        <nav class="site-foot__links" aria-label="Footer">
            <a href="<?= e($neko['discord_url']) ?>"><?= neko_icon('discord') ?> Discord</a>
            <a href="<?= e($neko['wiki_url']) ?>"><?= neko_icon('book') ?> Wiki</a>
            <a href="<?= e($base) ?>feed.php"><?= neko_icon('rss') ?> News feed</a>
            <a href="<?= e($base) ?>forgot_password.php"><?= neko_icon('shield') ?> Reset password</a>
        </nav>
    </div>
</footer>

<script>
document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-copy]');
    if (!btn || !navigator.clipboard) return;
    navigator.clipboard.writeText(btn.getAttribute('data-copy')).then(function () {
        btn.textContent = 'Copied';
        setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
    });
});
(function () {
    var toggle = document.querySelector('.nav-toggle');
    var nav = document.getElementById('site-nav');
    if (!toggle || !nav) return;
    toggle.addEventListener('click', function () {
        var open = nav.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
})();
</script>
</body>
</html>
<?php
}

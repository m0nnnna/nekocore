<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/news.php';

$status = neko_realm_status();
$realm_up = $status['auth'] && $status['world'];
$realm_label = $realm_up ? 'Realm online' : (($status['auth'] || $status['world']) ? 'Realm partly up' : 'Realm offline');
$realm_dot = $realm_up ? 'dot--on' : (($status['auth'] || $status['world']) ? 'dot--part' : 'dot--off');

$posts = news_recent(4);
$news_ready = news_table_ready();

$top_chars = [];
$lb_error = null;
$pdo_chars = neko_db('chars');
if ($pdo_chars) {
    try {
        $top_chars = $pdo_chars->query("
            SELECT c.name, c.level, c.totaltime,
                COALESCE((SELECT SUM(CASE it.Quality WHEN 2 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 3 WHEN 5 THEN 4 ELSE 0 END)
                    FROM character_inventory ci JOIN item_instance i ON ci.item = i.guid JOIN acore_world.item_template it ON i.itemEntry = it.entry
                    WHERE ci.guid = c.guid AND ci.bag = 0 AND ci.slot BETWEEN 0 AND 18), 0) AS gear_points,
                COALESCE((SELECT COUNT(*) FROM character_achievement ca WHERE ca.guid = c.guid), 0) AS achievement_points
            FROM characters c
            ORDER BY (c.level + (c.totaltime / 7200.0) + gear_points + achievement_points) DESC
            LIMIT 5
        ")->fetchAll(PDO::FETCH_ASSOC);
    } catch (PDOException $e) {
        $lb_error = 'Leaderboard unavailable right now.';
    }
} else {
    $lb_error = 'Leaderboard unavailable right now.';
}

neko_page_start(['active' => 'home', 'body_class' => 'page--home']);
?>

<section class="hero">
    <div class="hero__copy">
        <p class="hero__realm"><span class="dot <?= $realm_dot ?>"></span> <?= e($realm_label) ?></p>
        <h1><?= e($neko['tagline']) ?></h1>
        <p class="hero__lede">
            NekoCore is a small private Wrath of the Lich King realm run for friends and friends-of-friends.
            Raids tuned so you can clear them solo or with a couple of pals, custom content that keeps growing,
            and nobody yelling in trade chat.
        </p>
        <?php neko_patch_warning('hero__warn'); ?>
    </div>
    <div class="hero__art">
        <img src="images/logo3.png" alt="The NekoCore mascot, a grinning cat-eared girl with coral hair" width="380" height="380">
    </div>
</section>

<div class="home-grid">
    <section class="home-news" aria-labelledby="news-heading">
        <div class="sec-head">
            <h2 id="news-heading">Latest news</h2>
            <a href="news.php">All news <?= neko_icon('chev-r') ?></a>
        </div>

        <?php if (!$news_ready): ?>
            <div class="alert alert--warn">The news table hasn't been created yet. Run <code>news_schema.sql</code> against the auth database, then <code>php import_announcements.php</code> to bring over the old announcements.</div>
        <?php elseif (empty($posts)): ?>
            <div class="empty"><?= neko_icon('paw') ?>Nothing posted yet. Check back soon, nya~</div>
        <?php else: ?>
            <div class="feed">
                <?php foreach ($posts as $post): $ts = news_timestamp($post); ?>
                    <article class="feed__item">
                        <div class="feed__date">
                            <b><?= date('j', $ts) ?></b>
                            <span><?= date('M Y', $ts) ?></span>
                        </div>
                        <div>
                            <h3 class="feed__title"><a href="<?= e(news_url($post)) ?>"><?= e($post['title']) ?></a></h3>
                            <p class="feed__excerpt"><?= e(news_excerpt($post, 200)) ?></p>
                            <div class="feed__meta">
                                <a class="chip chip--<?= e($post['category']) ?>" href="news.php?category=<?= e($post['category']) ?>"><?= e(news_category_label($post['category'])) ?></a>
                                <?php if ($post['pinned']): ?><span><?= neko_icon('pin') ?>Pinned</span><?php endif; ?>
                                <span><?= neko_icon('clock') ?><?= news_reading_time($post['body']) ?> min read</span>
                            </div>
                        </div>
                    </article>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    </section>

    <aside class="home-aside">
        <div class="panel">
            <h3 class="panel__title"><?= neko_icon('shield') ?> Realm status</h3>
            <div class="realm">
                <div class="realm__row">
                    <span class="dot <?= $status['auth'] ? 'dot--on' : 'dot--off' ?>"></span>
                    Login server
                    <span class="<?= $status['auth'] ? 'is-on' : 'is-off' ?>"><?= $status['auth'] ? 'Online' : 'Offline' ?></span>
                </div>
                <div class="realm__row">
                    <span class="dot <?= $status['world'] ? 'dot--on' : 'dot--off' ?>"></span>
                    World server
                    <span class="<?= $status['world'] ? 'is-on' : 'is-off' ?>"><?= $status['world'] ? 'Online' : 'Offline' ?></span>
                </div>
            </div>
            <p class="notice-line">NekoCore is in beta. If something breaks, tell us on <a href="<?= e($neko['discord_url']) ?>">Discord</a>.</p>
        </div>

        <div class="panel panel--ice">
            <h3 class="panel__title"><?= neko_icon('download') ?> Start playing</h3>
            <?php neko_start_playing(false); ?>
            <p class="panel__foot">Need an account? <a href="register.php">Create one</a> · <a href="<?= e($neko['wiki_url']) ?>">Read the wiki</a></p>
        </div>

        <div class="panel">
            <h3 class="panel__title"><?= neko_icon('crown') ?> Top adventurers</h3>
            <?php if ($lb_error): ?>
                <p class="notice-line"><?= e($lb_error) ?></p>
            <?php elseif (empty($top_chars)): ?>
                <p class="notice-line">No characters yet. Be the first name on this list.</p>
            <?php else: ?>
                <ol class="lb-mini">
                    <?php foreach ($top_chars as $row):
                        $total = (int)$row['level'] + $row['totaltime'] / 7200.0 + (float)$row['gear_points'] + (float)$row['achievement_points']; ?>
                        <li>
                            <a href="lb.php?char=<?= rawurlencode($row['name']) ?>"><?= e($row['name']) ?></a>
                            <span class="pts"><?= number_format($total, 1) ?> pts</span>
                        </li>
                    <?php endforeach; ?>
                </ol>
                <p class="panel__foot"><a href="lb.php">Full leaderboard <?= neko_icon('chev-r') ?></a></p>
            <?php endif; ?>
        </div>

        <div class="panel">
            <h3 class="panel__title"><?= neko_icon('star') ?> NekoCore v1 legends</h3>
            <ol class="lb-mini">
                <li>Heil</li>
                <li>Noc</li>
                <li>Wyrd</li>
                <li>Pantsu</li>
                <li>Sieg</li>
            </ol>
            <p class="notice-line">The five who carried the first realm. Never forgotten.</p>
        </div>
    </aside>
</div>

<?php neko_page_end(); ?>

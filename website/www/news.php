<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/news.php';

$categories = news_categories();
$category = isset($_GET['category']) && isset($categories[$_GET['category']]) ? $_GET['category'] : '';
$search   = trim((string)($_GET['q'] ?? ''));
$page     = max(1, (int)($_GET['page'] ?? 1));
$filtered = $category !== '' || $search !== '';

$result = news_fetch_published(['category' => $category, 'search' => $search, 'page' => $page]);
$posts  = $result['items'];
$counts = news_category_counts();
$total_all = array_sum($counts);

// On the unfiltered first page, the top pinned post gets the featured slot.
$featured = null;
if (!$filtered && $result['page'] === 1 && !empty($posts) && $posts[0]['pinned']) {
    $featured = array_shift($posts);
}

/** Build a news.php URL preserving the current filters. */
$link = function (array $override = []) use ($category, $search): string {
    $q = array_filter(array_merge(['category' => $category, 'q' => $search], $override), fn($v) => $v !== '' && $v !== null && $v !== 1);
    return 'news.php' . ($q ? '?' . http_build_query($q) : '');
};

$title = $category !== '' ? $categories[$category]['plural'] : ($search !== '' ? 'Search: ' . $search : 'News');
neko_page_start(['title' => $title, 'active' => 'news', 'description' => 'Patch notes, events and announcements from the NekoCore realm.']);
?>

<div class="page-head">
    <h1>News</h1>
    <p>Patch notes, events, maintenance windows, and whatever else the cats have been up to.</p>
</div>

<?php if (!news_table_ready()): ?>
    <div class="alert alert--warn">The news table hasn't been created yet. Run <code>news_schema.sql</code> against the auth database, then <code>php import_announcements.php</code>.</div>
<?php endif; ?>

<div class="news-tools">
    <ul class="cat-tabs">
        <li><a href="news.php"<?= $category === '' && $search === '' ? ' aria-current="page"' : '' ?>>All <small><?= $total_all ?></small></a></li>
        <?php foreach ($categories as $slug => $cat): ?>
            <li><a href="news.php?category=<?= e($slug) ?>"<?= $category === $slug ? ' aria-current="page"' : '' ?>><?= e($cat['plural']) ?> <small><?= $counts[$slug] ?? 0 ?></small></a></li>
        <?php endforeach; ?>
    </ul>
    <form class="search" method="get" action="news.php" role="search">
        <?php if ($category !== ''): ?><input type="hidden" name="category" value="<?= e($category) ?>"><?php endif; ?>
        <input class="input" type="search" name="q" value="<?= e($search) ?>" placeholder="Search news" aria-label="Search news">
        <button class="btn btn--ice" type="submit" aria-label="Search"><?= neko_icon('search') ?></button>
    </form>
</div>

<?php if ($featured): $ts = news_timestamp($featured); ?>
    <section class="featured" aria-label="Pinned post">
        <div>
            <span class="featured__kicker"><?= neko_icon('pin') ?> Pinned</span>
            <h2><a href="<?= e(news_url($featured)) ?>"><?= e($featured['title']) ?></a></h2>
            <p><?= e(news_excerpt($featured, 260)) ?></p>
            <div class="featured__meta">
                <a class="chip chip--<?= e($featured['category']) ?>" href="news.php?category=<?= e($featured['category']) ?>"><?= e(news_category_label($featured['category'])) ?></a>
                &nbsp; <?= date('F j, Y', $ts) ?> &nbsp;·&nbsp; <?= e($featured['author']) ?>
            </div>
        </div>
        <a class="btn btn--coral" href="<?= e(news_url($featured)) ?>">Read the post</a>
    </section>
<?php endif; ?>

<?php if ($search !== ''): ?>
    <p class="result-note"><?= $result['total'] ?> result<?= $result['total'] === 1 ? '' : 's' ?> for “<?= e($search) ?>”<?= $category !== '' ? ' in ' . e($categories[$category]['plural']) : '' ?>. <a href="<?= e($link(['q' => ''])) ?>">Clear search</a></p>
<?php endif; ?>

<?php if (empty($posts) && !$featured): ?>
    <div class="empty">
        <?= neko_icon('paw') ?>
        <?php if ($filtered): ?>
            Nothing here matches. <a href="news.php">Show all news</a>
        <?php else: ?>
            Nothing posted yet. Check back soon, nya~
        <?php endif; ?>
    </div>
<?php else: ?>
    <div class="feed">
        <?php $month = ''; foreach ($posts as $post): $ts = news_timestamp($post); $m = date('F Y', $ts); ?>
            <?php if ($m !== $month): $month = $m; ?>
                <h2 class="month-rule"><?= e($m) ?></h2>
            <?php endif; ?>
            <article class="feed__item">
                <div class="feed__date">
                    <b><?= date('j', $ts) ?></b>
                    <span><?= date('D', $ts) ?></span>
                </div>
                <div>
                    <h3 class="feed__title"><a href="<?= e(news_url($post)) ?>"><?= e($post['title']) ?></a></h3>
                    <p class="feed__excerpt"><?= e(news_excerpt($post, 220)) ?></p>
                    <div class="feed__meta">
                        <a class="chip chip--<?= e($post['category']) ?>" href="news.php?category=<?= e($post['category']) ?>"><?= e(news_category_label($post['category'])) ?></a>
                        <?php if ($post['pinned']): ?><span><?= neko_icon('pin') ?>Pinned</span><?php endif; ?>
                        <span><?= e($post['author']) ?></span>
                        <span><?= neko_icon('clock') ?><?= news_reading_time($post['body']) ?> min read</span>
                    </div>
                </div>
            </article>
        <?php endforeach; ?>
    </div>

    <?php if ($result['pages'] > 1): $cur = $result['page']; $last = $result['pages']; ?>
        <nav class="pager" aria-label="Pages">
            <?php if ($cur > 1): ?><a href="<?= e($link(['page' => $cur - 1])) ?>" rel="prev"><?= neko_icon('chev-l') ?> Newer</a><?php endif; ?>
            <?php
            $shown = [];
            for ($i = 1; $i <= $last; $i++) {
                if ($i === 1 || $i === $last || abs($i - $cur) <= 2) {
                    $shown[] = $i;
                }
            }
            $prev = 0;
            foreach ($shown as $i) {
                if ($i - $prev > 1) echo '<span class="pager__gap">…</span>';
                if ($i === $cur) echo '<span aria-current="page">' . $i . '</span>';
                else echo '<a href="' . e($link(['page' => $i])) . '">' . $i . '</a>';
                $prev = $i;
            }
            ?>
            <?php if ($cur < $last): ?><a href="<?= e($link(['page' => $cur + 1])) ?>" rel="next">Older <?= neko_icon('chev-r') ?></a><?php endif; ?>
        </nav>
    <?php endif; ?>
<?php endif; ?>

<p class="notice-line" style="margin-top: 36px;">Prefer a feed reader? <a href="feed.php"><?= neko_icon('rss', 'ico') ?> Subscribe via RSS</a>.</p>

<?php neko_page_end(); ?>

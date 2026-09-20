<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/news.php';

$slug = trim((string)($_GET['slug'] ?? ''));
$post = $slug !== '' ? news_fetch_by_slug($slug) : null;

// Staff can preview drafts and scheduled posts via ?preview=1.
$is_preview = false;
if (!$post && $slug !== '' && isset($_GET['preview'])) {
    require __DIR__ . '/inc/admin_auth.php';
    if (admin_user()) {
        $post = news_fetch_by_slug($slug, true);
        $is_preview = (bool)$post;
    }
}

if (!$post) {
    http_response_code(404);
    neko_page_start(['title' => 'Post not found', 'active' => 'news']);
    ?>
    <div class="page-head"><h1>That post wandered off</h1><p>There's no news post at this address. It may have been unpublished or renamed.</p></div>
    <p><a class="btn btn--ice" href="news.php"><?= neko_icon('chev-l') ?> Back to all news</a></p>
    <?php
    neko_page_end();
    exit;
}

$ts = news_timestamp($post);
$neighbors = $is_preview ? ['older' => null, 'newer' => null] : news_neighbors($post);
$related = $is_preview ? [] : news_related($post);
$excerpt = news_excerpt($post, 200);
$canonical = neko_base_url() . '/' . news_url($post);

$head = '<link rel="canonical" href="' . e($canonical) . '">'
      . '<meta property="og:type" content="article">'
      . '<meta property="article:published_time" content="' . e(date('c', $ts)) . '">';

neko_page_start(['title' => $post['title'], 'active' => 'news', 'description' => $excerpt, 'head' => $head]);
?>

<article class="post">
    <header class="post__head">
        <?php if ($is_preview): ?>
            <div class="alert alert--warn">Preview — this post is <?= $post['status'] === 'draft' ? 'a draft' : 'scheduled for ' . e(date('M j, Y g:i a', $ts)) ?> and isn't visible to players. <a href="admin/edit.php?id=<?= (int)$post['id'] ?>">Edit it</a></div>
        <?php endif; ?>
        <a class="chip chip--<?= e($post['category']) ?>" href="news.php?category=<?= e($post['category']) ?>"><?= e(news_category_label($post['category'])) ?></a>
        <h1><?= e($post['title']) ?></h1>
        <div class="post__meta">
            <span><time datetime="<?= e(date('c', $ts)) ?>"><?= date('F j, Y', $ts) ?></time></span>
            <span>by <?= e($post['author']) ?></span>
            <span><?= neko_icon('clock') ?><?= news_reading_time($post['body']) ?> min read</span>
            <?php if ($post['pinned']): ?><span><?= neko_icon('pin') ?>Pinned</span><?php endif; ?>
            <?php if (strtotime($post['updated_at']) - $ts > 3600): ?><span>Updated <?= e(neko_relative_time((int)strtotime($post['updated_at']))) ?></span><?php endif; ?>
        </div>
        <?php if (!empty($post['summary'])): ?>
            <p class="post__summary"><?= e($post['summary']) ?></p>
        <?php endif; ?>
    </header>

    <div class="md">
        <?= news_render_markdown($post['body']) ?>
    </div>

    <?php if ($neighbors['newer'] || $neighbors['older']): ?>
        <nav class="post-nav" aria-label="More posts">
            <?php if ($neighbors['older']): ?>
                <a href="<?= e(news_url($neighbors['older'])) ?>" rel="prev"><small><?= neko_icon('chev-l') ?> Older</small><?= e($neighbors['older']['title']) ?></a>
            <?php endif; ?>
            <?php if ($neighbors['newer']): ?>
                <a class="is-next" href="<?= e(news_url($neighbors['newer'])) ?>" rel="next"><small>Newer <?= neko_icon('chev-r') ?></small><?= e($neighbors['newer']['title']) ?></a>
            <?php endif; ?>
        </nav>
    <?php endif; ?>

    <?php if ($related): ?>
        <section class="related">
            <div class="sec-head"><h2>More <?= e(mb_strtolower(news_categories()[$post['category']]['plural'] ?? 'posts')) ?></h2><a href="news.php?category=<?= e($post['category']) ?>">See all</a></div>
            <ul>
                <?php foreach ($related as $r): ?>
                    <li><a href="<?= e(news_url($r)) ?>"><?= e($r['title']) ?></a><time><?= date('M j, Y', news_timestamp($r)) ?></time></li>
                <?php endforeach; ?>
            </ul>
        </section>
    <?php endif; ?>

    <p class="back-link"><a href="news.php"><?= neko_icon('chev-l') ?> All news</a></p>
</article>

<?php neko_page_end(); ?>

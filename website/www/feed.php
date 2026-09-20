<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/news.php';

header('Content-Type: application/rss+xml; charset=UTF-8');

$base  = neko_base_url();
$posts = news_fetch_published(['per_page' => 20])['items'];
$last  = $posts ? news_timestamp($posts[0]) : time();

$x = fn($s) => htmlspecialchars((string)$s, ENT_XML1 | ENT_QUOTES, 'UTF-8');

// Feed readers need absolute links; the renderer emits site-relative ones.
$absolute = fn(string $html) => preg_replace('#\b(href|src)="(?!https?://|mailto:|\#)/?#i', '$1="' . $base . '/', $html) ?? $html;

echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
    <title><?= $x($neko['site_name']) ?> news</title>
    <link><?= $x($base) ?>/news.php</link>
    <atom:link href="<?= $x($base) ?>/feed.php" rel="self" type="application/rss+xml"/>
    <description>Patch notes, events and announcements from the <?= $x($neko['site_name']) ?> realm.</description>
    <language>en</language>
    <lastBuildDate><?= date(DATE_RSS, $last) ?></lastBuildDate>
    <image>
        <url><?= $x($base) ?>/images/logo3.png</url>
        <title><?= $x($neko['site_name']) ?> news</title>
        <link><?= $x($base) ?>/news.php</link>
    </image>
<?php foreach ($posts as $post): $url = $base . '/' . news_url($post); ?>
    <item>
        <title><?= $x($post['title']) ?></title>
        <link><?= $x($url) ?></link>
        <guid isPermaLink="true"><?= $x($url) ?></guid>
        <pubDate><?= date(DATE_RSS, news_timestamp($post)) ?></pubDate>
        <category><?= $x(news_category_label($post['category'])) ?></category>
        <description><?= $x(news_excerpt($post, 300)) ?></description>
        <content:encoded><![CDATA[<?= str_replace(']]>', ']]]]><![CDATA[>', $absolute(news_render_markdown($post['body']))) ?>]]></content:encoded>
    </item>
<?php endforeach; ?>
</channel>
</rss>

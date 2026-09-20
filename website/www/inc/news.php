<?php
declare(strict_types=1);

/*
 * News repository + Markdown renderer.
 *
 * Posts live in the `web_news` table of the auth database (next to the other
 * web_* tables). See news_schema.sql in the private directory.
 */

const NEWS_PER_PAGE = 10;

function news_categories(): array
{
    return [
        'announcement' => ['label' => 'Announcement', 'plural' => 'Announcements'],
        'patch-notes'  => ['label' => 'Patch notes',  'plural' => 'Patch notes'],
        'event'        => ['label' => 'Event',        'plural' => 'Events'],
        'maintenance'  => ['label' => 'Maintenance',  'plural' => 'Maintenance'],
        'community'    => ['label' => 'Community',    'plural' => 'Community'],
    ];
}

function news_category_label(string $slug): string
{
    return news_categories()[$slug]['label'] ?? ucfirst($slug);
}

function news_db(): ?PDO
{
    return neko_db('auth');
}

/** True when the web_news table exists. Cached per request. */
function news_table_ready(): bool
{
    static $ready = null;
    if ($ready !== null) {
        return $ready;
    }
    $db = news_db();
    if (!$db) {
        return $ready = false;
    }
    try {
        $db->query("SELECT 1 FROM web_news LIMIT 1");
        return $ready = true;
    } catch (PDOException $e) {
        return $ready = false;
    }
}

/* ---------------------------------------------------------------- reads */

/**
 * Published posts, newest first. Pinned posts float to the top of page 1
 * unless a search or category filter is active.
 *
 * @return array{items: array, total: int, pages: int, page: int}
 */
function news_fetch_published(array $opts = []): array
{
    $page     = max(1, (int)($opts['page'] ?? 1));
    $per_page = max(1, (int)($opts['per_page'] ?? NEWS_PER_PAGE));
    $category = $opts['category'] ?? '';
    $search   = trim((string)($opts['search'] ?? ''));

    $empty = ['items' => [], 'total' => 0, 'pages' => 0, 'page' => $page];
    if (!news_table_ready()) {
        return $empty;
    }
    $db = news_db();

    $where  = ["status = 'published'", "published_at <= NOW()"];
    $params = [];
    if ($category !== '' && isset(news_categories()[$category])) {
        $where[]  = "category = :category";
        $params['category'] = $category;
    }
    if ($search !== '') {
        $where[] = "(title LIKE :q OR summary LIKE :q OR body LIKE :q)";
        $params['q'] = '%' . $search . '%';
    }
    $where_sql = implode(' AND ', $where);

    $stmt = $db->prepare("SELECT COUNT(*) FROM web_news WHERE $where_sql");
    $stmt->execute($params);
    $total = (int)$stmt->fetchColumn();
    $pages = (int)ceil($total / $per_page);
    $page  = min($page, max(1, $pages));

    $offset = ($page - 1) * $per_page;
    $stmt = $db->prepare("
        SELECT id, slug, title, category, summary, body, author, pinned, published_at, updated_at
        FROM web_news
        WHERE $where_sql
        ORDER BY pinned DESC, published_at DESC, id DESC
        LIMIT $per_page OFFSET $offset
    ");
    $stmt->execute($params);

    return ['items' => $stmt->fetchAll(PDO::FETCH_ASSOC), 'total' => $total, 'pages' => $pages, 'page' => $page];
}

function news_recent(int $limit = 3): array
{
    return news_fetch_published(['per_page' => $limit])['items'];
}

function news_fetch_by_slug(string $slug, bool $include_unpublished = false): ?array
{
    if (!news_table_ready()) {
        return null;
    }
    $sql = "SELECT * FROM web_news WHERE slug = :slug";
    if (!$include_unpublished) {
        $sql .= " AND status = 'published' AND published_at <= NOW()";
    }
    $stmt = news_db()->prepare($sql);
    $stmt->execute(['slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ?: null;
}

/** The published posts immediately before and after this one. */
function news_neighbors(array $post): array
{
    $db = news_db();
    $older = $newer = null;
    if (news_table_ready()) {
        $stmt = $db->prepare("SELECT slug, title FROM web_news WHERE status='published' AND published_at <= NOW() AND (published_at < :p OR (published_at = :p AND id < :id)) ORDER BY published_at DESC, id DESC LIMIT 1");
        $stmt->execute(['p' => $post['published_at'], 'id' => $post['id']]);
        $older = $stmt->fetch(PDO::FETCH_ASSOC) ?: null;

        $stmt = $db->prepare("SELECT slug, title FROM web_news WHERE status='published' AND published_at <= NOW() AND (published_at > :p OR (published_at = :p AND id > :id)) ORDER BY published_at ASC, id ASC LIMIT 1");
        $stmt->execute(['p' => $post['published_at'], 'id' => $post['id']]);
        $newer = $stmt->fetch(PDO::FETCH_ASSOC) ?: null;
    }
    return ['older' => $older, 'newer' => $newer];
}

function news_related(array $post, int $limit = 3): array
{
    if (!news_table_ready()) {
        return [];
    }
    $stmt = news_db()->prepare("SELECT slug, title, category, published_at FROM web_news WHERE status='published' AND published_at <= NOW() AND category = :c AND id <> :id ORDER BY published_at DESC LIMIT $limit");
    $stmt->execute(['c' => $post['category'], 'id' => $post['id']]);
    return $stmt->fetchAll(PDO::FETCH_ASSOC);
}

/** Post counts per category (published only). */
function news_category_counts(): array
{
    if (!news_table_ready()) {
        return [];
    }
    $rows = news_db()->query("SELECT category, COUNT(*) AS n FROM web_news WHERE status='published' AND published_at <= NOW() GROUP BY category")->fetchAll(PDO::FETCH_KEY_PAIR);
    return array_map('intval', $rows);
}

/* --------------------------------------------------------------- admin */

function news_fetch_all_admin(): array
{
    if (!news_table_ready()) {
        return [];
    }
    return news_db()->query("SELECT id, slug, title, category, status, pinned, author, published_at, updated_at FROM web_news ORDER BY COALESCE(published_at, created_at) DESC, id DESC")->fetchAll(PDO::FETCH_ASSOC);
}

function news_fetch_by_id(int $id): ?array
{
    if (!news_table_ready()) {
        return null;
    }
    $stmt = news_db()->prepare("SELECT * FROM web_news WHERE id = :id");
    $stmt->execute(['id' => $id]);
    return $stmt->fetch(PDO::FETCH_ASSOC) ?: null;
}

/**
 * Insert or update a post. $data keys: id?, slug, title, category, summary,
 * body, author, status, pinned, published_at (Y-m-d H:i:s or null).
 * Returns the post id.
 */
function news_save(array $data): int
{
    $db = news_db();
    $fields = [
        'slug'         => $data['slug'],
        'title'        => $data['title'],
        'category'     => $data['category'],
        'summary'      => $data['summary'] !== '' ? $data['summary'] : null,
        'body'         => $data['body'],
        'author'       => $data['author'],
        'status'       => $data['status'],
        'pinned'       => (int)$data['pinned'],
        'published_at' => $data['published_at'],
    ];

    if (!empty($data['id'])) {
        $set = implode(', ', array_map(fn($k) => "$k = :$k", array_keys($fields)));
        $fields['id'] = (int)$data['id'];
        $db->prepare("UPDATE web_news SET $set WHERE id = :id")->execute($fields);
        return $fields['id'];
    }

    $cols = implode(', ', array_keys($fields));
    $vals = implode(', ', array_map(fn($k) => ":$k", array_keys($fields)));
    $db->prepare("INSERT INTO web_news ($cols) VALUES ($vals)")->execute($fields);
    return (int)$db->lastInsertId();
}

function news_delete(int $id): void
{
    news_db()->prepare("DELETE FROM web_news WHERE id = :id")->execute(['id' => $id]);
}

function news_slug_exists(string $slug, int $ignore_id = 0): bool
{
    $stmt = news_db()->prepare("SELECT COUNT(*) FROM web_news WHERE slug = :slug AND id <> :id");
    $stmt->execute(['slug' => $slug, 'id' => $ignore_id]);
    return (int)$stmt->fetchColumn() > 0;
}

/* ------------------------------------------------------------- helpers */

function news_slugify(string $text): string
{
    $text = mb_strtolower(trim($text));
    $text = preg_replace('/[^\p{L}\p{N}]+/u', '-', $text) ?? '';
    $text = trim($text, '-');
    if ($text === '') {
        $text = 'post';
    }
    return mb_substr($text, 0, 100);
}

function news_url(array $post): string
{
    return 'post.php?slug=' . rawurlencode($post['slug']);
}

function news_timestamp(array $post): int
{
    return $post['published_at'] ? (int)strtotime($post['published_at']) : time();
}

function news_reading_time(string $body): int
{
    $words = str_word_count(strip_tags($body));
    return max(1, (int)round($words / 200));
}

/** Plain-text excerpt: the summary if set, else the first $len chars of the body. */
function news_excerpt(array $post, int $len = 180): string
{
    if (!empty($post['summary'])) {
        return $post['summary'];
    }
    $text = $post['body'];
    $text = preg_replace('/```.*?```/s', '', $text) ?? $text;          // drop code blocks
    $text = preg_replace('/!\[[^\]]*\]\([^)]*\)/', '', $text) ?? $text; // drop images
    $text = preg_replace('/\[([^\]]+)\]\([^)]*\)/', '$1', $text) ?? $text; // keep link text
    $text = preg_replace_callback('/\[item:(\d+)(?:\s+([^\]]+))?\]/', fn($m) => $m[2] ?? ('item #' . $m[1]), $text) ?? $text;
    $text = preg_replace('/^\s*(?:#+|[-*+]|\d+[.)]|>)\s*/m', '', $text) ?? $text; // headings, list markers, quotes
    $text = preg_replace('/[*_`]+/', '', $text) ?? $text;
    $text = preg_replace('/^-{3,}\s*$/m', '', $text) ?? $text;

    // Each line becomes a sentence so headings and bullets read naturally.
    $parts = [];
    foreach (explode("\n", $text) as $line) {
        $line = trim($line);
        if ($line === '') continue;
        $parts[] = preg_match('/[.!?:;,]$/', $line) ? $line : $line . '.';
    }
    $text = implode(' ', $parts);
    $text = preg_replace('/\s+/', ' ', trim($text)) ?? $text;
    if (mb_strlen($text) > $len) {
        $text = mb_substr($text, 0, $len);
        $text = preg_replace('/\s+\S*$/', '', $text) . '…';
    }
    return $text;
}

/* ------------------------------------------------------------ markdown */

/**
 * Render a safe subset of Markdown to HTML. All input is HTML-escaped first,
 * so post bodies can never inject markup; only the constructs below produce
 * tags.
 *
 *   # / ## / ### headings      > blockquote        --- rule
 *   - item / 1. item           ```code fence```    `inline code`
 *   **bold** *italic*          [text](https://…)   ![alt](https://…)
 *   bare https://… links       [item:12345] → drop-search link
 */
function news_render_markdown(string $md): string
{
    $md = str_replace("\r\n", "\n", $md);
    $md = str_replace("\r", "\n", $md);

    // Pull fenced code blocks out first so nothing inside them is processed.
    $fences = [];
    $md = preg_replace_callback('/^```[^\n]*\n(.*?)^```[ \t]*$/ms', function ($m) use (&$fences) {
        $key = "\x1A" . count($fences) . "\x1A";
        $fences[$key] = '<pre class="md-code"><code>' . e(rtrim($m[1], "\n")) . '</code></pre>';
        return $key;
    }, $md) ?? $md;

    $lines = explode("\n", $md);
    $html = '';
    $para = [];
    $list = null;   // 'ul' | 'ol'
    $quote = [];

    $flush_para = function () use (&$para, &$html) {
        if ($para) {
            $html .= '<p>' . news_inline(implode("\n", $para)) . '</p>' . "\n";
            $para = [];
        }
    };
    $flush_list = function () use (&$list, &$html) {
        if ($list) {
            $html .= "</$list>\n";
            $list = null;
        }
    };
    $flush_quote = function () use (&$quote, &$html) {
        if ($quote) {
            $html .= '<blockquote>' . news_render_markdown(implode("\n", $quote)) . "</blockquote>\n";
            $quote = [];
        }
    };

    foreach ($lines as $line) {
        // Placeholder for a fenced block
        if (preg_match('/^\x1A\d+\x1A$/', trim($line))) {
            $flush_para(); $flush_list(); $flush_quote();
            $html .= $fences[trim($line)] . "\n";
            continue;
        }

        if (preg_match('/^>\s?(.*)$/', $line, $m)) {
            $flush_para(); $flush_list();
            $quote[] = $m[1];
            continue;
        }
        $flush_quote();

        if (trim($line) === '') {
            $flush_para(); $flush_list();
            continue;
        }

        if (preg_match('/^(#{1,3})\s+(.+?)\s*#*$/', $line, $m)) {
            $flush_para(); $flush_list();
            $level = strlen($m[1]) + 1; // # becomes h2: the post title owns h1
            $html .= "<h$level>" . news_inline($m[2]) . "</h$level>\n";
            continue;
        }

        if (preg_match('/^(-{3,}|\*{3,})\s*$/', $line)) {
            $flush_para(); $flush_list();
            $html .= "<hr>\n";
            continue;
        }

        if (preg_match('/^\s*[-*+]\s+(.+)$/', $line, $m)) {
            $flush_para();
            if ($list !== 'ul') { $flush_list(); $html .= "<ul>\n"; $list = 'ul'; }
            $html .= '<li>' . news_inline($m[1]) . "</li>\n";
            continue;
        }
        if (preg_match('/^\s*\d+[.)]\s+(.+)$/', $line, $m)) {
            $flush_para();
            if ($list !== 'ol') { $flush_list(); $html .= "<ol>\n"; $list = 'ol'; }
            $html .= '<li>' . news_inline($m[1]) . "</li>\n";
            continue;
        }

        $flush_list();
        $para[] = $line;
    }
    $flush_para(); $flush_list(); $flush_quote();

    return $html;
}

/** Inline Markdown on an already-plain-text string. */
function news_inline(string $text): string
{
    $out = e($text);

    // Protect inline code from further processing.
    $codes = [];
    $out = preg_replace_callback('/`([^`\n]+)`/', function ($m) use (&$codes) {
        $key = "\x1B" . count($codes) . "\x1B";
        $codes[$key] = '<code>' . $m[1] . '</code>';
        return $key;
    }, $out) ?? $out;

    $safe_url = static function (string $url): ?string {
        $url = html_entity_decode($url, ENT_QUOTES, 'UTF-8');
        if (preg_match('#^(https?://|mailto:|/|[a-z0-9_-]+\.php)#i', $url)) {
            return e($url);
        }
        return null;
    };

    // Images: ![alt](url)
    $out = preg_replace_callback('/!\[([^\]]*)\]\(([^)\s]+)\)/', function ($m) use ($safe_url) {
        $url = $safe_url($m[2]);
        return $url ? '<img src="' . $url . '" alt="' . $m[1] . '" loading="lazy">' : $m[0];
    }, $out) ?? $out;

    // Item shortcode: [item:12345] or [item:12345 Thunderfury]
    $out = preg_replace_callback('/\[item:(\d+)(?:\s+([^\]]+))?\]/', function ($m) {
        $label = isset($m[2]) && $m[2] !== '' ? $m[2] : 'item #' . $m[1];
        return '<a class="md-item" href="dropsearch.php?item=' . $m[1] . '">' . $label . '</a>';
    }, $out) ?? $out;

    // Links: [text](url)
    $out = preg_replace_callback('/\[([^\]]+)\]\(([^)\s]+)\)/', function ($m) use ($safe_url) {
        $url = $safe_url($m[2]);
        if (!$url) {
            return $m[0];
        }
        $ext = preg_match('#^https?://#i', $url) ? ' rel="noopener"' : '';
        return '<a href="' . $url . '"' . $ext . '>' . $m[1] . '</a>';
    }, $out) ?? $out;

    // Bare URLs (not already inside an href / tag)
    $out = preg_replace_callback('#(?<![="\'>])\bhttps?://[^\s<]+#i', function ($m) {
        $url = rtrim($m[0], '.,;:!?)');
        $trail = substr($m[0], strlen($url));
        return '<a href="' . $url . '" rel="noopener">' . $url . '</a>' . $trail;
    }, $out) ?? $out;

    $out = preg_replace('/\*\*(.+?)\*\*/s', '<strong>$1</strong>', $out) ?? $out;
    $out = preg_replace('/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/s', '<em>$1</em>', $out) ?? $out;
    $out = preg_replace('/(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)/s', '<em>$1</em>', $out) ?? $out;

    $out = nl2br($out, false);

    return strtr($out, $codes);
}

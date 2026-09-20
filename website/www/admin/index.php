<?php
require __DIR__ . '/../inc/bootstrap.php';
require __DIR__ . '/../inc/layout.php';
require __DIR__ . '/../inc/news.php';
require __DIR__ . '/../inc/admin_auth.php';

$admin = admin_require();

// Quick actions from the list: pin / unpin, publish now.
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_check();
    $id = (int)($_POST['id'] ?? 0);
    $post = $id ? news_fetch_by_id($id) : null;
    if ($post) {
        $action = $_POST['action'] ?? '';
        if ($action === 'pin') {
            news_db()->prepare("UPDATE web_news SET pinned = 1 - pinned WHERE id = :id")->execute(['id' => $id]);
            admin_flash($post['pinned'] ? 'Unpinned “' . $post['title'] . '”.' : 'Pinned “' . $post['title'] . '”.');
        } elseif ($action === 'publish') {
            // A scheduled post already has a (future) published_at -- "now" has
            // to win over it, or the post stays hidden until its old date.
            news_db()->prepare("UPDATE web_news SET status = 'published', published_at = IF(published_at IS NULL OR published_at > NOW(), NOW(), published_at) WHERE id = :id")->execute(['id' => $id]);
            admin_flash('Published “' . $post['title'] . '”.');
        } elseif ($action === 'unpublish') {
            news_db()->prepare("UPDATE web_news SET status = 'draft' WHERE id = :id")->execute(['id' => $id]);
            admin_flash('Moved “' . $post['title'] . '” back to drafts.');
        }
    }
    header('Location: index.php');
    exit;
}

$posts = news_fetch_all_admin();
$now = time();

$state = function (array $p) use ($now): array {
    if ($p['status'] !== 'published') return ['draft', 'Draft'];
    if ($p['published_at'] && strtotime($p['published_at']) > $now) return ['scheduled', 'Scheduled'];
    return ['published', 'Published'];
};

neko_page_start(['title' => 'News admin', 'base' => '../', 'active' => 'news']);
require __DIR__ . '/_bar.php';
?>

<div class="sec-head">
    <h2>News posts</h2>
    <a class="btn btn--coral btn--sm" href="edit.php"><?= neko_icon('edit') ?> New post</a>
</div>

<?php if (!news_table_ready()): ?>
    <div class="alert alert--warn">The <code>web_news</code> table doesn't exist yet. Run <code>news_schema.sql</code> against the auth database first.</div>
<?php elseif (empty($posts)): ?>
    <div class="empty"><?= neko_icon('paw') ?>No posts yet. <a href="edit.php">Write the first one</a>.</div>
<?php else: ?>
    <div class="tbl-wrap">
        <table class="tbl">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Category</th>
                    <th>State</th>
                    <th>Date</th>
                    <th class="actions"></th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($posts as $p): [$sk, $sl] = $state($p); ?>
                    <tr>
                        <td>
                            <?php if ($p['pinned']): ?><span title="Pinned" style="color: var(--coral);"><?= neko_icon('pin') ?></span> <?php endif; ?>
                            <a href="edit.php?id=<?= (int)$p['id'] ?>"><?= e($p['title']) ?></a>
                            <br><small style="color: var(--cream-dim);">/<?= e($p['slug']) ?> · <?= e($p['author']) ?></small>
                        </td>
                        <td><span class="chip chip--<?= e($p['category']) ?>"><?= e(news_category_label($p['category'])) ?></span></td>
                        <td><span class="chip chip--<?= $sk ?>"><?= $sl ?></span></td>
                        <td style="white-space: nowrap;"><?= $p['published_at'] ? date('M j, Y g:i a', strtotime($p['published_at'])) : '—' ?></td>
                        <td class="actions">
                            <a href="../post.php?slug=<?= rawurlencode($p['slug']) ?><?= $sk !== 'published' ? '&preview=1' : '' ?>">View</a>
                            <form method="POST" style="display: inline;"><?= csrf_field() ?><input type="hidden" name="id" value="<?= (int)$p['id'] ?>">
                                <?php if ($sk === 'published'): ?>
                                    <button class="btn btn--ghost btn--sm" name="action" value="pin" type="submit"><?= $p['pinned'] ? 'Unpin' : 'Pin' ?></button>
                                    <button class="btn btn--ghost btn--sm" name="action" value="unpublish" type="submit">Unpublish</button>
                                <?php else: ?>
                                    <button class="btn btn--ice btn--sm" name="action" value="publish" type="submit">Publish now</button>
                                <?php endif; ?>
                            </form>
                        </td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
<?php endif; ?>

<?php neko_page_end(); ?>

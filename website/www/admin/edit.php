<?php
require __DIR__ . '/../inc/bootstrap.php';
require __DIR__ . '/../inc/layout.php';
require __DIR__ . '/../inc/news.php';
require __DIR__ . '/../inc/admin_auth.php';

$admin = admin_require();
$categories = news_categories();

$id = (int)($_GET['id'] ?? $_POST['id'] ?? 0);
$post = $id ? news_fetch_by_id($id) : null;
if ($id && !$post) {
    admin_flash('That post no longer exists.');
    header('Location: index.php');
    exit;
}

$errors = [];
$form = [
    'title'        => $post['title'] ?? '',
    'slug'         => $post['slug'] ?? '',
    'category'     => $post['category'] ?? 'announcement',
    'summary'      => $post['summary'] ?? '',
    'body'         => $post['body'] ?? '',
    'author'       => $post['author'] ?? ucfirst(strtolower($admin['username'])),
    'status'       => $post['status'] ?? 'draft',
    'pinned'       => (int)($post['pinned'] ?? 0),
    'published_at' => !empty($post['published_at']) ? date('Y-m-d\TH:i', strtotime($post['published_at'])) : '',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_check();
    $action = $_POST['action'] ?? 'save';

    if ($action === 'delete' && $post) {
        news_delete($post['id']);
        admin_flash('Deleted “' . $post['title'] . '”.');
        header('Location: index.php');
        exit;
    }

    foreach (['title', 'slug', 'category', 'summary', 'body', 'author', 'status', 'published_at'] as $k) {
        $form[$k] = trim((string)($_POST[$k] ?? ''));
    }
    $form['pinned'] = isset($_POST['pinned']) ? 1 : 0;
    if ($action === 'publish_now') {
        // Ignore whatever date is in the form -- the post goes live this minute.
        $form['status'] = 'published';
        $form['published_at'] = '';
    } elseif ($action === 'publish') {
        $form['status'] = 'published';
    } elseif ($action === 'draft') {
        $form['status'] = 'draft';
    }

    if ($form['title'] === '' || mb_strlen($form['title']) > 200) {
        $errors[] = 'Give the post a title (up to 200 characters).';
    }
    if ($form['body'] === '') {
        $errors[] = 'The post needs a body.';
    }
    if (!isset($categories[$form['category']])) {
        $errors[] = 'Pick a category.';
    }
    if (mb_strlen($form['summary']) > 500) {
        $errors[] = 'Keep the summary under 500 characters.';
    }
    if ($form['author'] === '' || mb_strlen($form['author']) > 32) {
        $form['author'] = ucfirst(strtolower($admin['username']));
    }
    if (!in_array($form['status'], ['draft', 'published'], true)) {
        $form['status'] = 'draft';
    }

    $form['slug'] = news_slugify($form['slug'] !== '' ? $form['slug'] : $form['title']);
    if (news_table_ready() && news_slug_exists($form['slug'], $post['id'] ?? 0)) {
        $errors[] = 'Another post already uses the address /' . $form['slug'] . '. Change the slug.';
    }

    $published_at = null;
    if ($form['published_at'] !== '') {
        $t = strtotime($form['published_at']);
        if ($t === false) {
            $errors[] = 'The publish date isn\'t a valid date.';
        } else {
            $published_at = date('Y-m-d H:i:s', $t);
        }
    } elseif ($form['status'] === 'published') {
        $published_at = date('Y-m-d H:i:s');
        $form['published_at'] = date('Y-m-d\TH:i');
    }

    if (empty($errors)) {
        $saved_id = news_save([
            'id'           => $post['id'] ?? 0,
            'slug'         => $form['slug'],
            'title'        => $form['title'],
            'category'     => $form['category'],
            'summary'      => $form['summary'],
            'body'         => $form['body'],
            'author'       => $form['author'],
            'status'       => $form['status'],
            'pinned'       => $form['pinned'],
            'published_at' => $published_at,
        ]);

        if ($form['status'] === 'published' && strtotime($published_at) > time()) {
            admin_flash('Scheduled “' . $form['title'] . '” for ' . date('M j, Y g:i a', strtotime($published_at)) . '.');
        } elseif ($form['status'] === 'published') {
            admin_flash('Published “' . $form['title'] . '”.');
        } else {
            admin_flash('Saved “' . $form['title'] . '” as a draft.');
        }
        header('Location: edit.php?id=' . $saved_id);
        exit;
    }
}

$confirm_delete = $post && isset($_GET['delete']);

neko_page_start(['title' => $post ? 'Edit: ' . $post['title'] : 'New post', 'base' => '../', 'active' => 'news']);
require __DIR__ . '/_bar.php';
?>

<div class="sec-head">
    <h2><?= $post ? 'Edit post' : 'New post' ?></h2>
    <?php if ($post): ?>
        <a href="../post.php?slug=<?= rawurlencode($post['slug']) ?>&preview=1">View post <?= neko_icon('chev-r') ?></a>
    <?php endif; ?>
</div>

<?php if (!empty($errors)): ?>
    <div class="alert alert--error"><ul><?php foreach ($errors as $err): ?><li><?= e($err) ?></li><?php endforeach; ?></ul></div>
<?php endif; ?>

<?php if ($confirm_delete): ?>
    <div class="alert alert--warn">
        <p>Delete “<?= e($post['title']) ?>” for good? This can't be undone.</p>
        <form method="POST" class="form-actions" style="margin-top: 10px;">
            <?= csrf_field() ?>
            <input type="hidden" name="id" value="<?= (int)$post['id'] ?>">
            <button class="btn btn--danger btn--sm" name="action" value="delete" type="submit">Yes, delete it</button>
            <a class="btn btn--ghost btn--sm" href="edit.php?id=<?= (int)$post['id'] ?>">Keep it</a>
        </form>
    </div>
<?php endif; ?>

<form method="POST" id="post-form">
    <?= csrf_field() ?>
    <?php if ($post): ?><input type="hidden" name="id" value="<?= (int)$post['id'] ?>"><?php endif; ?>

    <div class="editor">
        <div>
            <div class="field">
                <label for="title">Title</label>
                <input class="input" type="text" id="title" name="title" required maxlength="200" value="<?= e($form['title']) ?>" placeholder="Patch 1.4: Karazhan opens its doors">
            </div>
            <div class="form-row">
                <div class="field">
                    <label for="slug">Address (slug)</label>
                    <input class="input" type="text" id="slug" name="slug" maxlength="100" value="<?= e($form['slug']) ?>" placeholder="auto from title">
                    <span class="help">post.php?slug=<span id="slug-preview"><?= e($form['slug'] ?: '…') ?></span></span>
                </div>
                <div class="field">
                    <label for="category">Category</label>
                    <select class="select" id="category" name="category">
                        <?php foreach ($categories as $slug => $cat): ?>
                            <option value="<?= e($slug) ?>"<?= $form['category'] === $slug ? ' selected' : '' ?>><?= e($cat['label']) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
            </div>
            <div class="field">
                <label for="summary">Summary <small style="font-weight: 400; color: var(--cream-dim);">(optional)</small></label>
                <input class="input" type="text" id="summary" name="summary" maxlength="500" value="<?= e($form['summary']) ?>" placeholder="One or two sentences shown in the feed and RSS">
                <span class="help">Leave blank to use the first lines of the body.</span>
            </div>
            <div class="field">
                <label for="body">Body</label>
                <textarea class="textarea" id="body" name="body" required placeholder="Write in Markdown…"><?= e($form['body']) ?></textarea>
                <p class="md-help">
                    <code># Heading</code> &nbsp; <code>**bold**</code> &nbsp; <code>*italic*</code> &nbsp; <code>- list</code> &nbsp; <code>1. steps</code> &nbsp; <code>&gt; quote</code> &nbsp; <code>[text](https://…)</code> &nbsp; <code>![alt](https://…)</code> &nbsp; <code>```code```</code> &nbsp; <code>[item:19019 Thunderfury]</code> links to drop search
                </p>
            </div>
            <div class="form-row">
                <div class="field">
                    <label for="author">Author</label>
                    <input class="input" type="text" id="author" name="author" maxlength="32" value="<?= e($form['author']) ?>">
                </div>
                <div class="field">
                    <label for="published_at">Publish date</label>
                    <input class="input" type="datetime-local" id="published_at" name="published_at" value="<?= e($form['published_at']) ?>">
                    <span class="help">Set a future date to schedule. Blank = now, when published.</span>
                </div>
            </div>
            <div class="field">
                <label class="check"><input type="checkbox" name="pinned" value="1"<?= $form['pinned'] ? ' checked' : '' ?>> Pin to the top of the news page</label>
            </div>

            <div class="form-actions">
                <button class="btn btn--coral" type="submit" name="action" value="publish"><?= neko_icon('check') ?> <?= $form['status'] === 'published' ? 'Save changes' : 'Publish' ?></button>
                <?php if ($form['published_at'] !== '' && strtotime($form['published_at']) > time()): ?>
                    <button class="btn btn--ice" type="submit" name="action" value="publish_now">Publish now</button>
                <?php endif; ?>
                <button class="btn btn--ghost" type="submit" name="action" value="draft"><?= $form['status'] === 'published' ? 'Unpublish to draft' : 'Save draft' ?></button>
                <span class="spacer"></span>
                <?php if ($post && !$confirm_delete): ?>
                    <a class="btn btn--danger btn--sm" href="edit.php?id=<?= (int)$post['id'] ?>&delete=1">Delete</a>
                <?php endif; ?>
            </div>
        </div>

        <aside class="editor__preview" aria-live="polite">
            <div class="editor__preview-label"><span>Preview</span><span id="preview-stats"></span></div>
            <h1 id="preview-title" style="font-size: 1.8rem;"><?= e($form['title'] ?: 'Untitled post') ?></h1>
            <div class="md" id="preview-body"><?= news_render_markdown($form['body']) ?></div>
        </aside>
    </div>
</form>

<script>
(function () {
    var title = document.getElementById('title');
    var slug = document.getElementById('slug');
    var slugPreview = document.getElementById('slug-preview');
    var body = document.getElementById('body');
    var previewTitle = document.getElementById('preview-title');
    var previewBody = document.getElementById('preview-body');
    var stats = document.getElementById('preview-stats');
    var csrf = document.querySelector('#post-form input[name=csrf]').value;
    var slugTouched = slug.value !== '';

    function slugify(s) {
        return s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').slice(0, 100);
    }
    title.addEventListener('input', function () {
        previewTitle.textContent = title.value || 'Untitled post';
        if (!slugTouched) {
            slug.value = slugify(title.value);
            slugPreview.textContent = slug.value || '…';
        }
    });
    slug.addEventListener('input', function () {
        slugTouched = slug.value !== '';
        slugPreview.textContent = slug.value || slugify(title.value) || '…';
    });

    var timer = null;
    function render() {
        var words = body.value.trim().split(/\s+/).filter(Boolean).length;
        stats.textContent = words + ' words · ' + Math.max(1, Math.round(words / 200)) + ' min read';
        var fd = new FormData();
        fd.append('csrf', csrf);
        fd.append('body', body.value);
        fetch('preview.php', { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
            .then(function (html) { previewBody.innerHTML = html; })
            .catch(function () { stats.textContent = 'Preview unavailable'; });
    }
    body.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(render, 350);
    });
    render();

    // Ctrl/Cmd+S saves without leaving the editor.
    document.addEventListener('keydown', function (ev) {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') {
            ev.preventDefault();
            var btn = document.querySelector('#post-form button[value=<?= $form['status'] === 'published' ? 'publish' : 'draft' ?>]');
            if (btn) btn.click();
        }
    });
})();
</script>

<?php neko_page_end(); ?>

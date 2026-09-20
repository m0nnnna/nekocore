<?php
require __DIR__ . '/inc/bootstrap.php';
require __DIR__ . '/inc/layout.php';
require __DIR__ . '/inc/logs.php';

$db = neko_db('chars');
$error = $db ? null : 'The character database is not reachable right now.';

$runId = (int)($_GET['id'] ?? 0);
$encId = (int)($_GET['enc'] ?? 0);
$view = in_array($_GET['view'] ?? '', ['damage', 'healing', 'taken', 'deaths'], true) ? $_GET['view'] : 'damage';

$run = null; $encounters = []; $enc = null; $actors = []; $names = [];
$rows = []; $deaths = []; $participants = []; $elig = null;

if (!$error) {
    try {
        $run = $runId ? nl_run($db, $runId) : null;
        if ($run) {
            $encounters = nl_encounters($db, $runId);
            $actors = nl_actors($db, $runId);
            if ($encId) {
                foreach ($encounters as $e) if ((int)$e['id'] === $encId) $enc = $e;
            } elseif ($encounters) {
                $enc = end($encounters);
            }
            if ($enc) {
                if (($_GET['export'] ?? '') === 'csv') {
                    nl_export_csv($db, $run, $enc, $actors);
                }
                $participants = nl_participants($db, (int)$enc['id']);
                if ((int)$enc['result'] === 1) { nl_refresh_ranks($db); $elig = nl_kill_eligibility($db, (int)$enc['id']); }
                switch ($view) {
                    case 'healing':
                        $rows = nl_fold_to_players(nl_breakdown($db, (int)$enc['id'], NL_HEAL, 'src'), $actors);
                        break;
                    case 'taken':
                        $rows = nl_fold_to_players(nl_breakdown($db, (int)$enc['id'], NL_DAMAGE, 'dst'), $actors);
                        break;
                    case 'deaths':
                        $deaths = nl_deaths($db, (int)$enc['id']);
                        break;
                    default:
                        $rows = nl_fold_to_players(nl_breakdown($db, (int)$enc['id'], NL_DAMAGE, 'src'), $actors);
                }
                $ids = [];
                foreach ($rows as $r) foreach ($r['spells'] as $s) $ids[] = $s['spell'];
                $names = nl_spell_names($db, $ids);
            }
        }
    } catch (PDOException $e) {
        $error = 'Database error: ' . $e->getMessage();
    }
}

if (!$error && !$run) {
    http_response_code(404);
    $error = 'No such log.';
}

$encDurationMs = $enc ? max(1, ((int)$enc['end_ms'] ?: (int)$enc['start_ms']) - (int)$enc['start_ms']) : 0;
$grand = array_sum(array_column($rows, 'total')) ?: 1;
$top = $rows ? max(array_column($rows, 'total')) : 1;
$title = $run ? ($enc ? $enc['boss_name'] . ' ~ ' : '') . $run['map_name'] : 'Log';
$kindForNames = $view === 'healing' ? NL_HEAL : NL_DAMAGE;
$rateLabel = $view === 'healing' ? 'HPS' : ($view === 'taken' ? 'DTPS' : 'DPS');
$extraLabel = $view === 'healing' ? 'Overheal' : 'Mitigated';

neko_page_start(['title' => $title, 'active' => 'logs']);
?>

<?php if ($error): ?>
    <div class="empty"><?= neko_icon('paw') ?><?= e($error) ?></div>
    <p class="back-link"><a href="logs.php">&larr; All logs</a></p>
<?php else: ?>

<div class="page-head nl-head">
    <div>
        <p class="nl-crumb"><a href="logs.php">Logs</a> / <a href="logs.php?map=<?= (int)$run['map_id'] ?>"><?= e($run['map_name']) ?></a></p>
        <h1><?= e($run['map_name']) ?> <span class="nl-sub"><?= e(nl_difficulty($run)) ?></span></h1>
        <p><?= e(date('l, F j, Y \a\t H:i', (int)$run['started_at'])) ?>
           &middot; <?= (int)$run['kills'] ?> boss<?= (int)$run['kills'] === 1 ? '' : 'es' ?> down, <?= (int)$run['wipes'] ?> wipe<?= (int)$run['wipes'] === 1 ? '' : 's' ?>
           <?= (int)$run['ended_at'] ? '&middot; ' . e(nl_duration(((int)$run['ended_at'] - (int)$run['started_at']) * 1000)) . ' from first pull to instance reset' : '&middot; <span class="nl-live">still live</span>' ?></p>
    </div>
</div>

<div class="cols nl-cols">
    <div>
    <?php if (!$enc): ?>
        <div class="empty"><?= neko_icon('paw') ?>No boss was pulled in this run (yet).</div>
    <?php else: ?>
        <div class="sec-head">
            <h2><?= e($enc['boss_name']) ?>
                <span class="nl-result <?= e(nl_result_class((int)$enc['result'])) ?>"><?= e(nl_result_label((int)$enc['result'])) ?></span></h2>
            <a class="btn btn--ghost btn--sm" href="log.php?id=<?= (int)$run['id'] ?>&amp;enc=<?= (int)$enc['id'] ?>&amp;export=csv">Export CSV</a>
        </div>
        <p class="notice-line">
            <?= e(nl_duration($encDurationMs)) ?> &middot; <?= (int)$enc['players'] ?> player<?= (int)$enc['players'] === 1 ? '' : 's' ?>
            &middot; <?= e(nl_era_name((int)$enc['min_era'])) ?><?= nl_era_name((int)$enc['min_era']) !== nl_era_name((int)$enc['max_era']) ? '&ndash;' . e(nl_era_name((int)$enc['max_era'])) : '' ?> era
            <?php if ($elig && !(int)$elig['eligible']): ?>
                &middot; <span class="nl-result is-wipe" title="Highest level in the group was <?= (int)$elig['max_level'] ?>; the boss is level <?= (int)$elig['boss_level'] ?> (limit +<?= NL_LEVEL_TOLERANCE ?>)">Over-level &middot; not ranked</span>
            <?php elseif ($elig): ?>
                &middot; <a class="nl-result is-kill" href="rankings.php?<?= http_build_query(['map' => $run['map_id'], 'boss' => $enc['boss_entry']]) ?>">Ranked</a>
            <?php endif; ?>
        </p>

        <nav class="nl-tabs" aria-label="Breakdown">
            <?php foreach (['damage' => 'Damage done', 'healing' => 'Healing done', 'taken' => 'Damage taken', 'deaths' => 'Deaths'] as $k => $label): ?>
                <a href="log.php?<?= http_build_query(['id' => $run['id'], 'enc' => $enc['id'], 'view' => $k]) ?>"<?= $view === $k ? ' aria-current="page"' : '' ?>><?= e($label) ?></a>
            <?php endforeach; ?>
        </nav>

        <?php if ($view === 'deaths'): ?>
            <?php if (!$deaths): ?>
                <div class="empty"><?= neko_icon('paw') ?>Nobody died. Suspiciously clean.</div>
            <?php else: ?>
            <div class="tbl-wrap"><table class="tbl">
                <thead><tr><th>Time</th><th>Who</th><th>Killed by</th></tr></thead>
                <tbody>
                <?php foreach ($deaths as $d): ?>
                    <tr>
                        <td><?= e(nl_duration((int)$d['t_ms'] - (int)$enc['start_ms'])) ?></td>
                        <td><?= nl_actor_html($actors, $d['dst']) ?></td>
                        <td><?= $d['src'] ? nl_actor_html($actors, $d['src']) : '<span class="nl-unknown">&mdash;</span>' ?></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table></div>
            <?php endif; ?>
        <?php else: ?>
            <?php if (!$rows): ?>
                <div class="empty"><?= neko_icon('paw') ?>Nothing recorded for this view.</div>
            <?php else: ?>
            <div class="tbl-wrap"><table class="tbl nl-meter">
                <thead><tr><th>#</th><th>Player</th><th>Amount</th><th class="num"><?= e($rateLabel) ?></th><th class="num"><?= e($extraLabel) ?></th></tr></thead>
                <tbody>
                <?php $i = 0; foreach ($rows as $guid => $r): $i++;
                    $actor = $actors[$guid] ?? null;
                    $color = $actor ? nl_class_color((int)$actor['class']) : 'var(--teal)';
                    $pct = $r['total'] / $top * 100;
                    uasort($r['spells'], fn($a, $b) => $b['total'] <=> $a['total']);
                ?>
                    <tr class="nl-row" data-toggle="d<?= $i ?>" tabindex="0">
                        <td class="nl-rank"><?= $i ?></td>
                        <td>
                            <?= nl_actor_html($actors, $guid) ?>
                            <span class="nl-sub"><?= $actor ? e(trim(nl_spec_name((int)$actor['class'], (int)$actor['spec']) . ' ' . nl_class_name((int)$actor['class']))) : '' ?></span>
                        </td>
                        <td class="nl-barcell">
                            <div class="nl-bar" style="--w:<?= round($pct, 1) ?>%;--c:<?= $color ?>"><span><?= e(nl_num($r['total'])) ?> <em><?= number_format($r['total'] / $grand * 100, 1) ?>%</em></span></div>
                        </td>
                        <td class="num"><?= e(nl_num($r['total'] / ($encDurationMs / 1000))) ?></td>
                        <td class="num"><?= e(nl_num($r['extra'])) ?></td>
                    </tr>
                    <tr class="nl-detail" id="d<?= $i ?>" hidden>
                        <td></td>
                        <td colspan="4">
                            <table class="nl-spells">
                                <thead><tr><th>Ability</th><th class="num">Amount</th><th class="num">%</th><th class="num">Hits</th><th class="num">Avg</th><th class="num"><?= e($extraLabel) ?></th></tr></thead>
                                <tbody>
                                <?php foreach ($r['spells'] as $s): ?>
                                    <tr>
                                        <td><?= e($s['prefix']) ?><?= e(nl_spell_name($names, (int)$s['spell'], $kindForNames)) ?><?= $s['periodic'] ? ' <span class="nl-sub">(tick)</span>' : '' ?></td>
                                        <td class="num"><?= e(nl_num($s['total'])) ?></td>
                                        <td class="num"><?= number_format($s['total'] / max(1, $r['total']) * 100, 1) ?>%</td>
                                        <td class="num"><?= (int)$s['hits'] ?></td>
                                        <td class="num"><?= e(nl_num($s['total'] / max(1, $s['hits']))) ?></td>
                                        <td class="num"><?= e(nl_num($s['extra'])) ?></td>
                                    </tr>
                                <?php endforeach; ?>
                                </tbody>
                            </table>
                        </td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table></div>
            <p class="notice-line">Click a row for the ability breakdown. Pets are counted under their owner.</p>
            <?php endif; ?>
        <?php endif; ?>
    <?php endif; ?>
    </div>

    <aside>
        <div class="sec-head"><h2>Pulls</h2><span class="notice-line"><?= count($encounters) ?></span></div>
        <?php if (!$encounters): ?>
            <div class="empty">None yet.</div>
        <?php else: ?>
        <ol class="nl-pulls">
            <?php foreach ($encounters as $e): $isCur = $enc && (int)$e['id'] === (int)$enc['id'];
                $ms = ((int)$e['end_ms'] ?: (int)$e['start_ms']) - (int)$e['start_ms']; ?>
                <li<?= $isCur ? ' aria-current="true"' : '' ?>>
                    <a href="log.php?<?= http_build_query(['id' => $run['id'], 'enc' => $e['id'], 'view' => $view]) ?>">
                        <span class="nl-result <?= e(nl_result_class((int)$e['result'])) ?>"><?= e(nl_result_label((int)$e['result'])) ?></span>
                        <strong><?= e($e['boss_name']) ?></strong>
                        <span class="nl-sub"><?= e(nl_duration($ms)) ?> &middot; <?= (int)$e['players'] ?>p</span>
                    </a>
                </li>
            <?php endforeach; ?>
        </ol>
        <?php endif; ?>

        <?php if ($enc && $participants): ?>
        <div class="sec-head"><h2>Raid</h2><span class="notice-line"><?= count($participants) ?></span></div>
        <ul class="nl-roster">
            <?php foreach (array_keys($participants) as $g): ?>
                <li><?= nl_actor_html($actors, $g) ?> <span class="nl-sub"><?= e(nl_era_name((int)$participants[$g])) ?></span></li>
            <?php endforeach; ?>
        </ul>
        <?php endif; ?>
    </aside>
</div>

<script>
document.querySelectorAll('.nl-row').forEach(function (row) {
    var open = function () {
        var d = document.getElementById(row.dataset.toggle);
        if (d) { d.hidden = !d.hidden; row.classList.toggle('is-open', !d.hidden); }
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
});
</script>

<?php endif; ?>

<?php neko_page_end(); ?>

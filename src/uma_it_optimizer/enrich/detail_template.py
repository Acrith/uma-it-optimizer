"""Per-run detail HTML template. Standalone page — links back to the
main dashboard via a header link. Uses the same visual language."""
from __future__ import annotations

import json

from .per_run_detail import RunDetail  # noqa: F401


DETAIL_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
    color-scheme: light dark;
    --bg: #fafafa; --fg: #1a1a1a; --muted: #666;
    --border: #ddd; --row-alt: #f2f2f2; --hover: #e8f0fe;
    --accent: #0366d6;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #14161a; --fg: #e4e4e4; --muted: #999;
        --border: #2a2d33; --row-alt: #1a1d22; --hover: #21334d;
        --accent: #58a6ff;
    }
}
* { box-sizing: border-box; }
body {
    margin: 0; padding: 24px;
    font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--fg);
    max-width: 1400px; margin-left: auto; margin-right: auto;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { margin: 0 0 4px; font-size: 22px; }
h2 {
    margin-top: 28px; margin-bottom: 8px; font-size: 14px;
    color: var(--fg); text-transform: uppercase; letter-spacing: 0.05em;
}
h2 .subtle { color: var(--muted); font-size: 12px; font-weight: 400;
    text-transform: none; letter-spacing: 0; }
.subtitle { color: var(--muted); margin-bottom: 20px; font-size: 13px; }
.stats { display: flex; gap: 24px; margin-bottom: 20px; flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; }
.stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.05em; }
.stat-value { font-size: 18px; font-weight: 600; }
table {
    width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px;
}
th, td {
    padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--border);
    white-space: nowrap;
}
th {
    background: var(--bg); color: var(--muted); font-weight: 600;
    text-transform: uppercase; font-size: 11px; letter-spacing: 0.03em;
}
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr.total { font-weight: 600; background: var(--row-alt); }
tbody tr.total td { border-top: 2px solid var(--border); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
.chip {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    background: var(--row-alt); color: var(--muted);
    font-size: 11px; margin-right: 4px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.chip.type-Speed  { background: #e6f0ff; color: #0033aa; }
.chip.type-Stamina{ background: #ffe1e1; color: #a02020; }
.chip.type-Power  { background: #ffe8cc; color: #a04a00; }
.chip.type-Guts   { background: #ffe6f2; color: #a02060; }
.chip.type-Wit    { background: #e0f2e0; color: #206020; }
.chip.type-Friend { background: #fff8cc; color: #806000; }
@media (prefers-color-scheme: dark) {
    .chip.type-Speed  { background: #1a2540; color: #7fa7ff; }
    .chip.type-Stamina{ background: #3d1a1a; color: #ff9090; }
    .chip.type-Power  { background: #3d2a15; color: #ffb87a; }
    .chip.type-Guts   { background: #3d1a2a; color: #ff9ac9; }
    .chip.type-Wit    { background: #1e3a25; color: #90d99f; }
    .chip.type-Friend { background: #3d3515; color: #e0c869; }
}
.rarity-white { color: var(--muted); }
.rarity-gold  { color: #ba8500; font-weight: 600; }
.rarity-unique{ color: #b054d0; font-weight: 600; }

/* ── SP planner ─────────────────────────────────────────────────── */
.planner-topbar {
    position: sticky; top: 0;
    display: flex; gap: 20px; align-items: center;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 12px;
    z-index: 5;
}
.planner-stat { display: flex; flex-direction: column; }
.planner-stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.planner-stat-value { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.planner-stat-value.over-budget { color: #d43f3f; }
.planner-actions { margin-left: auto; display: flex; gap: 8px; }
.planner-btn {
    padding: 5px 12px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg);
    color: var(--fg);
    font-size: 12px;
    cursor: pointer;
    font-family: inherit;
}
.planner-btn:hover { background: var(--hover); }

.hint-group-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 10px;
}
.hint-group {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--bg);
}
.hint-group-title {
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 4px;
}
.hint-group.has-selection { border-color: #58a6ff; background: color-mix(in srgb, #58a6ff 6%, var(--bg)); }
.variant-row {
    display: flex; align-items: center; gap: 6px;
    margin-top: 4px;
}
.variant-row-label {
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    min-width: 42px;
}
.tier-note {
    color: #ba8500;
    font-size: 9px;
    text-transform: none;
    letter-spacing: 0;
    margin-left: 3px;
}
.variant-list { display: flex; flex-wrap: wrap; gap: 5px; }
.variant-btn {
    display: inline-flex; flex-direction: column;
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--row-alt);
    color: var(--fg);
    font-size: 11px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    min-width: 66px;
}
.variant-btn:hover { border-color: #58a6ff; }
.variant-btn.selected {
    background: #58a6ff;
    color: white;
    border-color: #2f6fc7;
}
.variant-btn.remove { color: #1e8a3a; border-color: #a4d9ba; }
.variant-btn.remove.selected { background: #1e8a3a; color: white; border-color: #10662a; }

.hint-group.dim { opacity: 0.35; }
.hint-group.dim .variant-btn { cursor: default; }
.tag-chip {
    display: inline-block;
    padding: 0 5px;
    border-radius: 2px;
    font-size: 9px;
    font-weight: 600;
    margin-left: 3px;
    vertical-align: middle;
    letter-spacing: 0.02em;
}
.tag-style-Front  { background: #dceeff; color: #0a3a80; }
.tag-style-Pace   { background: #e0dcff; color: #3a1a80; }
.tag-style-Late   { background: #ffe0e0; color: #a02020; }
.tag-style-End    { background: #ffe0f0; color: #a02060; }
.tag-dist         { background: #e0f2e0; color: #206020; }
@media (prefers-color-scheme: dark) {
    .tag-style-Front  { background: #1a2540; color: #7fa7ff; }
    .tag-style-Pace   { background: #2a1a40; color: #b09aff; }
    .tag-style-Late   { background: #3d1a1a; color: #ff9090; }
    .tag-style-End    { background: #3d1a2a; color: #ff9ac9; }
    .tag-dist         { background: #1e3a25; color: #90d99f; }
}

.filter-bar {
    display: flex; gap: 20px; flex-wrap: wrap; align-items: center;
    padding: 8px 12px; margin-bottom: 10px;
    border: 1px solid var(--border); border-radius: 5px;
}
.filter-group { display: flex; gap: 4px; align-items: center; }
.filter-group-label { font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }
.filter-btn {
    padding: 3px 10px; font-size: 11px; font-family: inherit;
    background: var(--bg); color: var(--fg);
    border: 1px solid var(--border); border-radius: 3px; cursor: pointer;
}
.filter-btn:hover { background: var(--hover); }
.filter-btn.active { background: #58a6ff; color: white; border-color: #2f6fc7; }
.variant-btn-label { font-weight: 700; }
.variant-btn-name { opacity: 0.85; }
.variant-btn-nums {
    font-size: 10px; opacity: 0.8;
    margin-top: 2px;
    font-variant-numeric: tabular-nums;
}
@media (prefers-color-scheme: dark) {
    .rarity-gold { color: #e4c060; }
    .rarity-unique { color: #d989ff; }
}
.header-row {
    display: flex;
    align-items: flex-start;
    gap: 20px;
    margin-bottom: 20px;
}
.trainee-portrait {
    width: 96px;
    height: 96px;
    border-radius: 8px;
    background: var(--row-alt);
    border: 1px solid var(--border);
    object-fit: cover;
    flex-shrink: 0;
}
.header-body { flex: 1; }
/* ── game-style card widget ─────────────────────────────────────── */
td.thumb-cell {
    width: 78px;
    padding: 6px;
    text-align: center;
    vertical-align: middle;
}
.card-widget {
    position: relative;
    width: 66px;
    height: 88px;
    border-radius: 5px;
    overflow: hidden;
    background: var(--row-alt);
    border: 1px solid var(--border);
    display: inline-block;
    box-shadow: 0 1px 2px rgba(0,0,0,0.15);
}
.card-widget-art {
    width: 100%; height: 100%; object-fit: cover; display: block;
}
.card-widget-rarity {
    position: absolute; top: 1px; left: 1px;
    width: 32px; height: auto;
    display: block;
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.4));
}
.card-widget-type {
    position: absolute; top: 2px; right: 2px;
    width: 18px; height: 18px;
    display: block;
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.3));
}
.card-widget-crystals {
    position: absolute; bottom: 0; left: 0; right: 0;
    display: flex; gap: 1px;
    justify-content: center;
    padding: 3px 2px;
    background: linear-gradient(to top, rgba(0,0,0,0.75), rgba(0,0,0,0));
}
.card-widget-crystals svg { width: 10px; height: 10px; display: block; }
/* Blue diamonds, mirroring the in-game LB indicator */
.lb-diamond-filled { fill: #6ab6ff; stroke: #2f6fc7; stroke-width: 1; }
.lb-diamond-empty  { fill: none; stroke: rgba(255,255,255,0.5); stroke-width: 1; }
</style>
</head>
<body>
<div class="subtitle"><a href="dashboard.html">← All runs</a></div>
<div class="header-row">
    __PORTRAIT__
    <div class="header-body">
        <h1>__HEADER__</h1>
        <div class="subtitle">__SUBTITLE__</div>
        <div class="stats">
__HEADER_STATS__
        </div>
    </div>
</div>

<h2>Per-source stat contributions</h2>
<table>
    <thead>
        <tr>
            <th></th>
            <th>Source</th>
            <th>Type</th>
            <th class="num">Speed</th>
            <th class="num">Stamina</th>
            <th class="num">Power</th>
            <th class="num">Wiz</th>
            <th class="num">Guts</th>
            <th class="num">SP</th>
            <th class="num">Hints</th>
        </tr>
    </thead>
    <tbody>__CONTRIBUTIONS_ROWS__</tbody>
</table>

<h2>Skill hints acquired <span class="subtle">— total levels across all sources</span></h2>
<table>
    <thead>
        <tr>
            <th>Skill</th>
            <th>Tier</th>
            <th class="num">Total Lvl</th>
            <th>Sources</th>
        </tr>
    </thead>
    <tbody>__HINT_ROWS__</tbody>
</table>

<h2>Score breakdown <span class="subtle">— what the SS-grade estimator says</span></h2>
__SCORE_TABLE__

<h2>SP planner <span class="subtle">— click variants to plan your skill picks · budget updates live</span></h2>
<div id="planner-root">__PLANNER_HTML__</div>

<h2>Knapsack-optimal picks <span class="subtle">— the auto-recommended plan</span></h2>
<table>
    <thead>
        <tr>
            <th>Skill</th>
            <th class="num">SP cost</th>
            <th class="num">Grade value</th>
            <th class="num">Value / SP</th>
        </tr>
    </thead>
    <tbody>__PLAN_ROWS__</tbody>
</table>

<h2>Race history <span class="subtle">— every race actually run, ordered by turn</span></h2>
<table>
    <thead>
        <tr>
            <th class="num">Turn</th>
            <th>Race</th>
            <th>Grade</th>
            <th>Result</th>
            <th>Style</th>
        </tr>
    </thead>
    <tbody>__RACE_ROWS__</tbody>
</table>

<h2>Factors gained</h2>
<table>
    <thead>
        <tr>
            <th>Year</th>
            <th class="num">Count</th>
            <th>Factors</th>
        </tr>
    </thead>
    <tbody>__FACTOR_ROWS__</tbody>
</table>

<script>
__PLANNER_JS__
</script>

</body>
</html>
"""


PLANNER_JS = """
(() => {
    const P = __PLANNER_DATA__;
    if (!P || !P.hint_groups || !P.hint_groups.length) return;
    const root = document.getElementById('planner-root');
    if (!root) return;

    // ── state ─────────────────────────────────────────────────────
    // selection: Set<skill_id>. Each variant toggles independently, so
    // the user can pick both a white ○ AND its gold upgrade in the same
    // group (they're separate purchases in-game).
    const selection = new Set();

    // Filter state — which style/distance the trainee is optimized for.
    // A hint group matches if any of its variants either (a) targets one
    // of the selected styles/distances, or (b) is universal (applies to
    // any setup). Non-matching groups get dimmed, not removed.
    const filter = { styles: new Set(), distances: new Set() };
    const STYLES = ['Front', 'Pace', 'Late', 'End'];
    const DISTANCES = ['Sprint', 'Mile', 'Medium', 'Long'];

    function selectKnapsack() {
        selection.clear();
        for (const sid of (P.knapsack_selection || [])) selection.add(sid);
    }
    function selectNone() { selection.clear(); }

    // Locate which group + variant a skill_id belongs to.
    function findVariant(sid) {
        for (const g of P.hint_groups) {
            for (const v of g.variants) {
                if (v.skill_id === sid) return { group: g, variant: v };
            }
        }
        return null;
    }
    // Currently-selected variant of a given rarity within a group.
    function pickedInTier(group, rarity) {
        return group.variants.find(v => v.rarity === rarity && selection.has(v.skill_id));
    }
    // The "canonical" white variant to auto-pick when a gold is chosen:
    // prefer ○ (rate=1), then ◎ (rate=2). Only considers buy options —
    // removals aren't valid as prereqs for a gold upgrade.
    function defaultWhite(group) {
        const buys = group.variants.filter(v => v.rarity === 1 && v.action !== 'remove');
        return buys.find(v => v.rate === 1)
            || buys.find(v => v.rate === 2)
            || buys[0];
    }
    // Toggle a variant with proper tier semantics:
    //  - White tier is mutex within the group (◎/○/× replace each other).
    //  - Deselecting white also cascades-deselects gold in the same group.
    //  - Selecting gold auto-selects a white prerequisite if none is picked.
    //  - Gold is mutex within its tier (usually only one gold variant).
    function toggleVariant(sid) {
        const found = findVariant(sid);
        if (!found) return;
        const { group, variant } = found;

        // Removals are independent — no mutex, no cascade.
        if (variant.action === 'remove') {
            if (selection.has(sid)) selection.delete(sid);
            else selection.add(sid);
            return;
        }
        // pickedInTier only considers 'buy' variants of a given rarity
        // (removals live in their own row and shouldn't participate in
        // the white/gold mutex or prereq logic).
        const buyPickedInTier = (rarity) =>
            group.variants.find(v => v.rarity === rarity
                && v.action !== 'remove'
                && selection.has(v.skill_id));

        if (variant.rarity === 1) {
            const currentWhite = buyPickedInTier(1);
            if (currentWhite && currentWhite.skill_id === sid) {
                selection.delete(sid);
                for (const v of group.variants) {
                    if (v.rarity === 2 && v.action !== 'remove') selection.delete(v.skill_id);
                }
            } else {
                if (currentWhite) selection.delete(currentWhite.skill_id);
                selection.add(sid);
            }
            return;
        }
        if (variant.rarity === 2) {
            const currentGold = buyPickedInTier(2);
            if (currentGold && currentGold.skill_id === sid) {
                selection.delete(sid);
            } else {
                if (currentGold) selection.delete(currentGold.skill_id);
                selection.add(sid);
                if (!buyPickedInTier(1)) {
                    const w = defaultWhite(group);
                    if (w) selection.add(w.skill_id);
                }
            }
        }
    }

    // ── math ──────────────────────────────────────────────────────
    function totals() {
        let sp = 0, value = 0;
        for (const g of P.hint_groups) {
            for (const v of g.variants) {
                if (selection.has(v.skill_id)) {
                    sp += v.sp_cost; value += v.grade_value;
                }
            }
        }
        return { sp, value };
    }
    function rankForScore(score) {
        for (const t of P.rank_tiers) {
            if (t.min <= score && score <= t.max) return t.rank;
        }
        return score <= 0 ? 1 : P.rank_tiers[P.rank_tiers.length - 1].rank;
    }
    function letterForRank(r) {
        return P.letter_grade_by_rank[r] || (r > 18 ? `EX+${r - 18}` : '?');
    }

    // ── render ────────────────────────────────────────────────────
    function groupMatchesFilter(g) {
        // Mismatch-only filter: a variant is hidden only if it's
        // *specifically for a different* style or distance than what
        // you picked. A skill with no style tag (like Warning Shot) is
        // style-agnostic and stays visible regardless of style filter —
        // and vice versa for distance. So a Pace runner on Miles matches
        // both Pace-only skills, Mile-only skills, Pace+Mile skills,
        // and every universal skill; Sprint/Medium/Long-specific and
        // Front/Late/End-specific skills dim.
        if (filter.styles.size === 0 && filter.distances.size === 0) return true;
        return g.variants.some(v => {
            const vStyles = v.styles || [];
            const vDists = v.distances || [];
            const styleOk = filter.styles.size === 0
                || vStyles.length === 0
                || vStyles.some(s => filter.styles.has(s));
            const distOk = filter.distances.size === 0
                || vDists.length === 0
                || vDists.some(d => filter.distances.has(d));
            return styleOk && distOk;
        });
    }
    function render() {
        const { sp, value } = totals();
        const spLeft = P.budget - sp;
        const totalScore = P.floor_score + value;
        const rank = rankForScore(totalScore);
        const overBudget = sp > P.budget;

        const filterBar = `
            <div class="filter-bar">
                <div class="filter-group">
                    <span class="filter-group-label">Style</span>
                    ${STYLES.map(s =>
                        `<button class="filter-btn ${filter.styles.has(s) ? 'active' : ''}"
                            data-filter="style" data-val="${s}">${s}</button>`
                    ).join('')}
                </div>
                <div class="filter-group">
                    <span class="filter-group-label">Distance</span>
                    ${DISTANCES.map(d =>
                        `<button class="filter-btn ${filter.distances.has(d) ? 'active' : ''}"
                            data-filter="distance" data-val="${d}">${d}</button>`
                    ).join('')}
                </div>
                <span style="color: var(--muted); font-size: 11px;">
                    ${filter.styles.size + filter.distances.size === 0
                        ? 'Showing all groups. Click a tag to focus.'
                        : 'Non-matching groups dimmed. Click again to unfilter.'}
                </span>
            </div>
        `;

        root.innerHTML = `
            <div class="planner-topbar">
                <div class="planner-stat">
                    <span class="planner-stat-label">SP used</span>
                    <span class="planner-stat-value ${overBudget ? 'over-budget' : ''}">
                        ${sp.toLocaleString()} / ${P.budget.toLocaleString()}
                        <span style="font-size: 12px; color: var(--muted);">(${spLeft} left)</span>
                    </span>
                </div>
                <div class="planner-stat">
                    <span class="planner-stat-label">Score bonus</span>
                    <span class="planner-stat-value">+${value.toLocaleString()}</span>
                </div>
                <div class="planner-stat">
                    <span class="planner-stat-label">Est. total</span>
                    <span class="planner-stat-value">${totalScore.toLocaleString()}</span>
                </div>
                <div class="planner-stat">
                    <span class="planner-stat-label">Est. grade</span>
                    <span class="planner-stat-value">${letterForRank(rank)}
                        <span style="font-size: 12px; color: var(--muted);">(rank ${rank})</span>
                    </span>
                </div>
                <div class="planner-actions">
                    <button class="planner-btn" data-action="knapsack">Reset to optimum</button>
                    <button class="planner-btn" data-action="clear">Clear all</button>
                </div>
            </div>
            ${filterBar}
            <div class="hint-group-list">
                ${P.hint_groups.map(renderGroup).join('')}
            </div>
        `;
        // Wire clicks — respect tier semantics (see toggleVariant)
        root.querySelectorAll('.variant-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                toggleVariant(parseInt(btn.dataset.skill));
                render();
            });
        });
        root.querySelectorAll('button[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.action === 'knapsack') selectKnapsack();
                if (btn.dataset.action === 'clear') selectNone();
                render();
            });
        });
        root.querySelectorAll('button[data-filter]').forEach(btn => {
            btn.addEventListener('click', () => {
                const set = btn.dataset.filter === 'style'
                    ? filter.styles : filter.distances;
                const v = btn.dataset.val;
                if (set.has(v)) set.delete(v);
                else set.add(v);
                render();
            });
        });
    }

    function renderGroup(g) {
        const buyWhites = g.variants.filter(v => v.rarity === 1 && v.action !== 'remove');
        const buyGolds  = g.variants.filter(v => v.rarity === 2 && v.action !== 'remove');
        const removals  = g.variants.filter(v => v.action === 'remove');
        const hasSel = g.variants.some(v => selection.has(v.skill_id));
        const dimmed = !groupMatchesFilter(g);
        const rows = [];
        if (buyWhites.length) rows.push(renderVariantRow(buyWhites, 'White', 'buy-white'));
        if (buyGolds.length)  rows.push(renderVariantRow(buyGolds, 'Gold upgrade', 'buy-gold'));
        if (removals.length)  rows.push(renderVariantRow(removals, 'Remove', 'remove'));

        // Classification chips — use the "best" (positive) variant's tags
        // since ○/◎/× of the same skill share classification.
        const primary = g.variants.find(v => v.grade_value > 0) || g.variants[0];
        const styleChips = (primary.styles || [])
            .map(s => `<span class="tag-chip tag-style-${s}">${s}</span>`).join('');
        const distChips = (primary.distances || [])
            .map(d => `<span class="tag-chip tag-dist">${d}</span>`).join('');
        const universalChip = primary.is_universal
            ? '<span class="tag-chip" style="background: var(--row-alt); color: var(--muted);">Universal</span>'
            : '';

        return `
            <div class="hint-group ${hasSel ? 'has-selection' : ''} ${dimmed ? 'dim' : ''}">
                <div class="hint-group-title">
                    ${g.display_name}
                    ${styleChips}${distChips}${universalChip}
                </div>
                ${rows.join('')}
            </div>
        `;
    }

    function renderVariantRow(variants, tierLabel, kind) {
        const notice = kind === 'buy-gold'
            ? '<span class="tier-note">(needs white bought)</span>'
            : kind === 'remove'
            ? '<span class="tier-note">(× auto-acquired; cleanse)</span>'
            : '';
        return `
            <div class="variant-row">
                <span class="variant-row-label">${tierLabel}${notice}</span>
                <div class="variant-list">
                    ${variants.map(v => renderVariant(v, selection.has(v.skill_id))).join('')}
                </div>
            </div>
        `;
    }

    function renderVariant(v, selected) {
        const cls = ['variant-btn'];
        if (selected) cls.push('selected');
        if (v.action === 'remove') cls.push('remove');
        return `
            <button class="${cls.join(' ')}"
                data-skill="${v.skill_id}"
                title="${v.name}">
                <span class="variant-btn-label">${v.rate_label}</span>
                <span class="variant-btn-nums">${v.sp_cost} SP · +${v.grade_value}</span>
            </button>
        `;
    }

    selectKnapsack();
    render();
})();
"""


def _stat_card(label: str, value: str) -> str:
    return (f'<div class="stat"><span class="stat-label">{label}</span>'
            f'<span class="stat-value">{value}</span></div>')


def _rarity_from_id(card_id: int) -> tuple[str, str]:
    """Support card id prefix encodes rarity: 1xxxx=R, 2xxxx=SR, 3xxxx=SSR.
    Returns (css_class, display_label)."""
    prefix = card_id // 10000
    if prefix == 3:
        return "ssr", "SSR"
    if prefix == 2:
        return "sr", "SR"
    return "r", "R"


def _type_short(card_type: str) -> str:
    """One-letter abbreviation shown inside the type badge circle."""
    return {"Speed": "S", "Stamina": "St", "Power": "P",
            "Guts": "G", "Wit": "W", "Friend": "F"}.get(card_type, "?")


def _fmt(n: int | None) -> str:
    if n is None or n == 0:
        return "—"
    return f"{n:,}"


def render(d: RunDetail) -> str:
    header = f"{d.trainee_name} — {d.scenario_name}"
    subtitle = f"{d.timestamp} · <code>{d.filename}</code>"

    total_stats = {k: 0 for k in ("speed", "stamina", "power", "wiz", "guts")}
    for c in d.contributions:
        for k in total_stats:
            total_stats[k] += c["gains"].get(k, 0)

    header_stats = "".join([
        _stat_card("5-stat sum", f"{sum(d.final_stats.values()):,}"),
        _stat_card("Fans", f"{d.fans:,}"),
        _stat_card("Unspent SP", f"{d.unspent_sp:,}"),
        _stat_card("Races run", str(d.races_run)),
        _stat_card("Motivation", str(d.motivation)),
        _stat_card("Vital", f"{d.vital}/100"),
    ])

    # Contribution rows
    contrib_rows_html: list[str] = []
    for c in d.contributions:
        g = c["gains"]
        type_chip = (f'<span class="chip type-{c["card_type"]}">{c["card_type"]}</span>'
                     if c["card_type"] else "")
        # Card widget imitating the in-game card layout, using gametora's
        # actual utx_txt_rarity_* and utx_ico_obtain_* asset URLs from
        # the game's own icon set. Events / Inspiration have no image.
        if c.get("image_url"):
            lb = c.get("limit_break")
            if lb is not None:
                def _diamond(filled: bool) -> str:
                    cls = "lb-diamond-filled" if filled else "lb-diamond-empty"
                    return (f'<svg viewBox="0 0 10 10">'
                            f'<polygon class="{cls}" points="5,0 10,5 5,10 0,5"/></svg>')
                crystals_html = (
                    f'<div class="card-widget-crystals" title="Limit break {lb}/4">'
                    f'{"".join(_diamond(i < lb) for i in range(4))}</div>'
                )
            else:
                crystals_html = ""
            rarity_html = (
                f'<img class="card-widget-rarity" src="{c["rarity_icon_url"]}"'
                f' alt="{c["rarity_label"]}" loading="lazy"'
                f' onerror="this.style.visibility=\'hidden\'">'
                if c.get("rarity_icon_url") else ""
            )
            type_html = (
                f'<img class="card-widget-type" src="{c["type_icon_url"]}"'
                f' alt="{c["card_type"]}" title="{c["card_type"]}" loading="lazy"'
                f' onerror="this.style.visibility=\'hidden\'">'
                if c.get("type_icon_url") else ""
            )
            lb_html = (
                f'<div class="card-widget" title="{c["card_name"]}">'
                f'<img class="card-widget-art" src="{c["image_url"]}"'
                f' alt="{c["card_name"]}" loading="lazy"'
                f' onerror="this.style.visibility=\'hidden\'">'
                f'{rarity_html}'
                f'{type_html}'
                f'{crystals_html}'
                f'</div>'
            )
        else:
            lb_html = ""
        contrib_rows_html.append(
            f'<tr>'
            f'<td class="thumb-cell">{lb_html}</td>'
            f'<td>{c["card_name"]}</td>'
            f'<td>{type_chip}</td>'
            f'<td class="num">{_fmt(g["speed"])}</td>'
            f'<td class="num">{_fmt(g["stamina"])}</td>'
            f'<td class="num">{_fmt(g["power"])}</td>'
            f'<td class="num">{_fmt(g["wiz"])}</td>'
            f'<td class="num">{_fmt(g["guts"])}</td>'
            f'<td class="num">{_fmt(g["skill_pts"])}</td>'
            f'<td class="num">{c["hint_count"] or "—"}</td>'
            f'</tr>'
        )
    # Totals row
    total_sp = sum(c["gains"]["skill_pts"] for c in d.contributions)
    total_hints = sum(c["hint_count"] for c in d.contributions)
    contrib_rows_html.append(
        f'<tr class="total">'
        f'<td></td>'
        f'<td>Total</td><td></td>'
        f'<td class="num">{_fmt(total_stats["speed"])}</td>'
        f'<td class="num">{_fmt(total_stats["stamina"])}</td>'
        f'<td class="num">{_fmt(total_stats["power"])}</td>'
        f'<td class="num">{_fmt(total_stats["wiz"])}</td>'
        f'<td class="num">{_fmt(total_stats["guts"])}</td>'
        f'<td class="num">{_fmt(total_sp)}</td>'
        f'<td class="num">{total_hints or "—"}</td>'
        f'</tr>'
    )

    # Hint rows
    hint_rows_html: list[str] = []
    for h in d.hints:
        sources_labels = ", ".join(sorted({s["source"] for s in h["sources"]}))
        hint_rows_html.append(
            f'<tr>'
            f'<td class="rarity-{h["rarity_label"]}">{h["name"]}</td>'
            f'<td class="rarity-{h["rarity_label"]}">{h["rarity_label"]}</td>'
            f'<td class="num">{h["total_level"]}</td>'
            f'<td>{sources_labels}</td>'
            f'</tr>'
        )
    if not hint_rows_html:
        hint_rows_html.append('<tr><td colspan="4">No hints captured.</td></tr>')

    # Race rows — highlight wins with a subtle green tint
    race_rows_html: list[str] = []
    for rc in d.races:
        result_style = 'color: #1e8a3a; font-weight: 600;' if rc["won"] else ''
        race_rows_html.append(
            f'<tr>'
            f'<td class="num">{rc["turn"]}</td>'
            f'<td>{rc["race_name"]}</td>'
            f'<td>{rc["grade_label"]}</td>'
            f'<td style="{result_style}">{rc["result_ordinal"]}</td>'
            f'<td>{rc["running_style"]}</td>'
            f'</tr>'
        )
    if not race_rows_html:
        race_rows_html.append('<tr><td colspan="5">No races captured.</td></tr>')

    # Factor rows — grouped per year with composed names as chips
    factor_rows_html: list[str] = []
    for y in d.factors_by_year:
        chips = "".join(
            f'<span class="chip" title="factor_id {f["factor_id"]}">{f["name"]}</span>'
            for f in y["factors"]
        )
        factor_rows_html.append(
            f'<tr><td>Year {y["year"]}</td>'
            f'<td class="num">{len(y["factors"])}</td>'
            f'<td>{chips}</td></tr>'
        )
    if not factor_rows_html:
        factor_rows_html.append('<tr><td colspan="3">No factors captured.</td></tr>')

    portrait_html = (
        f'<img class="trainee-portrait" src="{d.trainee_portrait_url}" '
        f'alt="{d.trainee_name}" loading="lazy" '
        f'onerror="this.style.display=\'none\'">'
        if d.trainee_portrait_url else ""
    )

    # Score-breakdown table
    ss = d.score_summary or {}
    if ss:
        # Format helpers
        def fnum(n): return f"{n:,}" if isinstance(n, int) else str(n)
        score_table = (
            '<table>\n<thead><tr>'
            '<th>Component</th><th class="num">Score</th><th>Notes</th>'
            '</tr></thead><tbody>'
            f'<tr><td>Stats (5-stat curve)</td><td class="num">{fnum(ss["stat_score"])}</td>'
            f'<td>from FiveStatusFinalScore lookup</td></tr>'
            f'<tr><td>Owned skills</td><td class="num">{fnum(ss["owned_skill_score"])}</td>'
            f'<td>sum of grade_value for skills you already have</td></tr>'
            f'<tr class="total"><td>Floor (no more SP spent)</td>'
            f'<td class="num">{fnum(ss["floor"])}</td><td>rank {ss["rank_floor"]}</td></tr>'
            f'<tr><td>+ Optimal SP spend</td>'
            f'<td class="num">+{fnum(ss["planned_score"] - ss["floor"])}</td>'
            f'<td>{ss["sp_spent_in_plan"]}/{ss["unspent_sp"]} SP used '
            f'({len(d.plan)} skills)</td></tr>'
            f'<tr class="total"><td>Planned score (knapsack ceiling)</td>'
            f'<td class="num">{fnum(ss["planned_score"])}</td>'
            f'<td>rank {ss["rank_planned"]}</td></tr>'
            f'<tr><td>Naive ceiling (2.0×SP)</td>'
            f'<td class="num">{fnum(ss["naive_ceiling"])}</td>'
            f'<td>flat conversion, overstates by '
            f'{fnum(ss["naive_ceiling"] - ss["planned_score"])}</td></tr>'
            '</tbody></table>'
        )
    else:
        score_table = '<p class="subtle">Score estimator produced no result for this capture.</p>'

    # Plan rows — gold-upgrade rows are indented + prefixed with '└→'
    # so their pairing with the preceding white is visually explicit.
    plan_rows_html: list[str] = []
    for p in d.plan:
        indent_prefix = ""
        row_class = ""
        if p.get("is_gold_upgrade"):
            indent_prefix = ('<span style="color: var(--muted); '
                             'font-family: ui-monospace; margin-right: 6px;">'
                             '└→</span>')
            row_class = ' style="background: color-mix(in srgb, #ffea54 6%, transparent);"'
        plan_rows_html.append(
            f'<tr{row_class}>'
            f'<td>{indent_prefix}{p["name"]}</td>'
            f'<td class="num">{p["sp_cost"]}</td>'
            f'<td class="num">{p["grade_value"]}</td>'
            f'<td class="num">{p["value_per_sp"]:.2f}</td>'
            f'</tr>'
        )
    if not plan_rows_html:
        plan_rows_html.append(
            '<tr><td colspan="4">No hints available to buy '
            '(or no SP budget). Estimator falls back to owned-skill-only floor.</td></tr>'
        )

    # Planner: JS data + placeholder HTML (JS renders into the div on load)
    planner_data_json = json.dumps(d.planner, ensure_ascii=False) if d.planner else "null"
    planner_placeholder = (
        '<p class="subtle">Loading planner…</p>'
        if d.planner else
        '<p class="subtle">No skill hints available — no plan to build.</p>'
    )
    planner_js = PLANNER_JS.replace("__PLANNER_DATA__", planner_data_json)

    return (
        DETAIL_HTML
        .replace("__TITLE__", f"{d.trainee_name} · {d.timestamp}")
        .replace("__PORTRAIT__", portrait_html)
        .replace("__HEADER__", header)
        .replace("__SUBTITLE__", subtitle)
        .replace("__HEADER_STATS__", header_stats)
        .replace("__CONTRIBUTIONS_ROWS__", "".join(contrib_rows_html))
        .replace("__HINT_ROWS__", "".join(hint_rows_html))
        .replace("__SCORE_TABLE__", score_table)
        .replace("__PLANNER_HTML__", planner_placeholder)
        .replace("__PLANNER_JS__", planner_js)
        .replace("__PLAN_ROWS__", "".join(plan_rows_html))
        .replace("__RACE_ROWS__", "".join(race_rows_html))
        .replace("__FACTOR_ROWS__", "".join(factor_rows_html))
    )

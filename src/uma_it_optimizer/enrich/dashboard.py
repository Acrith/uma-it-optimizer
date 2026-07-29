from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .aggregations import by_deck
from .detail_template import render as render_detail
from .per_run_detail import build as build_detail
from .run_metrics import RunMetrics, summarize_directory


HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IT runs — dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
    color-scheme: light dark;
    --bg: #fafafa;
    --fg: #1a1a1a;
    --muted: #666;
    --border: #ddd;
    --row-alt: #f2f2f2;
    --hover: #e8f0fe;
    --accent: #0366d6;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #14161a;
        --fg: #e4e4e4;
        --muted: #999;
        --border: #2a2d33;
        --row-alt: #1a1d22;
        --hover: #21334d;
        --accent: #58a6ff;
    }
}
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 24px;
    font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--fg);
}
h1 { margin: 0 0 4px; font-size: 20px; }
.subtitle { color: var(--muted); margin-bottom: 16px; font-size: 13px; }
.stats {
    display: flex;
    gap: 24px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}
.stat { display: flex; flex-direction: column; }
.stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.05em; }
.stat-value { font-size: 18px; font-weight: 600; }
input[type=search] {
    width: 100%;
    max-width: 400px;
    padding: 8px 12px;
    font: inherit;
    background: var(--bg);
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-bottom: 12px;
}
.table-wrap { overflow-x: auto; }
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    min-width: 900px;
}
th, td {
    padding: 6px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}
th {
    cursor: pointer;
    user-select: none;
    background: var(--bg);
    position: sticky;
    top: 0;
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.03em;
}
th:hover { color: var(--fg); }
th.sort-asc::after { content: " \\25B2"; color: var(--accent); }
th.sort-desc::after { content: " \\25BC"; color: var(--accent); }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: var(--hover); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
.badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.badge-completed { background: #d4edda; color: #155724; }
.badge-pre_training { background: #ffe1cc; color: #7a3f00; }
@media (prefers-color-scheme: dark) {
    .badge-completed { background: #1e3a25; color: #90d99f; }
    .badge-pre_training { background: #3d2915; color: #ffb87a; }
}
.controls {
    display: flex;
    gap: 16px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 12px;
}
label.toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--muted);
    cursor: pointer;
}
.empty {
    padding: 40px;
    text-align: center;
    color: var(--muted);
}
h2 {
    margin-top: 32px;
    margin-bottom: 8px;
    font-size: 15px;
    color: var(--fg);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
h2 .subtle { color: var(--muted); font-size: 12px; font-weight: 400; text-transform: none; letter-spacing: 0; }
.chip {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--row-alt);
    color: var(--muted);
    font-size: 11px;
    margin-right: 4px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.deck-thumbs {
    display: inline-flex;
    gap: 3px;
    vertical-align: middle;
    margin-right: 6px;
}
.deck-thumb-wrap { position: relative; display: inline-block; }
.deck-thumb-wrap img.card {
    width: 32px;
    height: 42px;
    border-radius: 3px;
    object-fit: cover;
    background: var(--row-alt);
    border: 1px solid var(--border);
    display: block;
}
.deck-thumb-wrap img.type-badge {
    position: absolute; top: -2px; right: -2px;
    width: 12px; height: 12px;
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.3));
}
.deck-thumb-wrap .lb-mini {
    display: flex; gap: 1px; justify-content: center;
    margin-top: 2px;
}
.deck-thumb-wrap .lb-mini svg { width: 6px; height: 6px; display: block; }
.lb-mini .filled { fill: #6ab6ff; stroke: #2f6fc7; stroke-width: 1; }
.lb-mini .empty { fill: none; stroke: rgba(150,150,150,0.5); stroke-width: 1; }
tbody tr td:has(.deck-thumbs) { padding: 8px 10px; }
.grade-badge {
    height: 22px;
    width: auto;
    vertical-align: middle;
    display: inline-block;
}
</style>
</head>
<body>
<h1>Independent Training runs</h1>
<div class="subtitle">__SUBTITLE__</div>

<div class="stats">
__STATS_HTML__
</div>

<h2>Deck performance <span class="subtle">— completed runs only, click column to sort</span></h2>
<div class="table-wrap">
<table id="decks">
    <thead>
        <tr>
            <th data-key="deck_hash"     data-type="text">Deck</th>
            <th data-key="type_label"    data-type="text">Types</th>
            <th data-key="trainees_label" data-type="text">Trainees</th>
            <th data-key="runs"          data-type="num">Runs</th>
            <th data-key="best_score"    data-type="num" title="Best planned score across runs of this deck">Best Score</th>
            <th data-key="avg_score"     data-type="num" title="Average planned score across runs of this deck">Avg Score</th>
            <th data-key="best_rank"     data-type="num" title="Grade range: worst floor → best ceiling across runs">Grade</th>
            <th data-key="best_stat_sum" data-type="num">Best 5-Stat</th>
            <th data-key="avg_unspent_sp" data-type="num">Avg SP</th>
            <th data-key="best_fans"     data-type="num">Best Fans</th>
        </tr>
    </thead>
    <tbody id="decks-body"></tbody>
</table>
</div>

<h2>All runs <span class="subtle">— per-capture detail</span></h2>
<div class="controls">
    <input type="search" id="filter" placeholder="Filter (deck#, trainee, scenario, ...)">
    <label class="toggle">
        <input type="checkbox" id="show-all">
        Show pre-training / incomplete captures
    </label>
</div>

<div class="table-wrap">
<table id="runs">
    <thead>
        <tr>
            <th data-key="run_state"     data-type="text">State</th>
            <th data-key="timestamp"     data-type="text">Date</th>
            <th data-key="trainee_name"  data-type="text">Trainee</th>
            <th data-key="scenario_name" data-type="text">Scenario</th>
            <th data-key="deck_hash"     data-type="text">Deck</th>
            <th data-key="score_ceiling" data-type="num" title="Estimated SS-grade score at knapsack-optimal SP spend">Score</th>
            <th data-key="letter_grade"  data-type="text" title="Letter grade range from rank tier">Grade</th>
            <th data-key="stat_sum"      data-type="num">5-Stat</th>
            <th data-key="speed"         data-type="num">Spd</th>
            <th data-key="stamina"       data-type="num">Sta</th>
            <th data-key="power"         data-type="num">Pow</th>
            <th data-key="wiz"           data-type="num">Wiz</th>
            <th data-key="guts"          data-type="num">Gts</th>
            <th data-key="unspent_sp"    data-type="num">SP</th>
            <th data-key="races_run"     data-type="num">Races</th>
            <th data-key="fans"          data-type="num">Fans</th>
            <th data-key="skill_hints_available" data-type="num">Hints</th>
            <th data-key="timestamp"     data-type="text">Detail</th>
        </tr>
    </thead>
    <tbody id="runs-body"></tbody>
</table>
</div>

<script>
const DATA = __DATA_JSON__;
const DECKS = __DECKS_JSON__;

function fmtDate(ts) {
    // 20260725T185207 → 2026-07-25 18:52
    if (!/^\\d{8}T\\d{6}$/.test(ts)) return ts;
    return `${ts.slice(0,4)}-${ts.slice(4,6)}-${ts.slice(6,8)} `
         + `${ts.slice(9,11)}:${ts.slice(11,13)}`;
}
function fmtNum(n) {
    if (n === null || n === undefined) return "";
    return typeof n === "number" ? n.toLocaleString() : n;
}
function renderDeckGradeRange(d) {
    // Grade spread across the runs in this deck's bucket — worst floor
    // to best ceiling. Shows how much the deck's outcome varies with
    // SP-picking + trainee.
    const lo = d.worst_grade_letter, hi = d.best_grade_letter;
    const loIcon = d.worst_grade_icon, hiIcon = d.best_grade_icon;
    if (!lo && !hi) return "—";
    const badge = (letter, url) => url
        ? `<img class="grade-badge" src="${url}" alt="${letter}" title="${letter}" loading="lazy" onerror="this.replaceWith(document.createTextNode('${letter}'))">`
        : `<strong>${letter}</strong>`;
    if (lo === hi) return badge(lo, loIcon);
    return `${badge(lo, loIcon)}<span style="color: var(--muted); margin: 0 3px;">→</span>${badge(hi, hiIcon)}`;
}

function renderGradeBadges(r) {
    // Render floor and ceiling icons side-by-side with a '→' when they
    // differ. Falls back to bold text for EX-tier grades where we have
    // no icon URL.
    const floor = r.grade_floor_letter, ceiling = r.grade_ceiling_letter;
    const floorIcon = r.grade_floor_icon, ceilingIcon = r.grade_ceiling_icon;
    if (!floor && !ceiling) return "—";
    const badge = (letter, url) => url
        ? `<img class="grade-badge" src="${url}" alt="${letter}" title="${letter}" loading="lazy" onerror="this.replaceWith(document.createTextNode('${letter}'))">`
        : `<strong>${letter}</strong>`;
    if (floor === ceiling) return badge(floor, floorIcon);
    return `${badge(floor, floorIcon)}<span style="color: var(--muted); margin: 0 3px;">→</span>${badge(ceiling, ceilingIcon)}`;
}

function renderDeckThumb(c) {
    if (!c || !c.image_url) return "";
    const crystals = c.limit_break != null
        ? Array.from({length: 4}, (_, i) =>
            `<svg viewBox="0 0 10 10"><polygon class="${i < c.limit_break ? 'filled' : 'empty'}" points="5,0 10,5 5,10 0,5"/></svg>`
          ).join("")
        : "";
    const typeBadge = c.type_icon_url
        ? `<img class="type-badge" src="${c.type_icon_url}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
        : "";
    return `<span class="deck-thumb-wrap" title="${c.name || ""} · LB ${c.limit_break ?? '?'}/4">
        <img class="card" src="${c.image_url}" loading="lazy" onerror="this.style.visibility='hidden'">
        ${typeBadge}
        <span class="lb-mini">${crystals}</span>
    </span>`;
}

// ── generic sortable-table controller ─────────────────────────────
function makeSortable({tableId, bodyId, colspan, data, defaultKey, defaultDir, rowHtml, filterFn}) {
    const table = document.getElementById(tableId);
    const body = document.getElementById(bodyId);
    let sortKey = defaultKey;
    let sortDir = defaultDir;
    let filterText = "";
    let showAll = false;

    function apply() {
        let rows = data;
        if (filterFn) rows = rows.filter(r => filterFn(r, {showAll, filterText}));
        const q = filterText.trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                Object.values(r).some(v => String(v).toLowerCase().includes(q))
            );
        }
        const numeric = table.querySelector(`th[data-key="${sortKey}"]`)?.dataset.type === "num";
        rows = [...rows].sort((a, b) => {
            const av = a[sortKey], bv = b[sortKey];
            if (numeric) return ((av || 0) - (bv || 0)) * sortDir;
            return String(av).localeCompare(String(bv)) * sortDir;
        });
        table.querySelectorAll("th").forEach(th => {
            th.classList.remove("sort-asc", "sort-desc");
            if (th.dataset.key === sortKey) {
                th.classList.add(sortDir === 1 ? "sort-asc" : "sort-desc");
            }
        });
        if (!rows.length) {
            body.innerHTML = `<tr><td colspan="${colspan}" class="empty">No rows.</td></tr>`;
        } else {
            body.innerHTML = rows.map(rowHtml).join("");
        }
    }

    table.querySelectorAll("th").forEach(th => {
        th.addEventListener("click", () => {
            const key = th.dataset.key;
            if (sortKey === key) sortDir = -sortDir;
            else { sortKey = key; sortDir = th.dataset.type === "num" ? -1 : 1; }
            apply();
        });
    });

    return {
        apply,
        setFilter: (t) => { filterText = t; apply(); },
        setShowAll: (v) => { showAll = v; apply(); },
    };
}

// ── runs table ────────────────────────────────────────────────────
const runsCtrl = makeSortable({
    tableId: "runs",
    bodyId: "runs-body",
    colspan: 20,
    data: DATA,
    defaultKey: "timestamp",
    defaultDir: -1,
    filterFn: (r, {showAll}) => showAll || r.run_state === "completed",
    rowHtml: (r) => `
        <tr title="${r.filename}\\n${r.deck_summary}">
            <td><span class="badge badge-${r.run_state}">${r.run_state.replace("_", " ")}</span></td>
            <td>${fmtDate(r.timestamp)}</td>
            <td>${r.trainee_name}</td>
            <td>${r.scenario_name}</td>
            <td title="${r.deck_summary}">
                <span class="deck-thumbs">
                    ${(r.deck_cards||[]).map(c => renderDeckThumb(c)).join("")}
                </span>
                <span class="mono" style="font-size: 10px; color: var(--muted); vertical-align: middle;">${r.deck_hash}</span>
            </td>
            <td class="num" title="${r.score_range_label}">${r.score_ceiling ? fmtNum(r.score_ceiling) : "—"}</td>
            <td title="${r.rank_range_label}">${renderGradeBadges(r)}</td>
            <td class="num">${fmtNum(r.stat_sum)}</td>
            <td class="num">${fmtNum(r.speed)}</td>
            <td class="num">${fmtNum(r.stamina)}</td>
            <td class="num">${fmtNum(r.power)}</td>
            <td class="num">${fmtNum(r.wiz)}</td>
            <td class="num">${fmtNum(r.guts)}</td>
            <td class="num">${fmtNum(r.unspent_sp)}</td>
            <td class="num">${fmtNum(r.races_run)}</td>
            <td class="num">${fmtNum(r.fans)}</td>
            <td class="num">${fmtNum(r.skill_hints_available)}</td>
            <td>${r.detail_href ? `<a href="${r.detail_href}">Open ▸</a>` : "—"}</td>
        </tr>
    `,
});
document.getElementById("filter").addEventListener("input", e => runsCtrl.setFilter(e.target.value));
document.getElementById("show-all").addEventListener("change", e => runsCtrl.setShowAll(e.target.checked));

// ── decks table ───────────────────────────────────────────────────
const decksCtrl = makeSortable({
    tableId: "decks",
    bodyId: "decks-body",
    colspan: 10,
    data: DECKS,
    defaultKey: "best_fans",
    defaultDir: -1,
    filterFn: null,
    rowHtml: (d) => `
        <tr title="${d.deck_summary}">
            <td>
                <span class="deck-thumbs">
                    ${(d.deck_cards||[]).map(c => renderDeckThumb(c)).join("")}
                </span>
                <span class="mono" style="font-size: 10px; color: var(--muted); vertical-align: middle;">${d.deck_hash}</span>
            </td>
            <td>${Object.entries(d.type_composition).sort((a,b)=>b[1]-a[1])
                    .map(([t,n]) => `<span class="chip">${n}×${t}</span>`).join("")}</td>
            <td>${d.trainees_label}</td>
            <td class="num">${d.runs}</td>
            <td class="num">${fmtNum(d.best_score)}</td>
            <td class="num">${fmtNum(d.avg_score)}</td>
            <td>${renderDeckGradeRange(d)}</td>
            <td class="num">${fmtNum(d.best_stat_sum)}</td>
            <td class="num">${fmtNum(d.avg_unspent_sp)}</td>
            <td class="num">${fmtNum(d.best_fans)}</td>
        </tr>
    `,
});

runsCtrl.apply();
decksCtrl.apply();
</script>
</body>
</html>
"""


def _stat_card(label: str, value: str) -> str:
    return (
        f'<div class="stat"><span class="stat-label">{label}</span>'
        f'<span class="stat-value">{value}</span></div>'
    )


def _stats_html(runs: list[RunMetrics]) -> str:
    """Header cards — computed from completed runs only. Pre-training
    captures would skew the 'best' fields, so we ignore them here."""
    if not runs:
        return _stat_card("Runs", "0")
    completed = [r for r in runs if r.run_state == "completed"]
    if not completed:
        return "".join([
            _stat_card("Runs (total)", str(len(runs))),
            _stat_card("Completed runs", "0"),
            _stat_card("Note", "no completed captures yet"),
        ])
    deck_counter: Counter[str] = Counter(r.deck_hash for r in completed)
    top_deck_hash, top_deck_count = deck_counter.most_common(1)[0]
    best_stat_sum = max(r.stat_sum for r in completed)
    best_fans = max(r.fans for r in completed)
    incomplete = len(runs) - len(completed)
    tail = f" (+{incomplete} incomplete)" if incomplete else ""
    return "".join([
        _stat_card("Completed runs", f"{len(completed)}{tail}"),
        _stat_card("Unique decks", str(len(deck_counter))),
        _stat_card("Most-used deck", f"{top_deck_hash} ({top_deck_count}×)"),
        _stat_card("Best 5-stat sum", f"{best_stat_sum:,}"),
        _stat_card("Best fans", f"{best_fans:,}"),
    ])


def build_dashboard(runs_dir: Path, out_path: Path) -> Path:
    runs = summarize_directory(runs_dir)
    rows = [r.as_row() for r in runs]

    # Generate per-run detail pages alongside the main dashboard, and
    # inject the href into each row so the main table can link to it.
    for row, r in zip(rows, runs, strict=True):
        run_json_path = runs_dir / r.filename
        if not run_json_path.exists():
            row["detail_href"] = None
            continue
        try:
            detail = build_detail(run_json_path)
            html = render_detail(detail)
            detail_name = f"detail_{r.timestamp}_uma{r.trainee_card_id}.html"
            (runs_dir / detail_name).write_text(html, encoding="utf-8")
            row["detail_href"] = detail_name
        except (KeyError, ValueError, json.JSONDecodeError):
            row["detail_href"] = None

    data_json = json.dumps(rows, ensure_ascii=False)

    # Deck aggregation over completed runs only — pre-training captures
    # would pollute avg/best figures with base-state noise.
    completed = [r for r in runs if r.run_state == "completed"]
    deck_rows = [d.as_row() for d in by_deck(completed)]
    decks_json = json.dumps(deck_rows, ensure_ascii=False)

    subtitle = (
        f"Source: <code>{runs_dir}</code> — {len(runs)} run"
        f"{'s' if len(runs) != 1 else ''} loaded"
    )
    html = (
        HTML_TEMPLATE
        .replace("__SUBTITLE__", subtitle)
        .replace("__STATS_HTML__", _stats_html(runs))
        .replace("__DATA_JSON__", data_json)
        .replace("__DECKS_JSON__", decks_json)
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path

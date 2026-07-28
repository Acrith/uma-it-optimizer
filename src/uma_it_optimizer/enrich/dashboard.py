from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

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
</style>
</head>
<body>
<h1>Independent Training runs</h1>
<div class="subtitle">__SUBTITLE__</div>

<div class="stats">
__STATS_HTML__
</div>

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
            <th data-key="deck_hash"     data-type="text">Deck#</th>
            <th data-key="stat_sum"      data-type="num">5-Stat</th>
            <th data-key="speed"         data-type="num">Spd</th>
            <th data-key="stamina"       data-type="num">Sta</th>
            <th data-key="power"         data-type="num">Pow</th>
            <th data-key="wiz"           data-type="num">Wiz</th>
            <th data-key="guts"          data-type="num">Gts</th>
            <th data-key="fans"          data-type="num">Fans</th>
            <th data-key="factors_total" data-type="num">Factors</th>
            <th data-key="skills_owned"  data-type="num">Skills</th>
            <th data-key="skill_hints_available" data-type="num">Hints</th>
            <th data-key="unspent_sp"    data-type="num">SP</th>
            <th data-key="races_run"     data-type="num">Races</th>
        </tr>
    </thead>
    <tbody id="runs-body"></tbody>
</table>
</div>

<script>
const DATA = __DATA_JSON__;

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

function render(rows) {
    const body = document.getElementById("runs-body");
    if (!rows.length) {
        body.innerHTML =
            '<tr><td colspan="17" class="empty">No runs match this filter.</td></tr>';
        return;
    }
    body.innerHTML = rows.map(r => `
        <tr title="${r.filename}\\n${r.deck_summary}">
            <td><span class="badge badge-${r.run_state}">${r.run_state.replace("_", " ")}</span></td>
            <td>${fmtDate(r.timestamp)}</td>
            <td>${r.trainee_name}</td>
            <td>${r.scenario_name}</td>
            <td class="mono" title="${r.deck_summary}">${r.deck_hash}</td>
            <td class="num">${fmtNum(r.stat_sum)}</td>
            <td class="num">${fmtNum(r.speed)}</td>
            <td class="num">${fmtNum(r.stamina)}</td>
            <td class="num">${fmtNum(r.power)}</td>
            <td class="num">${fmtNum(r.wiz)}</td>
            <td class="num">${fmtNum(r.guts)}</td>
            <td class="num">${fmtNum(r.fans)}</td>
            <td class="num">${fmtNum(r.factors_total)}</td>
            <td class="num">${fmtNum(r.skills_owned)}</td>
            <td class="num">${fmtNum(r.skill_hints_available)}</td>
            <td class="num">${fmtNum(r.unspent_sp)}</td>
            <td class="num">${fmtNum(r.races_run)}</td>
        </tr>
    `).join("");
}

let sortKey = "timestamp";
let sortDir = -1; // -1 desc, 1 asc
let filterText = "";
let showAll = false;

function applyAndRender() {
    const q = filterText.trim().toLowerCase();
    let rows = DATA;
    if (!showAll) rows = rows.filter(r => r.run_state === "completed");
    if (q) {
        rows = rows.filter(r =>
            Object.values(r).some(v =>
                String(v).toLowerCase().includes(q)
            )
        );
    }
    const numeric = document.querySelector(`th[data-key="${sortKey}"]`)
        ?.dataset.type === "num";
    rows = [...rows].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (numeric) return (av - bv) * sortDir;
        return String(av).localeCompare(String(bv)) * sortDir;
    });
    document.querySelectorAll("th").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.key === sortKey) {
            th.classList.add(sortDir === 1 ? "sort-asc" : "sort-desc");
        }
    });
    render(rows);
}

document.querySelectorAll("th").forEach(th => {
    th.addEventListener("click", () => {
        const key = th.dataset.key;
        if (sortKey === key) sortDir = -sortDir;
        else { sortKey = key; sortDir = th.dataset.type === "num" ? -1 : 1; }
        applyAndRender();
    });
});
document.getElementById("filter").addEventListener("input", e => {
    filterText = e.target.value;
    applyAndRender();
});
document.getElementById("show-all").addEventListener("change", e => {
    showAll = e.target.checked;
    applyAndRender();
});

applyAndRender();
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
    data_json = json.dumps(rows, ensure_ascii=False)
    subtitle = (
        f"Source: <code>{runs_dir}</code> — {len(runs)} run"
        f"{'s' if len(runs) != 1 else ''} loaded"
    )
    html = (
        HTML_TEMPLATE
        .replace("__SUBTITLE__", subtitle)
        .replace("__STATS_HTML__", _stats_html(runs))
        .replace("__DATA_JSON__", data_json)
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path

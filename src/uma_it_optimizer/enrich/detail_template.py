"""Per-run detail HTML template. Standalone page — links back to the
main dashboard via a header link. Uses the same visual language."""
from __future__ import annotations

import json

from .per_run_detail import RunDetail


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
.card-thumb {
    width: 40px;
    height: 52px;
    border-radius: 3px;
    vertical-align: middle;
    object-fit: cover;
    background: var(--row-alt);
    border: 1px solid var(--border);
}
td.thumb-cell { width: 48px; padding: 4px 6px; }
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

</body>
</html>
"""


def _stat_card(label: str, value: str) -> str:
    return (f'<div class="stat"><span class="stat-label">{label}</span>'
            f'<span class="stat-value">{value}</span></div>')


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
        img_html = (
            f'<img class="card-thumb" src="{c["image_url"]}" alt="{c["card_name"]}"'
            f' loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            if c.get("image_url") else ""
        )
        contrib_rows_html.append(
            f'<tr>'
            f'<td class="thumb-cell">{img_html}</td>'
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

    return (
        DETAIL_HTML
        .replace("__TITLE__", f"{d.trainee_name} · {d.timestamp}")
        .replace("__PORTRAIT__", portrait_html)
        .replace("__HEADER__", header)
        .replace("__SUBTITLE__", subtitle)
        .replace("__HEADER_STATS__", header_stats)
        .replace("__CONTRIBUTIONS_ROWS__", "".join(contrib_rows_html))
        .replace("__HINT_ROWS__", "".join(hint_rows_html))
        .replace("__FACTOR_ROWS__", "".join(factor_rows_html))
    )

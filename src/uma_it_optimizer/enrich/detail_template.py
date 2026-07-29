"""Per-run detail HTML template. Standalone page — links back to the
main dashboard via a header link. Uses the same visual language."""
from __future__ import annotations

import json

from .lookups import grade_icon_url, letter_grade
from .per_run_detail import RunDetail  # noqa: F401


DETAIL_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
/* Palette mirrors the dashboard shell. Section accent for the detail
   page is 'lineage' green. Theme resolves via the same three-way
   rule: explicit data-theme wins, then OS preference, then dark. */
:root {
    color-scheme: dark light;
    --bg: #10131c; --bg-2: #171b28; --bg-3: #202538;
    --fg: #e8eaf2; --muted: #8a90a6;
    --border: #262c42; --row-alt: #181c2a; --hover: #232a42;
    --accent: #62b0ff; --accent-2: #ffb454;
    --accent-decks: #ff5c9b; --accent-runs: #62b0ff; --accent-lineage: #47c95c;
    --section-accent: var(--accent-runs);
    --shadow: 0 4px 16px rgba(0,0,0,0.4);
    --radius: 8px;
}
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
        --bg: #f4f2f6; --bg-2: #ffffff; --bg-3: #ffffff;
        --fg: #1a1a1a; --muted: #666;
        --border: #e0dce6; --row-alt: #faf7fc; --hover: #edeaf3;
        --accent: #0366d6;
        --shadow: 0 4px 16px rgba(0,0,0,0.08);
    }
}
:root[data-theme="light"] {
    color-scheme: light;
    --bg: #f4f2f6; --bg-2: #ffffff; --bg-3: #ffffff;
    --fg: #1a1a1a; --muted: #666;
    --border: #e0dce6; --row-alt: #faf7fc; --hover: #edeaf3;
    --accent: #0366d6;
    --shadow: 0 4px 16px rgba(0,0,0,0.08);
}
* { box-sizing: border-box; }
body {
    margin: 0;
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--fg);
    min-height: 100vh;
}
/* App shell — mirrors dashboard.py. Kept inline so detail pages open
   standalone without needing an external stylesheet. */
.app {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
    min-height: 100vh;
}
/* Embed mode: hide the standalone shell so only the run content shows
   when the page is loaded inside the dashboard's iframe. Section-nav
   and planner topbar keep their sticky behavior (relative to the
   iframe's own viewport). */
body.embed-mode { min-height: auto; }
body.embed-mode .sidebar { display: none; }
body.embed-mode .app { grid-template-columns: 1fr; }
body.embed-mode .main { padding: 16px 24px 32px; }
body.embed-mode .section-nav {
    top: 0;
    margin: 0 -24px 16px; padding: 8px 24px;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
}
body.embed-mode .planner-topbar { top: 44px; }
.sidebar {
    background: var(--bg-2);
    border-right: 1px solid var(--border);
    padding: 24px 16px;
    position: sticky; top: 0;
    height: 100vh;
    overflow-y: auto;
    display: flex; flex-direction: column; gap: 20px;
}
.sidebar-brand { display: flex; flex-direction: column; gap: 2px; padding: 0 6px; }
.sidebar-brand .brand-mark {
    font-size: 18px; font-weight: 700; letter-spacing: -0.01em;
    background: linear-gradient(135deg, var(--accent-decks), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
.sidebar-brand .brand-sub {
    color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.08em;
}
.side-nav { display: flex; flex-direction: column; gap: 2px; }
.side-nav a {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px; color: var(--muted); text-decoration: none;
    border-radius: 6px; font-weight: 500; transition: background 0.12s, color 0.12s;
}
.side-nav a:hover { background: var(--hover); color: var(--fg); }
.side-nav a.active {
    background: var(--bg-3); color: var(--accent-lineage);
    box-shadow: inset 3px 0 0 var(--accent-lineage);
}
.side-nav .nav-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: currentColor; opacity: 0.85;
}
.side-nav a[data-section="decks"] .nav-dot { color: var(--accent-decks); }
.side-nav a[data-section="runs"] .nav-dot { color: var(--accent-runs); }
.side-nav a[data-section="detail"] .nav-dot { color: var(--accent-lineage); }
.side-quick {
    margin-top: auto;
    padding: 10px 12px;
    background: var(--bg-3);
    border-radius: var(--radius);
    display: flex; flex-direction: column; gap: 4px;
    font-size: 11px;
}
.side-quick .stat {
    display: flex; flex-direction: row;
    justify-content: space-between; align-items: center;
    gap: 8px;
    min-width: 0;
    line-height: 1.4;
}
.side-quick .stat-label {
    color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.04em; font-size: 9px;
    flex-shrink: 0;
}
.side-quick .stat-value {
    color: var(--fg); font-weight: 700; font-variant-numeric: tabular-nums;
    font-size: 12px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    min-width: 0; text-align: right;
}

.main {
    padding: 24px 32px 48px;
    min-width: 0;
}
.main .card-panel { max-width: 100%; }

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { margin: 0 0 4px; font-size: 22px; }
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

/* ── Facility-style stat panel ─────────────────────────────────────
   Riff on the in-game stat readout: one card per training facility
   with grade circle + value; SP on the far right. */
.fac-panel {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 10px;
}
.fac-card {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    background: var(--bg);
    min-width: 0;
}
.fac-hdr {
    display: flex; align-items: center; gap: 6px;
    color: var(--muted);
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
    margin-bottom: 4px;
}
.fac-icon { font-size: 14px; line-height: 1; }
.fac-icon-img { width: 18px; height: 18px; object-fit: contain; }
.fac-icon-sp {
    display: inline-flex; align-items: center; justify-content: center;
    width: 20px; height: 18px;
    background: #9060d0; color: white;
    border-radius: 4px; font-size: 10px; font-weight: 700;
}
.fac-label { font-weight: 600; }
.fac-body { display: flex; align-items: center; gap: 8px; }
.fac-body .fac-value { line-height: 1; }
.fac-value {
    font-size: 22px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--fg);
}
.fac-card.fac-sp .fac-value { color: #9060d0; }
.stat-cap { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.fac-body img.grade-badge {
    height: 30px; width: auto; object-fit: contain;
    display: block;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.15));
}
/* Dark theme: nudge saturation + subtle glow so the light-card badges
   don't read as yellowed rectangles on the dark surface. */
:root[data-theme="dark"] .fac-body img.grade-badge,
:root[data-theme="dark"] .rank-badge img,
:root[data-theme="dark"] .compat-big img {
    filter:
        drop-shadow(0 0 0.5px rgba(255, 255, 255, 0.6))
        drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))
        saturate(1.15) brightness(1.05);
}
@media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) .fac-body img.grade-badge,
    :root:not([data-theme="light"]) .rank-badge img,
    :root:not([data-theme="light"]) .compat-big img {
        filter:
            drop-shadow(0 0 0.5px rgba(255, 255, 255, 0.6))
            drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5))
            saturate(1.15) brightness(1.05);
    }
}
/* Grade circle — tier-colored. Grades map to buckets: g0=G, g1=F/E,
   g2=D/C, g3=B/A, g4=S/SS/SS+, g5=UG/UG+. */
.grade {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 26px; height: 26px; padding: 0 6px;
    border-radius: 50%; font-weight: 800; font-size: 13px;
    color: white;
}
/* Grade badge colors — match the in-game rank table.
   Bases: G gray, F light purple, E dark purple, D indigo, C lime,
   B pink, A orange, S gold, SS deep gold, U-series a rainbow. */
.grade-G  { background: #9e9e9e; }
.grade-F  { background: #b98be0; }
.grade-E  { background: #8845c0; }
.grade-D  { background: #5e4bcd; }
.grade-C  { background: #7bbd45; }
.grade-B  { background: #e6549a; }
.grade-A  { background: #ee8b34; }
.grade-S  { background: #f4c336; color: #4a3a00; }
.grade-SS { background: #e59500; }
/* U-series (>1200) uses a distinct gold/rainbow set */
.grade-UG { background: linear-gradient(135deg, #ff8a00, #e6549a); }
.grade-UF { background: linear-gradient(135deg, #e6549a, #8845c0); }
.grade-UE { background: linear-gradient(135deg, #8845c0, #5e4bcd); }
.grade-UD { background: linear-gradient(135deg, #5e4bcd, #3a7bff); }
.grade-UC { background: linear-gradient(135deg, #3a7bff, #37b34a); }
.grade-UB { background: linear-gradient(135deg, #37b34a, #7bbd45); }
.grade-UA { background: linear-gradient(135deg, #7bbd45, #f4c336); color: #3a3a00; }
.grade-US { background: linear-gradient(135deg, #f4c336, #ee8b34, #e6549a); color: #3a1a00; }
/* '+' variant sharpens the badge — border + slight glow so G+ vs G reads at a glance */
.grade.grade-plus {
    box-shadow: 0 0 0 2px rgba(255,255,255,0.35) inset, 0 0 4px rgba(255,138,0,0.35);
}
/* U-series get a wider badge to accommodate 2-3 chars */
.grade.grade-u { min-width: 36px; padding: 0 8px; font-size: 12px; }
/* Per-facility card tint on the header bar */
.fac-card.fac-speed   { border-top: 3px solid #3a7bff; }
.fac-card.fac-stamina { border-top: 3px solid #e64545; }
.fac-card.fac-power   { border-top: 3px solid #ff8f30; }
.fac-card.fac-guts    { border-top: 3px solid #e94494; }
.fac-card.fac-wisdom  { border-top: 3px solid #37b34a; }
.fac-card.fac-sp      { border-top: 3px solid #9060d0; }

/* Hint cards — 2 columns on standard viewports, auto-fills to more
   or fewer on wider/narrower screens. Each card is a two-row unit:
   pill + level badge on top, sources muted underneath. */
.hint-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 8px;
    margin-bottom: 16px;
}
.hint-card {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
    background: var(--bg);
    min-width: 0;
}
.hint-main {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 4px;
}
.hint-main .skill-pill { flex: 1; min-width: 0; }
.hint-lv {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 2px 8px;
    background: var(--row-alt); color: var(--fg);
    border-radius: 10px;
    font-size: 11px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.hint-lv-max {
    background: linear-gradient(135deg, #ff8a00, #d54a8a);
    color: white;
}
.hint-sources {
    color: var(--muted); font-size: 11px;
    padding-left: 4px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Rank badges — inline letter icon + tiny 'rank N' hint underneath */
.rank-badge {
    display: inline-flex; align-items: center; gap: 6px;
    line-height: 1;
}
.rank-badge img {
    height: 22px; width: auto; object-fit: contain;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.15));
}
.rank-badge .rank-num {
    color: var(--muted); font-size: 11px;
    font-variant-numeric: tabular-nums;
}
.planner-grade { display: inline-flex; align-items: center; gap: 6px; }
.planner-grade-badge {
    height: 28px; width: auto; object-fit: contain;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.15));
    display: block;
}

.hint-empty {
    color: var(--muted); font-style: italic; padding: 20px;
    text-align: center; border: 1px dashed var(--border); border-radius: 6px;
}

.meta-strip {
    display: flex; gap: 20px; flex-wrap: wrap;
    color: var(--muted); font-size: 12px;
    padding: 4px 0 0;
}
.meta-strip b { color: var(--fg); font-weight: 600; }

/* Sticky section nav — quick jumps to each section, mirrors the SP
   planner's own sticky bar so scrolling long detail pages stays
   navigable. */
.section-nav {
    position: sticky; top: 0;
    z-index: 10;
    display: flex; gap: 4px; flex-wrap: wrap;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
    backdrop-filter: blur(6px);
    border-bottom: 1px solid var(--border);
    margin: 12px -24px 20px; padding-left: 24px; padding-right: 24px;
    font-size: 12px;
}
.section-nav a {
    padding: 4px 10px;
    border-radius: 4px;
    color: var(--muted);
    text-decoration: none;
    transition: background 0.15s;
}
.section-nav a:hover { background: var(--row-alt); color: var(--fg); text-decoration: none; }
.section-nav a.active { color: var(--accent); font-weight: 600; }
.section-nav .back-link {
    color: var(--accent);
    background: var(--row-alt);
    font-weight: 600;
    padding: 4px 12px;
}
.section-nav .nav-sep {
    display: inline-block; width: 1px; height: 16px;
    background: var(--border);
    margin: 0 4px;
}
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
/* Contribution table — column-tinted stats + bigger numbers so a row
   scan gives you "how much Speed did I get, from where" without
   having to eyeball across a sparse grid. */
.contrib-table th, .contrib-table td { padding: 8px 10px; }
.contrib-table th.col-thumb, .contrib-table td.thumb-cell { width: 76px; padding: 6px 8px; }
.contrib-table td.num {
    padding: 8px 12px;
    min-width: 56px;
    font-size: 15px;
    font-weight: 600;
    color: var(--fg);
}
.contrib-table td.num.zero { color: var(--muted); font-weight: 400; }
.contrib-table tr.total { border-top: 2px solid var(--border); background: var(--row-alt); }
.contrib-table tr.total td { padding-top: 10px; padding-bottom: 10px; font-weight: 700; }
.contrib-table tr.total td.num { font-size: 16px; }
.contrib-table .source-cell { display: flex; align-items: center; gap: 8px; }
.contrib-table .source-cell .chip { margin: 0; font-size: 11px; padding: 1px 6px; }
/* Column tints — the tint matches the training-focus color, so the eye
   maps 'red column = stamina' without looking at the header each time.
   Applied to <th> AND <td> in the same column via nth-of-type. */
.contrib-table th.col-speed,   .contrib-table td:nth-of-type(3) { background: rgba(58, 123, 255, 0.08); }
.contrib-table th.col-stamina, .contrib-table td:nth-of-type(4) { background: rgba(230, 69, 69, 0.08); }
.contrib-table th.col-power,   .contrib-table td:nth-of-type(5) { background: rgba(255, 143, 48, 0.10); }
.contrib-table th.col-guts,    .contrib-table td:nth-of-type(6) { background: rgba(233, 68, 148, 0.08); }
.contrib-table th.col-wisdom,  .contrib-table td:nth-of-type(7) { background: rgba(55, 179, 74, 0.10); }
.contrib-table th.col-sp,      .contrib-table td:nth-of-type(8) { background: rgba(150, 100, 220, 0.10); }
@media (prefers-color-scheme: dark) {
    .contrib-table th.col-speed,   .contrib-table td:nth-of-type(3) { background: rgba(58, 123, 255, 0.15); }
    .contrib-table th.col-stamina, .contrib-table td:nth-of-type(4) { background: rgba(230, 69, 69, 0.15); }
    .contrib-table th.col-power,   .contrib-table td:nth-of-type(5) { background: rgba(255, 143, 48, 0.15); }
    .contrib-table th.col-guts,    .contrib-table td:nth-of-type(6) { background: rgba(233, 68, 148, 0.15); }
    .contrib-table th.col-wisdom,  .contrib-table td:nth-of-type(7) { background: rgba(55, 179, 74, 0.15); }
    .contrib-table th.col-sp,      .contrib-table td:nth-of-type(8) { background: rgba(150, 100, 220, 0.15); }
}
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

/* Factor category chips — uma.moe-style color coding */
.chip.factor-stat     { background: #d5e5ff; color: #0f3d80; }
.chip.factor-aptitude { background: #ffd9dd; color: #900026; }
.chip.factor-unique   { background: #d3f0d5; color: #1e6a2b; border: 1px solid #6bc38a; }
.chip.factor-skill    { background: #ececf0; color: #3a3a45; }
.chip.factor-green    { background: #e0f2df; color: #206020; }
.chip.factor-special  { background: #f0e2ff; color: #4c1a8a; }
.chip.factor-unknown  { background: var(--row-alt); color: var(--muted); }
/* Factors-gained table — the Factors column packs many chips, so let
   it wrap onto multiple lines and give each row a bit of vertical
   breathing room. Year + Count stay narrow on the left. */
.factors-table td:nth-of-type(1) { white-space: nowrap; vertical-align: top; width: 60px; }
.factors-table td:nth-of-type(2) { white-space: nowrap; vertical-align: top; width: 60px; }
.factors-table td:nth-of-type(3) {
    white-space: normal;
    line-height: 1.9;
    padding-top: 8px; padding-bottom: 8px;
}
.factors-table td .chip { margin: 2px 3px; }

/* Pre-run affinity aptitudes get a diamond marker and dimmed styling
   so they're visibly distinct from actual year-1 spark procs. */
.chip.preroll { opacity: 0.65; border: 1px dashed rgba(0,0,0,0.15); }
.chip.preroll sup { font-size: 9px; margin-left: 2px; opacity: 0.75; }
.preroll-note {
    color: var(--muted); font-size: 11px; font-style: italic;
    margin-top: 4px;
}
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
    position: sticky; top: 44px;    /* below the section-nav */
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    padding: 8px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 12px;
    z-index: 5;
}
.planner-stat { display: flex; flex-direction: column; min-width: 0; }
.planner-stat-label {
    color: var(--muted); font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.04em;
}
.planner-stat-value {
    font-size: 15px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    display: inline-flex; align-items: center; gap: 4px;
    white-space: nowrap;
}
.planner-stat-value.over-budget { color: #d43f3f; }
.planner-actions {
    margin-left: auto; display: flex; gap: 6px;
    flex-shrink: 0;
}
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
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
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
/* Game-style skill pill: icon on left, name+cost on right. Background
   gradient encodes tier — white (r=1), gold (r=2), unique (r>=4),
   debuff/purple for removals. */
.variant-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px 3px 3px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: linear-gradient(to right, #f0eef5 0%, #e0dae8 100%);
    color: #333;
    font-size: 11px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    min-width: 130px;
    max-width: 220px;
    overflow: hidden;
}
.variant-btn:hover { filter: brightness(1.05); box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
.variant-btn.selected {
    outline: 2px solid #2f6fc7;
    outline-offset: 1px;
}
.variant-btn img.skill-icon {
    width: 30px; height: 30px;
    border-radius: 50%;
    flex-shrink: 0;
    background: transparent;
}
.variant-btn-body { display: flex; flex-direction: column; overflow: hidden; }
.variant-btn-name {
    font-weight: 600;
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 170px;
}
.variant-btn-nums {
    font-size: 10px;
    opacity: 0.75;
    font-variant-numeric: tabular-nums;
}

/* Rarity tier gradients — match game/gametora pill colors */
.variant-btn.tier-gold { background: linear-gradient(to right, #ffc754 0%, #ff9134 100%); color: #4a2600; }
.variant-btn.tier-unique { background: linear-gradient(to right, #7fb3ff 0%, #5e8fff 100%); color: white; }
.variant-btn.tier-white  { background: linear-gradient(to right, #f0eef5 0%, #e0dae8 100%); color: #333; }
.variant-btn.negative-x { background: linear-gradient(to right, #d0b0ff 0%, #b090e0 100%); color: white; }
.variant-btn.remove {
    background: linear-gradient(to right, #a4d9ba 0%, #6bc38a 100%);
    color: #10441e;
    border-color: #6bc38a;
}
.variant-btn.remove.selected { outline-color: #10662a; }
.variant-btn.inert { cursor: default; }
.variant-btn.inert:hover { filter: none; box-shadow: none; }
@media (prefers-color-scheme: dark) {
    .variant-btn.tier-white  { color: #ddd; background: linear-gradient(to right, #3a3a4a 0%, #2e2e3d 100%); }
    .variant-btn.tier-gold   { color: #2a1500; }
    .variant-btn.negative-x  { color: white; }
    .variant-btn.remove      { color: #dfffe6; background: linear-gradient(to right, #206040 0%, #185030 100%); }
}

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

/* Lineage / parent-compat panel */
.lineage-panel { border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; background: var(--bg); }
.lineage-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.lineage-header h2 { margin: 0; font-size: 16px; }
.lineage-header .compat-big { font-size: 28px; font-weight: 700; line-height: 1; }
.lineage-header .compat-big.compat-3 { color: #ff8a00; }
.lineage-header .compat-big.compat-2 { color: #58a6ff; }
.lineage-header .compat-big.compat-1 { color: #b96e6e; }
.lineage-header .compat-total { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
.lineage-tree { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.lineage-parent { border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }
.lineage-parent-hdr { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.lineage-parent-hdr img.portrait { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; background: var(--row-alt); }
.lineage-parent-hdr .name { font-weight: 600; }
.lineage-parent-hdr .rank { color: var(--muted); font-size: 12px; margin-left: auto; }
.lineage-stats { color: var(--muted); font-size: 11px; margin-bottom: 8px; font-variant-numeric: tabular-nums; }
.lineage-factors { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
/* Muted variant for factors that did NOT proc this run — same color
   family but low opacity + no border so the sparked ones pop. */
.lineage-factors .chip.not-sparked {
    opacity: 0.35; filter: grayscale(0.5);
}
.lineage-factors .chip.sparked {
    box-shadow: 0 0 0 1px currentColor inset, 0 0 6px rgba(255,138,0,0.35);
    font-weight: 600;
}
.lineage-factors .sparked-glow { text-shadow: 0 0 4px rgba(255,138,0,0.6); }
.factor-legend { color: var(--muted); font-size: 11px; margin: 6px 0 10px; }
.factor-legend .chip { margin-right: 4px; padding: 1px 6px; font-size: 10px; }
.lineage-gp-block { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); }
.lineage-gp-block .gp-title { color: var(--muted); font-size: 11px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
.lineage-gp { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.lineage-gp .gp { font-size: 11px; padding: 6px 8px; border: 1px dashed var(--border); border-radius: 4px; }
.lineage-gp .gp-hdr { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.lineage-gp .gp-hdr img.portrait { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; background: var(--row-alt); }
.lineage-gp .gp-hdr .gp-name { font-weight: 600; font-size: 11px; flex: 1; }
.lineage-gp .gp-hdr .gp-rank { color: var(--muted); font-size: 10px; }
.compat-breakdown { font-size: 12px; margin-top: 10px; }
.compat-breakdown table { min-width: 0; }
.compat-breakdown td { padding: 3px 8px; }
.compat-breakdown .pair-label { color: var(--muted); }
.no-lineage { color: var(--muted); font-size: 12px; margin: 4px 0 0 40px; }
.no-lineage b { color: var(--fg); }
.lineage-missing { border-style: dashed; background: color-mix(in srgb, #b8860b 6%, transparent); }
.lineage-missing .compat-big.compat-0 { color: #b8860b; }

/* SP-cost hint-discount annotation on plan rows */
.sp-hint { color: var(--muted); font-size: 10px; margin-left: 4px; }
.sp-hint s { text-decoration: line-through; }
</style>
</head>
<body>
<!-- Detail pages render standalone at file://…/detail_*.html but the
     dashboard embeds them via iframe. Adding ?embed=1 to the URL hides
     the shell so only the run's content shows inside the dashboard's
     panel slot. -->
<div class="app">
<aside class="sidebar">
    <div class="sidebar-brand">
        <span class="brand-mark">uma-it-optimizer</span>
        <span class="brand-sub">Independent Training</span>
    </div>
    <nav class="side-nav">
        <a href="dashboard.html#decks" data-section="decks"><span class="nav-dot"></span>Decks</a>
        <a href="dashboard.html#runs" data-section="runs"><span class="nav-dot"></span>Runs</a>
        <a href="#" data-section="detail" class="active" aria-current="page"><span class="nav-dot"></span>__RUN_TAB_LABEL__</a>
    </nav>
    <div class="side-quick">__SIDEBAR_STATS__</div>
</aside>
<main class="main">
<div class="header-row">
    __PORTRAIT__
    <div class="header-body">
        <h1>__HEADER__</h1>
        <div class="subtitle">__SUBTITLE__</div>
__HEADER_STATS__
    </div>
</div>

<nav class="section-nav">
    <a href="#contribs">Contributions</a>
    <a href="#hints">Hints</a>
    <a href="#score">Score</a>
    <a href="#planner">Planner</a>
    <a href="#plan">Optimal picks</a>
    <a href="#races">Races</a>
    <a href="#lineage">Lineage</a>
    <a href="#factors">Factors</a>
</nav>

<h2 id="contribs">Per-source stat contributions</h2>
<table class="contrib-table">
    <thead>
        <tr>
            <th class="col-thumb"></th>
            <th>Source</th>
            <th class="num col-speed">Speed</th>
            <th class="num col-stamina">Stamina</th>
            <th class="num col-power">Power</th>
            <th class="num col-guts">Guts</th>
            <th class="num col-wisdom">Wisdom</th>
            <th class="num col-sp">SP</th>
            <th class="num">Hints</th>
        </tr>
    </thead>
    <tbody>__CONTRIBUTIONS_ROWS__</tbody>
</table>

<h2 id="hints">Skill hints acquired <span class="subtle">— total levels across all sources</span></h2>
<div class="hint-grid">__HINT_ROWS__</div>

<h2 id="score">Score breakdown <span class="subtle">— what the SS-grade estimator says</span></h2>
__SCORE_TABLE__

<h2 id="planner">SP planner <span class="subtle">— click variants to plan your skill picks · budget updates live</span></h2>
<div id="planner-root">__PLANNER_HTML__</div>

<h2 id="plan">Knapsack-optimal picks <span class="subtle">— the auto-recommended plan</span></h2>
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

<h2 id="races">Race history <span class="subtle">— every race actually run, ordered by turn</span></h2>
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

<div id="lineage">__LINEAGE_PANEL__</div>

<h2 id="factors">Factors gained</h2>
<table class="factors-table">
    <thead>
        <tr>
            <th>Year</th>
            <th class="num">Count</th>
            <th>Factors</th>
        </tr>
    </thead>
    <tbody>__FACTOR_ROWS__</tbody>
</table>

</main>
</div>

<script>
// Embed mode — when this page is loaded inside the dashboard's
// iframe (?embed=1), collapse the shell so only the run content shows.
// The dashboard supplies its own sidebar around us.
(function () {
    // Embed mode triggered via hash (#embed) — file:// URLs render
    // query strings inconsistently, but hash fragments work everywhere.
    if (location.hash === '#embed' || location.search.includes('embed=1')) {
        document.body.classList.add('embed-mode');
    }
    // Sync theme with the parent (if embedded) or with localStorage
    // (if standalone). Also listen for live theme changes from parent.
    function applyTheme(theme) {
        if (theme === 'light' || theme === 'dark') {
            document.documentElement.dataset.theme = theme;
        } else {
            delete document.documentElement.dataset.theme;
        }
    }
    try { applyTheme(localStorage.getItem('uma_it_theme')); }
    catch (_) { /* localStorage can be denied inside iframes */ }
    window.addEventListener('message', (e) => {
        if (e.data && e.data.type === 'theme') applyTheme(e.data.value);
    });
    // When the standalone shell is visible, sidebar Decks / Runs links
    // navigate back to the dashboard; message the parent instead when
    // embedded (dashboard picks up the click via postMessage and
    // switches its own active panel).
    document.querySelectorAll('.side-nav a[data-section]').forEach(a => {
        a.addEventListener('click', (e) => {
            if (!document.body.classList.contains('embed-mode')) return;
            e.preventDefault();
            parent.postMessage({type: 'nav', section: a.dataset.section}, '*');
        });
    });
})();
</script>
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
        // Re-run knapsack against currently-visible groups so the plan
        // reflects the active filter (e.g. Pace + Mile → optimum for that
        // build). When no filter is active this reproduces the Python
        // pre-computed selection.
        const chosen = knapsackForActiveFilter();
        for (const sid of chosen) selection.add(sid);
    }
    function selectNone() { selection.clear(); }

    // Multi-choice knapsack, JS-side. Packages per group:
    //   [do nothing, white_i, (white_i + gold_j)*, removal stacked on any]
    // Only considers groups that match the current filter.
    function knapsackForActiveFilter() {
        const budget = P.budget | 0;
        if (budget <= 0) return [];
        const groupOptions = [];
        for (const g of P.hint_groups) {
            if (!groupMatchesFilter(g)) continue;
            const whites = g.variants.filter(v =>
                v.rarity === 1 && v.action !== 'remove' && v.grade_value > 0);
            const golds = g.variants.filter(v =>
                v.rarity === 2 && v.action !== 'remove');
            const removals = g.variants.filter(v => v.action === 'remove');
            if (!whites.length && !golds.length && !removals.length) continue;
            const packages = [{cost: 0, value: 0, sids: []}];
            for (const w of whites) {
                packages.push({cost: w.sp_cost, value: w.grade_value, sids: [w.skill_id]});
                for (const gd of golds) {
                    packages.push({
                        cost: w.sp_cost + gd.sp_cost,
                        value: w.grade_value + gd.grade_value,
                        sids: [w.skill_id, gd.skill_id],
                    });
                }
            }
            if (removals.length) {
                const base = packages.slice();
                for (const r of removals) {
                    for (const b of base) {
                        packages.push({
                            cost: b.cost + r.sp_cost,
                            value: b.value + r.grade_value,
                            sids: b.sids.concat([r.skill_id]),
                        });
                    }
                }
            }
            groupOptions.push(packages);
        }
        const n = groupOptions.length;
        if (!n) return [];

        // dp[i][w] flattened into one Int32Array per row for speed.
        const dp = new Array(n + 1);
        const choice = new Array(n + 1);
        for (let i = 0; i <= n; i++) {
            dp[i] = new Int32Array(budget + 1);
            choice[i] = new Int32Array(budget + 1);
        }
        for (let i = 1; i <= n; i++) {
            const pkgs = groupOptions[i - 1];
            const prev = dp[i - 1];
            const cur = dp[i];
            const ch = choice[i];
            for (let w = 0; w <= budget; w++) {
                let bestV = prev[w];
                let bestI = 0;
                for (let pi = 0; pi < pkgs.length; pi++) {
                    const p = pkgs[pi];
                    if (p.cost <= w) {
                        const v = prev[w - p.cost] + p.value;
                        if (v > bestV) { bestV = v; bestI = pi; }
                    }
                }
                cur[w] = bestV;
                ch[w] = bestI;
            }
        }
        const out = [];
        let w = budget;
        for (let i = n; i > 0; i--) {
            const p = groupOptions[i - 1][choice[i][w]];
            for (const sid of p.sids) out.push(sid);
            w -= p.cost;
        }
        return out;
    }

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
    function gradeBadgeHtml(rank) {
        const letter = letterForRank(rank);
        const icon = P.grade_icons_by_letter && P.grade_icons_by_letter[letter];
        const numTag = `<span class="rank-num">rank ${rank}</span>`;
        if (icon) {
            return `<img class="planner-grade-badge" src="${icon}" alt="${letter}"
                    title="rank ${rank}"
                    onerror="this.replaceWith(document.createTextNode('${letter}'))">
                    ${numTag}`;
        }
        return `<b>${letter}</b>${numTag}`;
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
                    <span class="planner-stat-value planner-grade">
                        ${gradeBadgeHtml(rank)}
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
        // Pill tier gradients (white/gold/purple×/green-remove) already
        // convey what each variant IS — no need for row labels.
        // Order variants: whites first, then gold upgrades, then removals.
        const buyWhites = g.variants.filter(v => v.rarity === 1 && v.action !== 'remove');
        const buyGolds  = g.variants.filter(v => v.rarity === 2 && v.action !== 'remove');
        const removals  = g.variants.filter(v => v.action === 'remove');
        const hasSel = g.variants.some(v => selection.has(v.skill_id));
        const dimmed = !groupMatchesFilter(g);
        const ordered = [...buyWhites, ...buyGolds, ...removals];

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
                <div class="variant-list">
                    ${ordered.map(v => renderVariant(v, selection.has(v.skill_id))).join('')}
                </div>
            </div>
        `;
    }

    function renderVariant(v, selected) {
        const cls = ['variant-btn'];
        if (selected) cls.push('selected');
        if (v.action === 'remove') cls.push('remove');
        else if (v.rate === -1) cls.push('negative-x');
        else if (v.rarity >= 4) cls.push('tier-unique');
        else if (v.rarity === 2) cls.push('tier-gold');
        else cls.push('tier-white');
        const iconHtml = v.icon_url
            ? `<img class="skill-icon" src="${v.icon_url}" alt="" loading="lazy"
                    onerror="this.style.visibility='hidden'">`
            : '<span class="skill-icon" style="display:inline-block"></span>';
        // Skill names already carry the ○/◎/× decorator when applicable
        // (e.g. 'Corner Recovery ○', 'Firm Conditions ◎', 'Fall Runner ×').
        // Skills with a single variant (e.g. 'Come What May', 'It's On!')
        // have no decorator. So don't prefix with rate_label — it either
        // duplicates or clutters. For removals we prepend a small 'Remove'
        // marker since the name alone doesn't convey the action.
        const namePrefix = v.action === 'remove' ? 'Remove ' : '';
        // Hint discount indicator: append 'lv N' + strikethrough base cost
        // when a discount is active. Buttons stay narrow — full formula
        // is in the tooltip.
        const base = v.base_sp_cost || v.sp_cost;
        const lv = v.hint_level || 0;
        const spCell = (lv > 0 && base > v.sp_cost)
            ? `${v.sp_cost} SP · <s style="opacity:.6;">${base}</s> · lv${lv}`
            : `${v.sp_cost} SP`;
        const tip = (lv > 0 && base > v.sp_cost)
            ? `${v.name} — base ${base} SP → ${v.sp_cost} SP (hint Lv ${lv}, ${lv*10}% off)`
            : v.name;
        return `
            <button class="${cls.join(' ')}"
                data-skill="${v.skill_id}"
                title="${tip}">
                ${iconHtml}
                <span class="variant-btn-body">
                    <span class="variant-btn-name">${namePrefix}${v.name}</span>
                    <span class="variant-btn-nums">${spCell} · +${v.grade_value}</span>
                </span>
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


# In-game stat grades. Two regimes:
#
# 1) 1..1200 uses fine tiers with + variants at half-steps:
#      G   1-50    G+  51-99
#      F   100-149 F+  150-199
#      E   200-249 E+  250-299
#      D   300-349 D+  350-399
#      C   400-499 C+  500-599
#      B   600-699 B+  700-799
#      A   800-899 A+  900-999
#      S   1000-1049 S+  1050-1099
#      SS  1100-1149 SS+ 1150-1200
#
# 2) 1201+ enters the U-series: alphabet drops 100 (UG=1201-1300,
#    UF=1301-1400, ..., US=1901-2000); a trailing digit 1..9 refines
#    each 100-window into 10-tens (base letter for 01-10, "1" for
#    11-20, ..., "9" for 91-00). Reference image confirmed 2026-07-30.
_LO_TIERS: tuple[tuple[int, str], ...] = (
    (1150, "SS+"), (1100, "SS"),
    (1050, "S+"),  (1000, "S"),
    (900,  "A+"),  (800,  "A"),
    (700,  "B+"),  (600,  "B"),
    (500,  "C+"),  (400,  "C"),
    (350,  "D+"),  (300,  "D"),
    (250,  "E+"),  (200,  "E"),
    (150,  "F+"),  (100,  "F"),
    (51,   "G+"),  (1,    "G"),
)
# U-series: second letter lower-case (matches the overall-rank icon
# keys). Digits are rendered as superscripts.
_U_LETTERS = ("Ug", "Uf", "Ue", "Ud", "Uc", "Ub", "Ua", "Us")
_SUPERSCRIPT_DIGIT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def stat_grade(value: int) -> str:
    """Stat grade in the same key format as ``lookups.GRADE_ICON_URL``
    (G / G+ / ... / SS+ / Ug / Ug¹ / ... / Us⁹). Uses the reference
    thresholds from the community rank table."""
    if value <= 0:
        return "G"
    if value <= 1200:
        for th, letter in _LO_TIERS:
            if value >= th:
                return letter
        return "G"
    over = value - 1200
    letter_idx = min((over - 1) // 100, len(_U_LETTERS) - 1)
    base = _U_LETTERS[letter_idx]
    within_100 = (over - 1) % 100  # 0..99
    if within_100 < 10:
        return base
    return base + str(within_100 // 10).translate(_SUPERSCRIPT_DIGIT)


def _grade_base(letter: str) -> str:
    """Strip trailing '+' or superscript digit to get the base class."""
    if letter.endswith("+"):
        return letter[:-1]
    if letter and letter[-1] in "⁰¹²³⁴⁵⁶⁷⁸⁹":
        return letter[:-1]
    return letter


# Support card TYPE (Wit) vs stat DISPLAY (Wisdom) — Global calls the
# stat 'Wisdom' but the training icon is the wit graduation cap
# (utx_ico_obtain_04). Same asset works for both.
_STAT_ICON_INDEX = {
    "speed":   0,  # boot
    "stamina": 1,  # heart
    "power":   2,  # bicep
    "guts":    3,  # flame
    "wisdom":  4,  # graduation cap
}


def _stat_icon_url(key: str) -> str:
    """Game-asset URL for a stat facility icon (from gametora CDN,
    same set as support-card training-focus icons)."""
    idx = _STAT_ICON_INDEX.get(key, 0)
    return f"https://gametora.com/images/umamusume/icons/utx_ico_obtain_0{idx}.png"


def _stat_facility_widget(
    *, key: str, label: str, value: int, cap: int,
) -> str:
    """One stat 'facility' badge — icon + grade badge + value/cap.

    Grade badges reuse the overall-uma-rank icon set (same visual
    system, matches the community rank-table image reference). Falls
    back to a styled text badge for tiers without a bundled icon URL
    (U-series beyond Ue⁹ don't have icons yet)."""
    grade = stat_grade(value)
    cap_str = f'<span class="stat-cap">/ {cap:,}</span>' if cap else ""
    icon_url = _stat_icon_url(key)

    badge_icon = grade_icon_url(grade)
    if badge_icon:
        grade_html = (
            f'<img class="grade-badge" src="{badge_icon}" alt="{grade}"'
            f' title="{grade}" loading="lazy"'
            f' onerror="this.replaceWith(document.createTextNode(\'{grade}\'))">'
        )
    else:
        base = _grade_base(grade)
        base_cls = base.replace("+", "").replace("¹","").replace("²","") \
                       .replace("³","").replace("⁴","").replace("⁵","") \
                       .replace("⁶","").replace("⁷","").replace("⁸","").replace("⁹","")
        plus_cls = " grade-plus" if grade.endswith("+") else ""
        u_cls = " grade-u" if base.startswith("U") else ""
        grade_html = (
            f'<span class="grade grade-{base_cls}{plus_cls}{u_cls}">'
            f'{grade}</span>'
        )
    return (
        f'<div class="fac-card fac-{key}">'
        f'  <div class="fac-hdr">'
        f'    <img class="fac-icon-img" src="{icon_url}" alt="{label}"'
        f' loading="lazy" onerror="this.style.display=\'none\'">'
        f'    <span class="fac-label">{label}</span>'
        f'  </div>'
        f'  <div class="fac-body">'
        f'    {grade_html}'
        f'    <span class="fac-value">{value:,}</span>{cap_str}'
        f'  </div>'
        f'</div>'
    )


def _sp_widget(value: int) -> str:
    return (
        f'<div class="fac-card fac-sp">'
        f'  <div class="fac-hdr">'
        f'    <span class="fac-icon fac-icon-sp">SP</span>'
        f'    <span class="fac-label">Skill Pts</span>'
        f'  </div>'
        f'  <div class="fac-body">'
        f'    <span class="fac-value">{value:,}</span>'
        f'  </div>'
        f'</div>'
    )


def _skill_pill_html(*, name: str, icon_url: str | None, rarity: int = 1,
                     rate: int = 1, action: str = "buy") -> str:
    """Static (non-clickable) pill for the picks / hints tables.
    Same visual language as the planner's variant buttons but marked
    inert (no cursor / hover). Rarity → gradient like the planner."""
    cls = ["variant-btn", "inert"]
    if action == "remove":
        cls.append("remove")
    elif rate == -1:
        cls.append("negative-x")
    elif rarity >= 4:
        cls.append("tier-unique")
    elif rarity == 2:
        cls.append("tier-gold")
    else:
        cls.append("tier-white")
    icon = (
        f'<img class="skill-icon" src="{icon_url}" alt="" loading="lazy" '
        f'onerror="this.style.visibility=\'hidden\'">'
        if icon_url else '<span class="skill-icon"></span>'
    )
    return (
        f'<span class="{" ".join(cls)}" title="{name}">'
        f'{icon}'
        f'<span class="variant-btn-body">'
        f'<span class="variant-btn-name">{name}</span>'
        f'</span></span>'
    )


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

    # Facility-style stat panel (game convention: Speed, Stamina, Power,
    # Guts, Wisdom, then SP). Icons kept as short text tags to avoid
    # emoji-rendering variance across OSes.
    fac_defs = [
        ("speed",   "Speed"),
        ("stamina", "Stamina"),
        ("power",   "Power"),
        ("guts",    "Guts"),
        ("wisdom",  "Wisdom"),
    ]
    header_stats = '<div class="fac-panel">' + "".join(
        _stat_facility_widget(
            key=k, label=lbl,
            value=int(d.final_stats.get(k if k != "wisdom" else "wiz", 0)),
            cap=int(d.caps.get(k if k != "wisdom" else "wiz", 0)),
        )
        for (k, lbl) in fac_defs
    ) + _sp_widget(d.unspent_sp) + '</div>'
    # 5-stat sum / Fans / Races strip removed — it duplicated the
    # sidebar's quick-stats block. The sidebar is persistent and
    # carries the same numbers.

    # Contribution rows — columns render in Speed/Stamina/Power/Guts/
    # Wisdom/SP order to match in-game facility layout. Zero values get
    # a faded '—' so the eye can skip them.
    def _num_cell(val: int) -> str:
        if not val:
            return '<td class="num zero">—</td>'
        return f'<td class="num">{_fmt(val)}</td>'

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
        hint_val = int(c.get("hint_count") or 0)
        hint_cell = (f'<td class="num zero">—</td>'
                     if not hint_val else f'<td class="num">{hint_val}</td>')
        contrib_rows_html.append(
            f'<tr>'
            f'<td class="thumb-cell">{lb_html}</td>'
            f'<td><span class="source-cell">'
            f'<span class="name">{c["card_name"]}</span>{type_chip}'
            f'</span></td>'
            f'{_num_cell(int(g.get("speed",0) or 0))}'
            f'{_num_cell(int(g.get("stamina",0) or 0))}'
            f'{_num_cell(int(g.get("power",0) or 0))}'
            f'{_num_cell(int(g.get("guts",0) or 0))}'
            f'{_num_cell(int(g.get("wiz",0) or 0))}'
            f'{_num_cell(int(g.get("skill_pts",0) or 0))}'
            f'{hint_cell}'
            f'</tr>'
        )
    # Totals row
    total_sp = sum(c["gains"]["skill_pts"] for c in d.contributions)
    total_hints = sum(c["hint_count"] for c in d.contributions)
    contrib_rows_html.append(
        f'<tr class="total">'
        f'<td></td>'
        f'<td>Total</td>'
        f'<td class="num">{_fmt(total_stats["speed"])}</td>'
        f'<td class="num">{_fmt(total_stats["stamina"])}</td>'
        f'<td class="num">{_fmt(total_stats["power"])}</td>'
        f'<td class="num">{_fmt(total_stats["guts"])}</td>'
        f'<td class="num">{_fmt(total_stats["wiz"])}</td>'
        f'<td class="num">{_fmt(total_sp)}</td>'
        f'<td class="num">{total_hints or "—"}</td>'
        f'</tr>'
    )

    # Hint cards — two-per-row grid (auto-fills wider). Tier column
    # dropped: pill color/border already conveys white vs gold vs
    # unique, so a separate tier label was pure redundancy. Sources
    # sit under the pill in a muted line so each card stays scannable.
    hint_rows_html: list[str] = []
    for h in d.hints:
        sources_labels = ", ".join(sorted({s["source"] for s in h["sources"]}))
        pill = _skill_pill_html(
            name=h["name"], icon_url=h.get("icon_url"),
            rarity=h.get("skill_rarity", 1),
        )
        lv_cls = "hint-lv"
        if h["total_level"] >= 5:
            lv_cls += " hint-lv-max"
        hint_rows_html.append(
            f'<div class="hint-card">'
            f'  <div class="hint-main">{pill}'
            f'    <span class="{lv_cls}" title="Total hint level across all sources">'
            f'Lv {h["total_level"]}</span>'
            f'  </div>'
            f'  <div class="hint-sources">{sources_labels}</div>'
            f'</div>'
        )
    if not hint_rows_html:
        hint_rows_html.append('<div class="hint-empty">No hints captured.</div>')

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

    # Factor rows — deduped per year with hit count. Each chip shows
    # 'Name  Nx' when a factor procced multiple times. Chips grouped
    # by category (stat → aptitude → green → skill → unique) so the
    # whole year's mix reads coherently at a glance.
    factor_rows_html: list[str] = []
    for y in d.factors_by_year:
        chip_parts = []
        for f in y["factors"]:
            hits_badge = f' <b>{f["hits"]}×</b>' if f["hits"] > 1 else ""
            chip_parts.append(
                f'<span class="chip factor-{f["type_label"]}" '
                f'title="factor_id {f["factor_id"]} · hit {f["hits"]}x">'
                f'{f["name"]}{hits_badge}'
                f'</span>'
            )
        # Year-1 pre-run aptitude affinity is dropped entirely from
        # display (see _build_lineage: aptitudes AND uniques in year 1
        # aren't real sparks — aptitudes go pre-run, uniques are
        # guaranteed auto-inherits from direct parents). The stored
        # preroll list is available on the RunDetail dict if we want
        # to surface it later, but it clutters the year-1 view without
        # helping anyone plan.
        total_hits = sum(f["hits"] for f in y["factors"])
        factor_rows_html.append(
            f'<tr><td>Year {y["year"]}</td>'
            f'<td class="num">{total_hits}</td>'
            f'<td>{"".join(chip_parts)}</td></tr>'
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

        def rank_badge(rank: int) -> str:
            """Render a rank as its letter grade + badge icon (falls
            back to the letter text if the icon isn't in our set)."""
            letter = letter_grade(rank)
            icon = grade_icon_url(letter)
            if icon:
                return (f'<span class="rank-badge">'
                        f'<img src="{icon}" alt="{letter}" title="rank {rank}" '
                        f'loading="lazy" onerror="this.replaceWith('
                        f'document.createTextNode(\'{letter}\'))">'
                        f'<span class="rank-num">rank {rank}</span></span>')
            return (f'<span class="rank-badge"><b>{letter}</b>'
                    f'<span class="rank-num">rank {rank}</span></span>')

        score_table = (
            '<table>\n<thead><tr>'
            '<th>Component</th><th class="num">Score</th><th>Notes</th>'
            '</tr></thead><tbody>'
            f'<tr><td>Stats (5-stat curve)</td><td class="num">{fnum(ss["stat_score"])}</td>'
            f'<td>from FiveStatusFinalScore lookup</td></tr>'
            f'<tr><td>Owned skills</td><td class="num">{fnum(ss["owned_skill_score"])}</td>'
            f'<td>sum of grade_value for skills you already have</td></tr>'
            f'<tr class="total"><td>Floor (no more SP spent)</td>'
            f'<td class="num">{fnum(ss["floor"])}</td>'
            f'<td>{rank_badge(ss["rank_floor"])}</td></tr>'
            f'<tr><td>+ Optimal SP spend</td>'
            f'<td class="num">+{fnum(ss["planned_score"] - ss["floor"])}</td>'
            f'<td>{ss["sp_spent_in_plan"]}/{ss["unspent_sp"]} SP used '
            f'({len(d.plan)} skills)</td></tr>'
            f'<tr class="total"><td>Planned score (knapsack ceiling)</td>'
            f'<td class="num">{fnum(ss["planned_score"])}</td>'
            f'<td>{rank_badge(ss["rank_planned"])}</td></tr>'
            f'<tr><td>Naive ceiling (2.0×SP)</td>'
            f'<td class="num">{fnum(ss["naive_ceiling"])}</td>'
            f'<td>flat conversion, overstates by '
            f'{fnum(ss["naive_ceiling"] - ss["planned_score"])}</td></tr>'
            '</tbody></table>'
        )
    else:
        score_table = '<p class="subtle">Score estimator produced no result for this capture.</p>'

    # Plan rows — each skill rendered as an inert pill (icon + name)
    # in the first cell. Gold-upgrade rows have a subtle indent + tint
    # so pairing with the preceding white reads at a glance.
    plan_rows_html: list[str] = []
    for p in d.plan:
        pill = _skill_pill_html(
            name=p["name"], icon_url=p.get("icon_url"),
            rarity=p.get("rarity", 1),
        )
        indent = ""
        row_style = ""
        if p.get("is_gold_upgrade"):
            indent = ('<span style="color: var(--muted); '
                      'font-family: ui-monospace; margin-right: 6px;">└→</span>')
            row_style = ' style="background: color-mix(in srgb, #ffea54 6%, transparent);"'
        # SP cell shows discounted cost; if a hint level applied,
        # add a subtle "was Nsp · hint Lv X" annotation so the
        # discount is visible without extra columns.
        base = int(p.get("base_sp_cost") or 0)
        lv = int(p.get("hint_level") or 0)
        cost = int(p.get("sp_cost") or 0)
        if lv > 0 and base > cost:
            sp_cell = (
                f'{cost}<span class="sp-hint" title="Base {base} SP → '
                f'{cost} SP (hint Lv {lv}, {lv*10}% off)">'
                f' <s>{base}</s></span>'
            )
        else:
            sp_cell = str(cost)
        plan_rows_html.append(
            f'<tr{row_style}>'
            f'<td>{indent}{pill}</td>'
            f'<td class="num">{sp_cell}</td>'
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

    lineage_panel = _render_lineage_panel(getattr(d, "lineage", None))

    # Quick-stats sidebar block — compact key/value pairs for this run.
    # Kept tight (labels UPPERCASE small, values tabular-num right-aligned,
    # ellipsis on overflow) so a long trainee/scenario name doesn't wrap.
    sidebar_stats = "".join([
        f'<div class="stat"><span class="stat-label">Trainee</span>'
        f'<span class="stat-value" title="{d.trainee_name}">{d.trainee_name}</span></div>',
        f'<div class="stat"><span class="stat-label">Scenario</span>'
        f'<span class="stat-value" title="{d.scenario_name}">{d.scenario_name}</span></div>',
        f'<div class="stat"><span class="stat-label">5-stat</span>'
        f'<span class="stat-value">{sum(d.final_stats.values()):,}</span></div>',
        f'<div class="stat"><span class="stat-label">Fans</span>'
        f'<span class="stat-value">{d.fans:,}</span></div>',
        f'<div class="stat"><span class="stat-label">Races</span>'
        f'<span class="stat-value">{d.races_run}</span></div>',
    ])

    # Sidebar tab label — replaces the generic "Run detail" with a
    # human-readable identifier so multiple open detail pages can be
    # told apart at a glance. Timestamp is the run's short local time.
    ts = d.timestamp
    if len(ts) >= 13 and ts[8] == 'T':
        short_ts = f"{ts[4:6]}/{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
    else:
        short_ts = ts
    tab_label = f"{d.trainee_name} · {short_ts}"

    return (
        DETAIL_HTML
        .replace("__TITLE__", f"{d.trainee_name} · {d.timestamp}")
        .replace("__PORTRAIT__", portrait_html)
        .replace("__HEADER__", header)
        .replace("__SUBTITLE__", subtitle)
        .replace("__HEADER_STATS__", header_stats)
        .replace("__SIDEBAR_STATS__", sidebar_stats)
        .replace("__RUN_TAB_LABEL__", tab_label)
        .replace("__LINEAGE_PANEL__", lineage_panel)
        .replace("__CONTRIBUTIONS_ROWS__", "".join(contrib_rows_html))
        .replace("__HINT_ROWS__", "".join(hint_rows_html))
        .replace("__SCORE_TABLE__", score_table)
        .replace("__PLANNER_HTML__", planner_placeholder)
        .replace("__PLANNER_JS__", planner_js)
        .replace("__PLAN_ROWS__", "".join(plan_rows_html))
        .replace("__RACE_ROWS__", "".join(race_rows_html))
        .replace("__FACTOR_ROWS__", "".join(factor_rows_html))
    )


def _render_lineage_panel(lineage: dict | None) -> str:
    """Render the parent-compatibility panel from a RunDetail.lineage dict.

    ``lineage`` shape: ``{"parents": [ParentSummary-as-dict, ...],
    "overall": OverallCompat-as-dict}``. Returns an empty string (i.e. no
    panel) for pre-v0.1.5 runs that don't carry parent data.
    """
    if not lineage:
        return (
            '<div class="lineage-panel lineage-missing">'
            '<div class="lineage-header">'
            '<span class="compat-big compat-0">?</span>'
            '<h2>Parent lineage compatibility</h2>'
            '</div>'
            '<p class="no-lineage">'
            'Parent data was not captured for this run. IT captures cannot be '
            'redone after the fact, so this run\'s ancestry (and its ◎/○/△ '
            'compat symbol) is permanently unavailable. Later captures made '
            'with extractor <b>v0.1.5+</b> will include full lineage + '
            'per-pair breakdown here.'
            '</p></div>'
        )
    overall = lineage.get("overall") or {}
    parents = lineage.get("parents") or []
    if not parents or not overall:
        return ""

    symbol = overall.get("symbol", "?")
    rank = overall.get("rank", 0)
    total = overall.get("total_points", 0)
    pairs = overall.get("pairs") or []
    sparked_count = lineage.get("sparked_count", 0)

    parts = [
        '<div class="lineage-panel">',
        '<div class="lineage-header">',
        f'<span class="compat-big compat-{rank}">{symbol}</span>',
        f'<h2>Parent lineage · spark potential</h2>',
        f'<span class="compat-total">{total} pts · '
        f'≤50 △ · 51–150 ○ · 151+ ◎  ·  {sparked_count} unique factors '
        f'proc\'d this run</span>',
        '</div>',
        '<div class="factor-legend">'
        '<span class="chip factor-stat sparked">sparked</span>'
        '<span class="chip factor-stat not-sparked">did not spark</span>'
        '  ·  All ancestor factors shown — sparked pills glow, '
        'un-sparked are faded. A factor sparks if <b>any</b> ancestor '
        'holding it proc\'d it this run.'
        '</div>',
        '<div class="lineage-tree">',
    ]
    for p in parents:
        portrait = (
            f'<img class="portrait" src="{p.get("portrait_url","")}" '
            f'alt="{p.get("name","")}" loading="lazy" '
            'onerror="this.style.display=\'none\'">'
            if p.get("portrait_url") else ''
        )
        parts.append('<div class="lineage-parent">')
        parts.append('<div class="lineage-parent-hdr">')
        parts.append(portrait)
        parts.append(f'<span class="name">{p.get("name","?")}</span>')
        parts.append(f'<span class="rank">Rank {p.get("rank",0)}</span>')
        parts.append('</div>')
        parts.append(
            '<div class="lineage-stats">'
            f'Spd {p.get("speed",0):,} · '
            f'Sta {p.get("stamina",0):,} · '
            f'Pow {p.get("power",0):,} · '
            f'Gts {p.get("guts",0):,} · '
            f'Wis {p.get("wiz",0):,}  ·  '
            f'{p.get("fans",0):,} fans'
            '</div>'
        )
        parts.append(_render_factor_pills(p.get("factors") or []))
        gps = p.get("grandparents") or []
        if gps:
            parts.append('<div class="lineage-gp-block">')
            parts.append('<div class="gp-title">grandparents</div>')
            parts.append('<div class="lineage-gp">')
            for gp in gps:
                gp_portrait = (
                    f'<img class="portrait" src="{gp.get("portrait_url","")}" '
                    f'alt="{gp.get("name","")}" loading="lazy" '
                    'onerror="this.style.display=\'none\'">'
                    if gp.get("portrait_url") else ''
                )
                parts.append('<div class="gp">')
                parts.append('<div class="gp-hdr">')
                parts.append(gp_portrait)
                parts.append(f'<span class="gp-name">{gp.get("name","?")}</span>')
                parts.append(f'<span class="gp-rank">Rank {gp.get("rank",0)}</span>')
                parts.append('</div>')
                parts.append(_render_factor_pills(gp.get("factors") or []))
                parts.append('</div>')  # /.gp
            parts.append('</div>')  # /.lineage-gp
            parts.append('</div>')  # /.lineage-gp-block
        parts.append('</div>')  # /.lineage-parent
    parts.append('</div>')  # /.lineage-tree

    parts.extend([
        '<div class="compat-breakdown">',
        '<table><thead><tr>',
        '<th>Pair</th><th class="num">Base</th>',
        '<th class="num">Shared G1</th><th class="num">Bonus</th>',
        '<th class="num">Total</th></tr></thead><tbody>',
    ])
    for p in pairs:
        parts.append(
            '<tr>'
            f'<td class="pair-label">{p.get("label","")}</td>'
            f'<td class="num">{p.get("base_points",0)}</td>'
            f'<td class="num">{p.get("g1_overlap_count",0)}</td>'
            f'<td class="num">+{p.get("g1_bonus",0)}</td>'
            f'<td class="num">{p.get("total",0)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    parts.append('</div>')  # /.lineage-panel
    return "\n".join(parts)


def _render_factor_pills(factors: list[dict]) -> str:
    """Compact factor-chip row for a parent or grandparent. Sparked
    factors bubble to the front (already sorted upstream) and get a
    subtle glow; un-sparked ones fade to background."""
    if not factors:
        return '<div class="lineage-factors"><span class="no-lineage">no factors</span></div>'
    parts = ['<div class="lineage-factors">']
    for f in factors:
        cls = f'chip factor-{f.get("type_label","unknown")} '
        cls += 'sparked' if f.get("sparked") else 'not-sparked'
        title = (f'factor_id {f.get("factor_id","?")} · '
                 f'{"proc\'d this run" if f.get("sparked") else "did not proc"}')
        parts.append(f'<span class="{cls}" title="{title}">{f.get("name","?")}</span>')
    parts.append('</div>')
    return "".join(parts)

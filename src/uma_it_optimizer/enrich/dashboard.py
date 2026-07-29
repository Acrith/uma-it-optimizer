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
/* Palette: dark-first, umaladder-inspired deep navy with warm pink
   primary + gold secondary. Light mode kept as a first-class theme
   with a proper neutral hover (not pink-on-pink). A data-theme attr
   on <html> lets the toggle override the OS preference. */
:root {
    color-scheme: dark light;
    /* Dark (default) */
    --bg: #10131c;
    --bg-2: #171b28;
    --bg-3: #202538;
    --fg: #e8eaf2;
    --muted: #8a90a6;
    --border: #262c42;
    --row-alt: #181c2a;
    --hover: #232a42;
    --accent: #ff5c9b;
    --accent-2: #ffb454;
    --accent-decks: #ff5c9b;
    --accent-runs: #62b0ff;
    --accent-lineage: #47c95c;
    --shadow: 0 4px 16px rgba(0,0,0,0.4);
    --shadow-lg: 0 12px 32px rgba(0,0,0,0.55);
    --radius: 8px;
}
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
        --bg: #f4f2f6;
        --bg-2: #ffffff;
        --bg-3: #ffffff;
        --fg: #1a1a1a;
        --muted: #666;
        --border: #e0dce6;
        --row-alt: #faf7fc;
        --hover: #edeaf3;       /* neutral gray-purple, not pink-on-pink */
        --accent: #e5307c;
        --shadow: 0 4px 16px rgba(0,0,0,0.08);
        --shadow-lg: 0 12px 32px rgba(0,0,0,0.12);
    }
}
/* Manual light override — takes precedence over system dark */
:root[data-theme="light"] {
    color-scheme: light;
    --bg: #f4f2f6;
    --bg-2: #ffffff;
    --bg-3: #ffffff;
    --fg: #1a1a1a;
    --muted: #666;
    --border: #e0dce6;
    --row-alt: #faf7fc;
    --hover: #edeaf3;
    --accent: #e5307c;
    --shadow: 0 4px 16px rgba(0,0,0,0.08);
    --shadow-lg: 0 12px 32px rgba(0,0,0,0.12);
}
* { box-sizing: border-box; }
body {
    margin: 0;
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--fg);
    min-height: 100vh;
}
/* App shell: sidebar rail + main scroll area. Sidebar carries the
   brand mark, section nav, and quick stats — keeps the main area
   free for content. */
.app {
    display: grid;
    /* minmax(0, 1fr) so a wide table inside .main can't force the
       grid track to expand past the viewport — the .table-wrap
       handles horizontal scroll instead of the whole page. */
    grid-template-columns: 220px minmax(0, 1fr);
    min-height: 100vh;
}
.sidebar {
    background: var(--bg-2);
    border-right: 1px solid var(--border);
    padding: 24px 16px;
    position: sticky; top: 0;
    height: 100vh;
    overflow-y: auto;
    display: flex; flex-direction: column; gap: 20px;
}
.sidebar-brand {
    display: flex; flex-direction: column; gap: 2px;
    padding: 0 6px;
}
.brand-row { display: flex; align-items: center; gap: 8px; }
.theme-toggle {
    margin-left: auto;
    background: var(--bg-3); border: 1px solid var(--border);
    color: var(--fg); cursor: pointer;
    width: 28px; height: 28px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 13px; padding: 0;
    transition: all 0.15s;
}
.theme-toggle:hover { border-color: var(--accent); transform: scale(1.08); }
.theme-toggle .theme-icon-light { display: none; }
:root[data-theme="light"] .theme-toggle .theme-icon-light { display: inline; }
:root[data-theme="light"] .theme-toggle .theme-icon-dark { display: none; }
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) .theme-toggle .theme-icon-light { display: inline; }
    :root:not([data-theme="dark"]) .theme-toggle .theme-icon-dark { display: none; }
}
.sidebar-brand .brand-mark {
    font-size: 18px; font-weight: 700; letter-spacing: -0.01em;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    -webkit-background-clip: text; background-clip: text;
    color: transparent;
}
.sidebar-brand .brand-sub {
    color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.08em;
}
.side-nav { display: flex; flex-direction: column; gap: 2px; }
.side-nav a {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px;
    color: var(--muted);
    text-decoration: none;
    border-radius: 6px;
    font-weight: 500;
    transition: background 0.12s, color 0.12s;
}
.side-nav a:hover { background: var(--hover); color: var(--fg); }
.side-nav a.active {
    background: var(--bg-3);
    color: var(--accent);
    box-shadow: inset 3px 0 0 var(--accent);
}
.side-nav .nav-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: currentColor; opacity: 0.85;
}
.side-nav a[data-section="decks"] .nav-dot { color: var(--accent-decks); }
.side-nav a[data-section="runs"] .nav-dot { color: var(--accent-runs); }
.side-nav a[data-section="analytics"] .nav-dot { color: var(--accent-lineage); }
.side-nav a[data-section^="run:"] .nav-dot { color: var(--accent-lineage); }
.side-nav a.dynamic-tab {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 4px 6px 10px;
    line-height: 1.25;
}
.side-nav a.dynamic-tab .tab-body {
    flex: 1; min-width: 0;
    display: flex; flex-direction: column; gap: 2px;
}
.side-nav a.dynamic-tab .tab-line1 {
    font-size: 12px; font-weight: 600;
    color: inherit;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.side-nav a.dynamic-tab .tab-line2 {
    font-size: 10px;
    color: var(--muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.side-nav a.dynamic-tab.active .tab-line2 { color: color-mix(in srgb, var(--accent-lineage) 75%, var(--muted)); }
.side-nav a.dynamic-tab .tab-close {
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px;
    background: none; border: 0; padding: 0; margin: 0;
    color: var(--muted); cursor: pointer;
    border-radius: 3px;
    font-size: 14px; line-height: 1;
    flex-shrink: 0;
}
.side-nav a.dynamic-tab .tab-close:hover {
    background: color-mix(in srgb, #d43f3f 20%, transparent);
    color: #ff8080;
}
.run-panel-frame {
    width: 100%;
    min-height: calc(100vh - 48px);
    border: 0;
    display: block;
    background: var(--bg);
}
.side-quick {
    margin-top: auto;
    padding: 10px 12px;
    background: var(--bg-3);
    border-radius: var(--radius);
    display: flex; flex-direction: column; gap: 4px;
    font-size: 11px;
    min-width: 0;
}
.side-quick .stat {
    display: flex; flex-direction: row;
    justify-content: space-between; align-items: center;
    gap: 8px;
    min-width: 0;
    line-height: 1.35;
}
.side-quick .stat-label {
    color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.04em; font-size: 9px;
    flex-shrink: 0;
}
.side-quick .stat-value {
    color: var(--fg); font-weight: 700;
    font-variant-numeric: tabular-nums;
    font-size: 12px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    min-width: 0; text-align: right;
}

.main {
    padding: 24px 32px 48px;
    min-width: 0;    /* let table-wrap scroll instead of expanding grid */
}
.main .card-panel {
    /* Panels honor the viewport width; the .table-wrap inside handles
       overflow-x so wide tables scroll horizontally without breaking
       out of the panel. overflow-hidden here would clip the table-wrap's
       scrollbar — leave it unset so the inner wrap's overflow-x wins. */
    max-width: 100%;
}
h1 {
    margin: 0 0 4px;
    font-size: 22px;
    letter-spacing: -0.01em;
    display: flex; align-items: center; gap: 10px;
}
h1::before {
    content: ""; display: inline-block;
    width: 4px; height: 22px;
    background: var(--section-accent, var(--accent));
    border-radius: 3px;
}
.subtitle { color: var(--muted); margin-bottom: 24px; font-size: 13px; }

/* Inactive panels stay in the DOM but positioned off-screen so
   iframes inside them keep their scroll position (display:none can
   reset iframe scrollY in some browsers). aria-hidden keeps screen
   readers on the same page. */
section.panel {
    position: absolute;
    left: -99999px;
    top: 0;
    width: 1px; height: 1px;
    overflow: hidden;
    visibility: hidden;
}
section.panel.active {
    position: static;
    left: auto; top: auto;
    width: auto; height: auto;
    overflow: visible;
    visibility: visible;
}
/* Panel-scoped accent so headers, chips, links, badges all inherit */
section.panel[data-section="decks"]     { --section-accent: var(--accent-decks); }
section.panel[data-section="runs"]      { --section-accent: var(--accent-runs); }
section.panel[data-section="analytics"] { --section-accent: var(--accent-lineage); }

.stats {
    display: flex;
    gap: 20px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.stat { display: flex; flex-direction: column; }
.stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.05em; }
.stat-value {
    font-size: 20px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--fg);
}
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
    display: flex; align-items: center; gap: 8px;
}
h2::before {
    content: ""; display: inline-block;
    width: 3px; height: 14px;
    background: var(--section-accent, var(--accent));
    border-radius: 2px;
}
h2 .subtle { color: var(--muted); font-size: 12px; font-weight: 400; text-transform: none; letter-spacing: 0; }
/* Content panels — subtle bordered surface so sections feel like
   discrete units instead of one long scroll. */
.card-panel {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
}
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
/* Type composition chips — colored to match the type icons (boot=Speed,
   heart=Stamina, bicep=Power, flame=Guts, grad=Wit, smiley=Friend). */
.chip.type-Speed   { background: #3a7bff; color: white; }
.chip.type-Stamina { background: #e64545; color: white; }
.chip.type-Power   { background: #ff8f30; color: white; }
.chip.type-Guts    { background: #e94494; color: white; }
.chip.type-Wit     { background: #37b34a; color: white; }
.chip.type-Friend  { background: #f5c942; color: #6a4600; }
.chip.type-Group   { background: #6bc38a; color: #10441e; }
.chip.type-\?      { background: var(--row-alt); color: var(--muted); }
/* Deck-hash link that jumps to the All Runs table filtered to that hash */
.deck-hash-link {
    background: none; border: 0; padding: 0;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 10px; color: var(--muted);
    cursor: pointer; vertical-align: middle;
    text-decoration: underline dotted;
}
.deck-hash-link:hover { color: var(--accent); }
/* Whole deck row is clickable — drills into the All Runs table
   filtered to that deck. The hint chip clarifies the affordance so
   users don't hunt for the small hash link. */
tr.deck-row, tr.run-row { cursor: pointer; transition: background 0.12s; }
tr.deck-row:hover, tr.run-row:hover { background: var(--hover) !important; }
/* Open pill — one canonical style, one canonical placement (last
   column, right-aligned), one canonical reveal (row hover). Applied
   to both Decks and Runs tables so drill-down affordance reads
   identically in both. */
.open-pill {
    display: inline-flex; align-items: center; gap: 3px;
    font-size: 10px; font-weight: 700;
    padding: 3px 10px; border-radius: 10px;
    background: var(--accent); color: white;
    text-transform: uppercase; letter-spacing: 0.04em;
    text-decoration: none;
    white-space: nowrap;
    transition: filter 0.12s, transform 0.12s;
}
.open-pill:hover {
    filter: brightness(1.1);
    transform: translateY(-1px);
    text-decoration: none;
}
th.open-col, td.open-cell {
    width: 1%;
    text-align: right;
    padding-right: 12px;
}
/* Only reveal the pill on row hover. Rows always keep the column
   width so hovering doesn't shift other cells around. */
tr.hover-open .open-pill {
    opacity: 0;
    transform: translateX(-4px);
    transition: opacity 0.12s, transform 0.12s;
    pointer-events: none;
}
tr.hover-open:hover .open-pill {
    opacity: 1;
    transform: translateX(0);
    pointer-events: auto;
}
/* Deck-perf filter panel — capped narrow so it doesn't sprawl on a
   wide viewport. The card-picker grid is allowed to break past the
   cap when open so more thumbnails fit at once. */
.deck-filter-panel {
    background: var(--bg-3);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 12px;
    display: flex; flex-direction: column; gap: 10px;
    max-width: 720px;
    box-shadow: var(--shadow);
}
.deck-filter-panel .card-picker { max-width: none; }
.deck-filter-panel .filter-row + .filter-row-actions { border-top-color: var(--border); }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-row-actions { border-top: 1px dashed var(--border); padding-top: 8px; }
.filter-label {
    color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em;
    min-width: 70px;
}
.filter-hint {
    color: var(--muted); font-size: 12px; font-style: italic;
    display: inline-flex; align-items: center; gap: 4px;
}
.filter-hint::before {
    content: "→"; color: var(--accent); font-weight: 700; font-style: normal;
}
.chip-set { display: flex; gap: 4px; flex-wrap: wrap; }
.chip-set .filter-chip {
    background: var(--bg-2); color: var(--fg);
    border: 1px solid var(--border);
    padding: 4px 12px; border-radius: 14px;
    font-size: 12px; font-weight: 500; cursor: pointer;
    user-select: none; transition: all 0.15s;
    display: inline-flex; align-items: center; gap: 4px;
}
.chip-set .filter-chip::before {
    content: ""; display: inline-block;
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--border);
    transition: background 0.15s;
}
.chip-set .filter-chip:hover {
    color: var(--fg); border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 8%, var(--bg-2));
}
.chip-set .filter-chip.active {
    background: var(--accent); color: white; border-color: var(--accent);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
}
.chip-set .filter-chip.active::before { background: white; }
.chip-set .filter-chip.disabled {
    opacity: 0.4; cursor: not-allowed;
    background: var(--bg); border-style: dashed;
}
.chip-set .filter-chip.disabled::before { display: none; }
.chip-set .filter-chip.disabled:hover {
    color: var(--muted); border-color: var(--border);
    background: var(--bg);
}

.card-chips { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; flex: 1; }
.card-chips .picked-card {
    display: inline-flex; align-items: center; gap: 4px;
    background: var(--bg);
    border: 1px solid var(--accent);
    padding: 2px 8px 2px 4px; border-radius: 4px;
    font-size: 11px;
}
.card-chips .picked-card img {
    height: 20px; width: 16px; object-fit: cover; border-radius: 2px;
}
.card-chips .picked-card .remove {
    background: none; border: 0; color: var(--muted); cursor: pointer;
    padding: 0 2px; font-size: 14px; line-height: 1;
}
.card-chips .picked-card .remove:hover { color: #d43f3f; }

.pill-btn {
    background: var(--accent); border: 1px solid var(--accent);
    color: white; padding: 6px 14px; border-radius: 14px;
    font: inherit; font-size: 12px; font-weight: 600;
    cursor: pointer;
    display: inline-flex; align-items: center; gap: 4px;
    transition: all 0.15s;
    box-shadow: 0 2px 6px color-mix(in srgb, var(--accent) 30%, transparent);
}
.pill-btn:hover {
    background: color-mix(in srgb, var(--accent) 85%, black);
    box-shadow: 0 3px 10px color-mix(in srgb, var(--accent) 45%, transparent);
    transform: translateY(-1px);
}
.pill-btn[aria-expanded="true"] {
    background: var(--bg-2); color: var(--accent); border-color: var(--accent);
    box-shadow: inset 0 0 0 2px var(--accent);
    transform: none;
}
.link-btn {
    background: none; border: 0; padding: 2px 6px;
    color: var(--accent); font: inherit; font-size: 12px;
    cursor: pointer; text-decoration: underline dotted;
}
.link-btn:hover { text-decoration: underline; }
.toggle { color: var(--muted); font-size: 12px; margin-left: auto; }
.toggle input { margin-right: 4px; }

/* Card picker floats above the page instead of pushing the deck
   table down. Anchored top-right of the deck-filter-panel so it
   lands under the '+ Add card' button. */
.deck-filter-panel { position: relative; }
.card-picker {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 20;
    width: 640px;
    max-width: 90vw;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: 6px;
    padding: 12px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}
@media (prefers-color-scheme: dark) {
    .card-picker { box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
}
.card-picker-hdr { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.card-picker-hdr input[type="search"] { flex: 1; }
.card-picker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
    gap: 8px;
    max-height: 360px;
    overflow-y: auto;
}
.pick-card {
    position: relative; cursor: pointer;
    border: 2px solid transparent;
    border-radius: 4px;
    transition: all 0.1s;
    padding: 3px;
    text-align: center;
}
.pick-card:hover { border-color: var(--accent); }
.pick-card.selected {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 15%, transparent);
}
.pick-card img.pick-thumb {
    width: 100%; height: auto; aspect-ratio: 32/42;
    object-fit: cover; border-radius: 3px; display: block;
}
.pick-card .pick-name {
    font-size: 10px; margin-top: 2px;
    color: var(--fg);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pick-card.hidden { display: none; }

.deck-footer {
    padding: 8px 12px; text-align: center;
    color: var(--muted); font-size: 11px;
    border-top: 1px dashed var(--border);
}
/* Parent-compat cell: colored ◎/○/△ symbol + optional total-points hint */
.compat-cell { white-space: nowrap; }
.compat-symbol { font-size: 15px; font-weight: 700; margin-right: 4px; }
.compat-symbol.compat-3 { color: #ff8a00; }  /* ◎ great — rainbow tier */
.compat-symbol.compat-2 { color: #58a6ff; }  /* ○ good */
.compat-symbol.compat-1 { color: #b96e6e; }  /* △ poor */
.compat-symbol.compat-0 { color: var(--muted); font-weight: normal; }
.compat-pts { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.compat-missing {
    font-size: 10px; color: #b8860b;
    background: rgba(184, 134, 11, 0.12);
    padding: 2px 6px; border-radius: 3px;
    border: 1px dashed rgba(184, 134, 11, 0.5);
    white-space: nowrap;
    cursor: help;
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
.preset-badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    cursor: pointer;
    user-select: none;
}
.preset-badge:hover { filter: brightness(1.1); box-shadow: 0 0 0 1px var(--accent); }
.preset-high { background: #ff8f30; color: white; }         /* inferred, high confidence */
.preset-low  { background: var(--row-alt); color: var(--muted); font-style: italic; }
.preset-override { background: #4f8fef; color: white; font-style: normal; }  /* player set */
@media (prefers-color-scheme: dark) {
    .preset-high { background: #d97010; }
    .preset-override { background: #3672cc; }
}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
    <div class="sidebar-brand">
        <div class="brand-row">
            <span class="brand-mark">uma-it-optimizer</span>
            <button id="theme-toggle" class="theme-toggle" title="Toggle theme" aria-label="Toggle theme">
                <span class="theme-icon-dark">🌙</span>
                <span class="theme-icon-light">☀️</span>
            </button>
        </div>
        <span class="brand-sub">Independent Training</span>
    </div>
    <nav class="side-nav" id="side-nav">
        <a href="#decks" data-section="decks" class="active"><span class="nav-dot"></span>Decks</a>
        <a href="#runs" data-section="runs"><span class="nav-dot"></span>Runs</a>
        <div id="side-nav-runs"></div>
    </nav>
    <div class="side-quick" id="side-quick" data-scope="dashboard">__STATS_HTML__</div>
</aside>

<main class="main">
<section class="panel active" id="decks-panel" data-section="decks">
<h1>Deck performance</h1>
<div class="subtitle">__SUBTITLE__ — completed runs only. Click a column to sort.</div>

<div class="card-panel">
<div class="deck-filter-panel">
    <div class="filter-row">
        <span class="filter-label">Cards</span>
        <div class="card-chips" id="deck-card-chips">
            <span class="filter-hint">none — click "+" to add a card filter</span>
        </div>
        <button class="pill-btn" id="deck-card-add-btn" aria-expanded="false">＋ Add card</button>
    </div>
    <div class="filter-row">
        <span class="filter-label">Scenario</span>
        <span class="chip-set" id="deck-scenario-set"></span>
    </div>
    <div class="filter-row filter-row-actions">
        <button class="link-btn" id="deck-clear">× Reset filters</button>
        <label class="toggle">
            <input type="checkbox" id="deck-expand">
            Show all decks (default: top 10)
        </label>
    </div>
    <div class="card-picker" id="deck-card-picker" hidden>
        <div class="card-picker-hdr">
            <input type="search" id="deck-card-search" placeholder="Search cards by name…">
            <button class="link-btn" id="deck-card-close">Close</button>
        </div>
        <div class="card-picker-grid" id="deck-card-grid"></div>
    </div>
</div>
</div>
<div class="card-panel">
<div class="table-wrap">
<table id="decks">
    <thead>
        <tr>
            <th data-key="deck_hash"     data-type="text">Deck</th>
            <th data-key="type_label"    data-type="text">Types</th>
            <th data-key="trainees_label" data-type="text">Trainees</th>
            <th data-key="scenarios_label" data-type="text">Scenarios</th>
            <th data-key="runs"          data-type="num">Runs</th>
            <th data-key="best_score"    data-type="num" title="Best planned score across runs of this deck">Best Score</th>
            <th data-key="avg_score"     data-type="num" title="Average planned score across runs of this deck">Avg Score</th>
            <th data-key="best_rank"     data-type="num" title="Grade range: worst floor → best ceiling across runs">Grade</th>
            <th data-key="best_stat_sum" data-type="num">Best 5-Stat</th>
            <th data-key="avg_unspent_sp" data-type="num">Avg SP</th>
            <th data-key="best_fans"     data-type="num">Best Fans</th>
            <th class="open-col"></th>
        </tr>
    </thead>
    <tbody id="decks-body"></tbody>
</table>
<div class="deck-footer" id="deck-footer"></div>
</div>
</div>
</section>

<section class="panel" id="runs-panel" data-section="runs">
<h1>All runs</h1>
<div class="subtitle">Every completed capture, sortable and filterable.</div>

<div class="card-panel">
<div class="controls">
    <input type="search" id="filter" placeholder="Filter (deck#, trainee, scenario, ...)">
</div>

<div class="table-wrap">
<table id="runs">
    <thead>
        <tr>
            <th data-key="timestamp"     data-type="text">Date</th>
            <th data-key="trainee_name"  data-type="text">Trainee</th>
            <th data-key="scenario_name" data-type="text">Scenario</th>
            <th data-key="inferred_preset" data-type="text" title="Heuristic guess at IT preset from stat pattern — Stamina is high-confidence when stamina > 850; everything else defaults to Balanced?">Preset</th>
            <th data-key="deck_hash"     data-type="text">Deck</th>
            <th data-key="score_ceiling" data-type="num" title="Estimated SS-grade score at knapsack-optimal SP spend">Score</th>
            <th data-key="letter_grade"  data-type="text" title="Letter grade range from rank tier">Grade</th>
            <th data-key="compat_rank"   data-type="num" title="Parent lineage compatibility — ◎ / ○ / △ from succession_relation + G1 overlap. Hover for breakdown.">Compat</th>
            <th data-key="stat_sum"      data-type="num">5-Stat</th>
            <th data-key="speed"         data-type="num">Spd</th>
            <th data-key="stamina"       data-type="num">Sta</th>
            <th data-key="power"         data-type="num">Pow</th>
            <th data-key="guts"          data-type="num">Gts</th>
            <th data-key="wiz"           data-type="num">Wis</th>
            <th data-key="unspent_sp"    data-type="num">SP</th>
            <th data-key="races_run"     data-type="num">Races</th>
            <th data-key="fans"          data-type="num">Fans</th>
            <th data-key="skill_hints_available" data-type="num">Hints</th>
            <th class="open-col"></th>
        </tr>
    </thead>
    <tbody id="runs-body"></tbody>
</table>
</div>
</div>
</section>

<div id="run-panels"></div>
</main>
</div>

<script>
// Theme toggle — persists in localStorage, overrides OS preference.
// Runs before section nav so the initial paint uses the right theme.
// Broadcasts to all embedded iframes so run details stay in sync.
(function () {
    const STORAGE_KEY = "uma_it_theme";
    function broadcastToIframes(theme) {
        document.querySelectorAll("iframe.run-panel-frame").forEach(f => {
            try { f.contentWindow.postMessage({type: "theme", value: theme}, "*"); }
            catch (_) {}
        });
    }
    function apply(theme) {
        if (theme === "light" || theme === "dark") {
            document.documentElement.dataset.theme = theme;
        } else {
            delete document.documentElement.dataset.theme;
        }
        broadcastToIframes(theme);
    }
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) apply(stored);
    const btn = document.getElementById("theme-toggle");
    if (btn) {
        btn.addEventListener("click", () => {
            const current = document.documentElement.dataset.theme
                || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
            const next = current === "dark" ? "light" : "dark";
            localStorage.setItem(STORAGE_KEY, next);
            apply(next);
        });
    }
    // Also sync every newly-loaded iframe to the current theme.
    window.__syncIframeTheme = (iframe) => {
        const theme = document.documentElement.dataset.theme || null;
        const send = () => {
            try { iframe.contentWindow.postMessage({type: "theme", value: theme}, "*"); }
            catch (_) {}
        };
        if (iframe.contentDocument?.readyState === "complete") send();
        else iframe.addEventListener("load", send, {once: true});
    };
})();

// Section nav — swap active panel + accent scope. Also manages
// dynamic run-detail tabs: opening a run adds a sidebar entry with an
// × close button, clicking Decks/Runs doesn't close it, and multiple
// runs can be open simultaneously.
(function () {
    const nav = document.getElementById("side-nav");
    const dynNav = document.getElementById("side-nav-runs");
    const runPanels = document.getElementById("run-panels");
    if (!nav) return;

    // openRuns: filename -> {label, detail_href, navEl, panelEl}
    const openRuns = new Map();

    // Save the initial dashboard-wide side-quick HTML so we can restore
    // it when the user switches back to a static (Decks/Runs) panel.
    const sideQuick = document.getElementById("side-quick");
    const dashboardStatsHTML = sideQuick.innerHTML;

    function fmtNumSafe(n) {
        return typeof n === "number" ? n.toLocaleString() : (n || "—");
    }

    function renderRunSidebarStats(row) {
        const grade = row.grade_ceiling_letter || row.grade_floor_letter || "—";
        const score = row.score_ceiling ? fmtNumSafe(row.score_ceiling) : "—";
        sideQuick.innerHTML = `
            <div class="stat"><span class="stat-label">Trainee</span>
                <span class="stat-value" title="${row.trainee_name}">${row.trainee_name}</span></div>
            <div class="stat"><span class="stat-label">Scenario</span>
                <span class="stat-value" title="${row.scenario_name}">${row.scenario_name}</span></div>
            <div class="stat"><span class="stat-label">Grade</span>
                <span class="stat-value">${grade}</span></div>
            <div class="stat"><span class="stat-label">Score</span>
                <span class="stat-value">${score}</span></div>
            <div class="stat"><span class="stat-label">5-stat</span>
                <span class="stat-value">${fmtNumSafe(row.stat_sum)}</span></div>
            <div class="stat"><span class="stat-label">Fans</span>
                <span class="stat-value">${fmtNumSafe(row.fans)}</span></div>
            <div class="stat"><span class="stat-label">Races</span>
                <span class="stat-value">${fmtNumSafe(row.races_run)}</span></div>
        `;
        sideQuick.dataset.scope = "run";
    }

    function restoreDashboardSidebarStats() {
        if (sideQuick.dataset.scope !== "dashboard") {
            sideQuick.innerHTML = dashboardStatsHTML;
            sideQuick.dataset.scope = "dashboard";
        }
    }

    // Per-section scroll memory. For static Decks/Runs we save the
    // main window's scrollY; for run tabs we save the iframe's own
    // scrollY (embedded pages scroll inside the iframe, not the outer
    // window). Switching in either direction restores both — outer
    // window position is per-section, iframe position is per-iframe.
    const scrollY = new Map();
    let currentSection = null;

    function saveScroll(section) {
        if (section === null) return;
        if (section.startsWith("run:")) {
            const filename = section.slice(4);
            const entry = openRuns.get(filename);
            if (entry) {
                try {
                    scrollY.set(section, entry.panelEl.querySelector("iframe").contentWindow.scrollY);
                } catch (_) { /* cross-frame access sometimes fails */ }
            }
        } else {
            scrollY.set(section, window.scrollY);
        }
    }

    function restoreScroll(section) {
        const target = scrollY.get(section) || 0;
        if (section.startsWith("run:")) {
            const filename = section.slice(4);
            const entry = openRuns.get(filename);
            if (!entry) return;
            const iframe = entry.panelEl.querySelector("iframe");
            const doRestore = () => {
                try { iframe.contentWindow.scrollTo(0, target); }
                catch (_) {}
            };
            // Defer to next frame so the panel's visibility toggle has
            // committed before we scroll — some browsers ignore
            // scrollTo on a still-invisible iframe.
            const kick = () => requestAnimationFrame(() =>
                requestAnimationFrame(doRestore));
            if (iframe.contentDocument?.readyState === "complete") {
                kick();
            } else {
                iframe.addEventListener("load", kick, {once: true});
            }
            window.scrollTo(0, 0);
        } else {
            window.scrollTo(0, target);
        }
    }

    function activate(section) {
        // Save current scroll before swapping.
        saveScroll(currentSection);
        nav.querySelectorAll("a").forEach(a => {
            a.classList.toggle("active", a.dataset.section === section);
        });
        // Static panels
        document.querySelectorAll("main > section.panel").forEach(p => {
            p.classList.toggle("active", p.dataset.section === section);
        });
        // Dynamic run panels
        runPanels.querySelectorAll("section.panel").forEach(p => {
            p.classList.toggle("active", p.dataset.section === section);
        });
        // (currentSection updated below after restoreScroll)
        // Contextual side-quick swap: run tab active → this run's stats;
        // otherwise → dashboard aggregate stats.
        if (section.startsWith("run:")) {
            const filename = section.slice(4);
            const row = DATA.find(r => r.filename === filename);
            if (row) renderRunSidebarStats(row);
        } else {
            restoreDashboardSidebarStats();
        }
        history.replaceState(null, "", "#" + section);
        currentSection = section;
        restoreScroll(section);
    }

    function shortTs(ts) {
        // 20260729T184907 → 07/29 18:49
        if (/^\d{8}T\d{6}$/.test(ts)) {
            return `${ts.slice(4,6)}/${ts.slice(6,8)} ${ts.slice(9,11)}:${ts.slice(11,13)}`;
        }
        return ts;
    }

    function tabGrade(row) {
        // Prefer the planned ceiling letter (with icon fallback logic
        // handled in the run detail); tabs just show the letter.
        return row.grade_ceiling_letter || row.grade_floor_letter || "";
    }

    // Scenario abbreviations for the tab's second line — the full name
    // still shows on hover via the title attribute.
    const SCENARIO_SHORT = {
        "URA Finale": "URA",
        "Unity Cup": "Unity",
        "Our Grand Concert": "GrandConcert",
        "Trackblazer": "MANT",
    };
    function shortScenario(name) {
        return SCENARIO_SHORT[name] || name;
    }
    function shortSP(sp) {
        if (typeof sp !== "number") return "—";
        if (sp >= 10000) return (sp / 1000).toFixed(1).replace(/\.0$/, "") + "k";
        return sp.toLocaleString();
    }

    function openRun(row) {
        const filename = row.filename;
        if (openRuns.has(filename)) {
            activate("run:" + filename);
            return;
        }
        if (!row.detail_href) return;
        const section = "run:" + filename;
        const line1 = `${row.trainee_name} · ${shortTs(row.timestamp)}`;
        const grade = tabGrade(row);
        const spStr = shortSP(row.unspent_sp);
        const line2Parts = [shortScenario(row.scenario_name)];
        if (grade) line2Parts.push(grade);
        line2Parts.push(`${spStr} SP`);
        const line2 = line2Parts.join(" · ");
        // Full metadata as hover title
        const fullLabel = `${row.trainee_name} · ${shortTs(row.timestamp)}\n${row.scenario_name} · ${grade || "—"} · ${row.unspent_sp?.toLocaleString() || "—"} SP`;

        // Sidebar entry — two-line label with × button
        const navEl = document.createElement("a");
        navEl.href = "#" + section;
        navEl.className = "dynamic-tab";
        navEl.dataset.section = section;
        navEl.dataset.filename = filename;
        navEl.title = fullLabel;
        navEl.innerHTML = `<span class="nav-dot"></span>
            <span class="tab-body">
              <span class="tab-line1">${line1}</span>
              <span class="tab-line2">${line2}</span>
            </span>
            <button class="tab-close" title="Close this run" aria-label="Close">×</button>`;
        dynNav.appendChild(navEl);

        // Panel — iframe pointed at detail_XXX.html?embed=1
        const panelEl = document.createElement("section");
        panelEl.className = "panel";
        panelEl.dataset.section = section;
        const iframe = document.createElement("iframe");
        iframe.className = "run-panel-frame";
        iframe.src = row.detail_href + "#embed";
        iframe.title = line1;
        panelEl.appendChild(iframe);
        runPanels.appendChild(panelEl);
        // Sync the initial theme once the iframe finishes loading.
        if (window.__syncIframeTheme) window.__syncIframeTheme(iframe);

        openRuns.set(filename, {label: line1, detail_href: row.detail_href, navEl, panelEl});
        activate(section);
    }

    function closeRun(filename) {
        const entry = openRuns.get(filename);
        if (!entry) return;
        const wasActive = entry.navEl.classList.contains("active");
        entry.navEl.remove();
        entry.panelEl.remove();
        openRuns.delete(filename);
        if (wasActive) activate("runs");
    }

    // Nav click routing
    nav.addEventListener("click", (e) => {
        const closeBtn = e.target.closest(".tab-close");
        if (closeBtn) {
            e.preventDefault();
            e.stopPropagation();
            const tab = closeBtn.closest(".dynamic-tab");
            const section = tab.dataset.section;
            const filename = section.slice(4);  // strip "run:"
            closeRun(filename);
            return;
        }
        const a = e.target.closest("a[data-section]");
        if (!a) return;
        e.preventDefault();
        activate(a.dataset.section);
    });

    // Delegated click on run rows — clicking anywhere on the row (not
    // just the Open pill) opens the run as an embedded tab.
    document.addEventListener("click", (e) => {
        // Don't intercept clicks on interactive descendants that have
        // their own handlers (deck-hash filter, preset badge, etc.)
        if (e.target.closest("button, a, input, .deck-hash-link, .preset-badge")) return;
        const rr = e.target.closest("tr.run-row[data-detail]");
        if (!rr) return;
        // Modified clicks fall through to browser default (open in new tab)
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) {
            window.open(rr.dataset.detail, "_blank", "noopener");
            return;
        }
        e.preventDefault();
        const row = DATA.find(r => r.filename === rr.dataset.filename);
        if (row) openRun(row);
    });

    // Message channel from embedded detail iframes: allow sidebar links
    // inside the detail page to switch the outer dashboard's panel.
    window.addEventListener("message", (e) => {
        const msg = e.data;
        if (!msg || msg.type !== "nav" || !msg.section) return;
        activate(msg.section);
    });

    const initial = (location.hash || "").replace(/^#/, "") || "decks";
    activate(initial);
})();
</script>
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
// Preset override state — persisted in localStorage keyed by run filename.
// The extractor can't capture which preset the player picked, so we show
// a heuristic guess and let the user correct it with a click. Overrides
// survive page reloads and dashboard regenerations.
const PRESET_OVERRIDE_KEY = "uma_it_preset_overrides_v1";
const PRESET_CYCLE = ["Balanced", "Stamina", "Sprint"];
function loadPresetOverrides() {
    try { return JSON.parse(localStorage.getItem(PRESET_OVERRIDE_KEY) || "{}"); }
    catch { return {}; }
}
function savePresetOverride(filename, value) {
    const all = loadPresetOverrides();
    if (value === null) delete all[filename]; else all[filename] = value;
    localStorage.setItem(PRESET_OVERRIDE_KEY, JSON.stringify(all));
}
function renderPresetBadge(r) {
    const overrides = loadPresetOverrides();
    const override = overrides[r.filename];
    const shown = override || r.inferred_preset;
    const cls = override ? "preset-override" : `preset-${r.inferred_preset_conf}`;
    const title = override
        ? `Set to '${override}' by you. Click to cycle (right-click to clear)`
        : `Inferred '${r.inferred_preset}' (${r.inferred_preset_conf} confidence). Click to set correct preset`;
    return `<span class="preset-badge ${cls}" data-preset-file="${r.filename}" title="${title}">${shown}</span>`;
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
    filterFn: null,
    rowHtml: (r) => `
        <tr class="run-row hover-open" data-detail="${r.detail_href || ''}" data-filename="${r.filename}" title="${r.filename}&#10;${r.deck_summary}">
            <td>${fmtDate(r.timestamp)}</td>
            <td>${r.trainee_name}</td>
            <td>${r.scenario_name}</td>
            <td>${renderPresetBadge(r)}</td>
            <td title="${r.deck_summary}">
                <span class="deck-thumbs">
                    ${(r.deck_cards||[]).map(c => renderDeckThumb(c)).join("")}
                </span>
                <button class="deck-hash-link" data-deck="${r.deck_hash}" title="Filter All Runs to this deck">${r.deck_hash}</button>
            </td>
            <td class="num" title="${r.score_range_label}">${r.score_ceiling ? fmtNum(r.score_ceiling) : "—"}</td>
            <td title="${r.rank_range_label}">${renderGradeBadges(r)}</td>
            <td class="compat-cell" title="${r.compat_tooltip}">${r.compat_missing
                ? `<span class="compat-missing">no data</span>`
                : `<span class="compat-symbol compat-${r.compat_rank}">${r.compat_symbol}</span><span class="compat-pts">${r.compat_total}</span>`}</td>
            <td class="num">${fmtNum(r.stat_sum)}</td>
            <td class="num">${fmtNum(r.speed)}</td>
            <td class="num">${fmtNum(r.stamina)}</td>
            <td class="num">${fmtNum(r.power)}</td>
            <td class="num">${fmtNum(r.guts)}</td>
            <td class="num">${fmtNum(r.wiz)}</td>
            <td class="num">${fmtNum(r.unspent_sp)}</td>
            <td class="num">${fmtNum(r.races_run)}</td>
            <td class="num">${fmtNum(r.fans)}</td>
            <td class="num">${fmtNum(r.skill_hints_available)}</td>
            <td class="open-cell">${r.detail_href ? `<span class="open-pill">Open ▸</span>` : ""}</td>
        </tr>
    `,
});
document.getElementById("filter").addEventListener("input", e => runsCtrl.setFilter(e.target.value));

// Deck drilldown — either the whole deck row OR the small hash pill
// filters the All Runs table to that deck and switches to the Runs
// section. Whole-row click is the primary affordance; the hash link
// stays for muscle-memory.
function drillIntoDeck(hash) {
    const input = document.getElementById("filter");
    input.value = hash;
    runsCtrl.setFilter(hash);
    // If we're in the SPA layout, activate the Runs panel first so the
    // filter is visible; then scroll the table into view.
    const activateFn = document.getElementById("side-nav") ? "runs" : null;
    if (activateFn) {
        // Trigger the same nav flow as clicking the sidebar's Runs link
        const runsLink = document.querySelector('#side-nav a[data-section="runs"]');
        if (runsLink) runsLink.click();
    }
    // Delay scrollIntoView so panel activation + rAF for the outer
    // window can settle first.
    requestAnimationFrame(() => {
        document.getElementById("runs").scrollIntoView({behavior: "smooth", block: "start"});
    });
}
document.addEventListener("click", (e) => {
    // Ignore clicks originating on the picker or interactive controls
    if (e.target.closest("button, a, input, .card-picker, .filter-chip")) {
        // …unless it's the deck-hash-link (a button we want to catch)
        const link = e.target.closest(".deck-hash-link");
        if (!link) return;
        drillIntoDeck(link.dataset.deck);
        return;
    }
    const row = e.target.closest("tr.deck-row[data-deck]");
    if (!row) return;
    drillIntoDeck(row.dataset.deck);
});

// Click a preset badge → cycle through Balanced → Stamina → Sprint →
// Custom → (clear override). Right-click clears immediately.
document.addEventListener("click", (e) => {
    const badge = e.target.closest(".preset-badge[data-preset-file]");
    if (!badge) return;
    const filename = badge.dataset.presetFile;
    const overrides = loadPresetOverrides();
    const current = overrides[filename];
    let next;
    if (!current) next = PRESET_CYCLE[0];
    else {
        const i = PRESET_CYCLE.indexOf(current);
        next = i === -1 || i === PRESET_CYCLE.length - 1 ? null : PRESET_CYCLE[i + 1];
    }
    savePresetOverride(filename, next);
    runsCtrl.apply();
});
document.addEventListener("contextmenu", (e) => {
    const badge = e.target.closest(".preset-badge[data-preset-file]");
    if (!badge) return;
    e.preventDefault();
    savePresetOverride(badge.dataset.presetFile, null);
    runsCtrl.apply();
});

// ── decks table ───────────────────────────────────────────────────
// Deck filters:
//   - Card picker: multi-select from a card grid; decks must contain
//     ALL selected cards (intersection).
//   - Scenario chips: multi-select; deck must include at least one
//     selected scenario. All 4 scenarios always available (chips for
//     scenarios with no runs are shown disabled).
//   - Top-N cap by default, expand toggle removes it.
const DECK_TOP_N = 10;
const ALL_SCENARIOS = ["URA Finale", "Unity Cup", "Our Grand Concert", "Trackblazer"];
const deckPickedCards = new Set();  // card_id (int)
const deckScenarioActive = new Set();
let deckExpanded = false;

function decksMatch(d) {
    if (deckScenarioActive.size > 0) {
        const dScens = new Set(d.scenarios || []);
        let hit = false;
        for (const s of deckScenarioActive) if (dScens.has(s)) { hit = true; break; }
        if (!hit) return false;
    }
    if (deckPickedCards.size > 0) {
        const deckCardIds = new Set((d.deck_cards || []).map(c => c.card_id));
        for (const cid of deckPickedCards) if (!deckCardIds.has(cid)) return false;
    }
    return true;
}

const decksCtrl = makeSortable({
    tableId: "decks",
    bodyId: "decks-body",
    colspan: 12,
    data: DECKS,
    defaultKey: "best_score",
    defaultDir: -1,
    filterFn: (d) => decksMatch(d),
    rowHtml: (d) => `
        <tr class="deck-row hover-open" data-deck="${d.deck_hash}" title="Click anywhere on the row to view all runs of this deck (${d.deck_summary})">
            <td>
                <span class="deck-thumbs">
                    ${(d.deck_cards||[]).map(c => renderDeckThumb(c)).join("")}
                </span>
                <button class="deck-hash-link" data-deck="${d.deck_hash}" title="Filter All Runs to this deck">${d.deck_hash}</button>
            </td>
            <td>${Object.entries(d.type_composition).sort((a,b)=>b[1]-a[1])
                    .map(([t,n]) => `<span class="chip type-${t}">${n}×${t}</span>`).join("")}</td>
            <td>${d.trainees_label}</td>
            <td>${d.scenarios_label || "—"}</td>
            <td class="num">${d.runs}</td>
            <td class="num">${fmtNum(d.best_score)}</td>
            <td class="num">${fmtNum(d.avg_score)}</td>
            <td>${renderDeckGradeRange(d)}</td>
            <td class="num">${fmtNum(d.best_stat_sum)}</td>
            <td class="num">${fmtNum(d.avg_unspent_sp)}</td>
            <td class="num">${fmtNum(d.best_fans)}</td>
            <td class="open-cell"><span class="open-pill">Open ▸</span></td>
        </tr>
    `,
});

// Post-process the tbody after each apply: enforce top-N cap unless
// user expanded, and populate the footer note. Runs on every apply()
// via a MutationObserver-free approach — decksCtrl.apply calls into
// a re-emit hook we override below.
const decksBody = document.getElementById("decks-body");
const decksFooter = document.getElementById("deck-footer");
const origDeckApply = decksCtrl.apply;
decksCtrl.apply = function () {
    origDeckApply();
    const rows = decksBody.querySelectorAll("tr");
    const total = rows.length;
    let visible = total;
    if (!deckExpanded && total > DECK_TOP_N) {
        rows.forEach((tr, i) => tr.style.display = i < DECK_TOP_N ? "" : "none");
        visible = DECK_TOP_N;
    } else {
        rows.forEach(tr => tr.style.display = "");
    }
    // Footer: how many decks visible / total after filter (of overall)
    const parts = [];
    parts.push(`${visible} of ${total} decks`);
    if (deckScenarioActive.size > 0 || deckPickedCards.size > 0)
        parts.push('<button class="link-btn" id="deck-clear-inline">Clear filters</button>');
    if (!deckExpanded && total > DECK_TOP_N)
        parts.push(`<button class="link-btn" id="deck-expand-inline">Show all ${total}</button>`);
    decksFooter.innerHTML = parts.join(' · ');
};

// Scenario chips — always show all four; chips for scenarios that
// don't appear in any deck are visually disabled but still labeled
// so the filter menu is self-explanatory.
const scenarioSet = document.getElementById("deck-scenario-set");
const scenariosInData = new Set(DECKS.flatMap(d => d.scenarios || []));
scenarioSet.innerHTML = ALL_SCENARIOS.map(s => {
    const disabled = scenariosInData.has(s) ? "" : " disabled";
    return `<button class="filter-chip${disabled}" data-scenario="${s}">${s}</button>`;
}).join("");

// Card picker — unique cards across all decks, sorted by frequency then name
const cardPickerBtn = document.getElementById("deck-card-add-btn");
const cardPicker = document.getElementById("deck-card-picker");
const cardGrid = document.getElementById("deck-card-grid");
const cardChipsBar = document.getElementById("deck-card-chips");
const cardSearchInput = document.getElementById("deck-card-search");

function buildCardCatalog() {
    const seen = new Map();  // card_id -> {card_id, name, image_url, count}
    for (const d of DECKS) {
        for (const c of (d.deck_cards || [])) {
            if (!c || !c.card_id) continue;
            const key = c.card_id;
            const prev = seen.get(key);
            if (prev) prev.count++;
            else seen.set(key, {
                card_id: c.card_id,
                name: c.name || `?card:${c.card_id}`,
                image_url: c.image_url,
                type_icon_url: c.type_icon_url,
                count: 1,
            });
        }
    }
    return Array.from(seen.values()).sort((a, b) =>
        b.count - a.count || a.name.localeCompare(b.name));
}
const CARD_CATALOG = buildCardCatalog();

function renderCardGrid(filter = "") {
    const q = filter.trim().toLowerCase();
    cardGrid.innerHTML = CARD_CATALOG.map(c => {
        const selected = deckPickedCards.has(c.card_id) ? " selected" : "";
        const matches = !q || c.name.toLowerCase().includes(q);
        const hidden = matches ? "" : " hidden";
        return `<div class="pick-card${selected}${hidden}" data-card-id="${c.card_id}" title="${c.name} (in ${c.count} decks)">
            ${c.image_url ? `<img class="pick-thumb" src="${c.image_url}" loading="lazy" onerror="this.style.visibility='hidden'">` : ''}
            <div class="pick-name">${c.name}</div>
        </div>`;
    }).join("");
}
renderCardGrid();

function renderCardChips() {
    if (deckPickedCards.size === 0) {
        cardChipsBar.innerHTML = '<span class="filter-hint">none — click "+" to add a card filter</span>';
        return;
    }
    const chips = [];
    for (const cid of deckPickedCards) {
        const c = CARD_CATALOG.find(x => x.card_id === cid);
        if (!c) continue;
        chips.push(`<span class="picked-card">
            ${c.image_url ? `<img src="${c.image_url}">` : ''}
            <span>${c.name}</span>
            <button class="remove" data-card-id="${cid}" title="Remove filter">×</button>
        </span>`);
    }
    cardChipsBar.innerHTML = chips.join("");
}
renderCardChips();

function openCardPicker(open) {
    cardPicker.hidden = !open;
    cardPickerBtn.setAttribute("aria-expanded", open);
    if (open) {
        cardSearchInput.value = "";
        renderCardGrid();
        cardSearchInput.focus();
    }
}
cardPickerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openCardPicker(cardPicker.hidden);
});
document.getElementById("deck-card-close").addEventListener("click", () => openCardPicker(false));
cardSearchInput.addEventListener("input", e => renderCardGrid(e.target.value));

// Dismiss picker on outside click / Escape. Clicks inside the picker
// (grid, search box) stop propagation via the container, so filter
// selection doesn't accidentally close the panel.
cardPicker.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", (e) => {
    if (cardPicker.hidden) return;
    if (e.target.closest("#deck-card-add-btn")) return;
    openCardPicker(false);
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !cardPicker.hidden) openCardPicker(false);
});

cardGrid.addEventListener("click", e => {
    const card = e.target.closest(".pick-card");
    if (!card) return;
    const cid = Number(card.dataset.cardId);
    if (deckPickedCards.has(cid)) deckPickedCards.delete(cid);
    else deckPickedCards.add(cid);
    card.classList.toggle("selected");
    renderCardChips();
    decksCtrl.apply();
});
cardChipsBar.addEventListener("click", e => {
    const rm = e.target.closest(".remove[data-card-id]");
    if (!rm) return;
    deckPickedCards.delete(Number(rm.dataset.cardId));
    renderCardChips();
    // Re-sync selected state in the (possibly still-open) grid
    cardGrid.querySelectorAll(".pick-card.selected").forEach(el => {
        if (!deckPickedCards.has(Number(el.dataset.cardId))) el.classList.remove("selected");
    });
    decksCtrl.apply();
});

document.getElementById("deck-expand").addEventListener("change", e => {
    deckExpanded = e.target.checked;
    decksCtrl.apply();
});
scenarioSet.addEventListener("click", e => {
    const chip = e.target.closest(".filter-chip:not(.disabled)");
    if (!chip) return;
    const s = chip.dataset.scenario;
    if (deckScenarioActive.has(s)) deckScenarioActive.delete(s);
    else deckScenarioActive.add(s);
    chip.classList.toggle("active");
    decksCtrl.apply();
});
function clearDeckFilters() {
    deckPickedCards.clear();
    deckScenarioActive.clear();
    scenarioSet.querySelectorAll(".filter-chip.active").forEach(c => c.classList.remove("active"));
    cardGrid.querySelectorAll(".pick-card.selected").forEach(c => c.classList.remove("selected"));
    renderCardChips();
    decksCtrl.apply();
}
document.getElementById("deck-clear").addEventListener("click", clearDeckFilters);
document.addEventListener("click", e => {
    if (e.target.matches("#deck-clear-inline")) { clearDeckFilters(); }
    if (e.target.matches("#deck-expand-inline")) {
        deckExpanded = true;
        document.getElementById("deck-expand").checked = true;
        decksCtrl.apply();
    }
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

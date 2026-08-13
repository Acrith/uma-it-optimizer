"""The E table: per (card, level, stat) specialty/initial surplus.

Completes the per-card stat answer. The base channel is solved exactly
(offset_sweep); the specialty and initial-carrying stats ride the E
channel, which is deterministic given the exact setup but varies ~+-8%
across decks (career AI facility-visit pattern; see it-formula.md).
So the honest E answer is a median with a spread, in X units on the
same scale as C and the axis:

    stat = floor(u_s * T(races) * (C_s + axis + dx_stat))
    dx_stat ~ 0 for the base trio (plus the card's measured offset);
    dx_stat = E for specialty/initial stats: quote median [p10, p90].

Uses only URA/GL/TB pal-free runs (Unity excluded end to end).

Usage:
    python e_table.py --mdb master.mdb --runs <dir> [--min-n 5]
        [--card 30010]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from it_formula import Masters, load_run
from offset_sweep import STAT_FIELDS, U, c_bounds, turns

STAT_NAMES = ("spd", "sta", "pow", "gut", "wiz")


def collect(runs_dir: Path, masters: Masters):
    """-> {(card, level, stat_idx): [dx, ...]} over deduped pal-free runs."""
    out: dict = defaultdict(list)
    seen: set = set()
    for p in sorted(runs_dir.glob("*/*.json")):
        try:
            r = load_run(p, masters)
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not r or r["scenario"] not in U or r.get("has_pal"):
            continue
        if not r["races"] or turns(r["races"]) is None:
            continue
        key = (r["scenario"], r["races"],
               tuple(sorted((x.card_id, x.level) for x in r["rows"])))
        if key in seen:
            continue
        seen.add(key)
        ut = U[r["scenario"]] * turns(r["races"])
        clo, chi = c_bounds(r["scenario"], r["races"])
        cm = (clo + chi) / 2
        lv = {x.card_id: (x.level, x.axis) for x in r["rows"]}
        for e in raw.get("SupportCardGainInfo") or []:
            cid = e["<SupportCardId>k__BackingField"]
            if cid not in lv or cid == 30078:
                continue
            g = e["<GainInfo>k__BackingField"]
            for i, f in enumerate(STAT_FIELDS):
                dx = (g[f] + 0.5) / ut - cm - lv[cid][1]
                out[(cid, lv[cid][0], i)].append(dx)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--card", type=int)
    args = ap.parse_args()

    masters = Masters(args.mdb)
    cells = collect(args.runs, masters)
    by_card: dict = defaultdict(dict)
    for (cid, lvl, i), v in cells.items():
        by_card[(cid, lvl)][i] = v

    print(f"{'card':>7} {'lv':>3} {'n':>4}  per-stat dx: median [p10..p90], "
          f"E-stats marked *")
    for (cid, lvl), stats in sorted(by_card.items()):
        n = len(stats.get(0, []))
        if n < args.min_n or (args.card and cid != args.card):
            continue
        _, _, _, initial, _ = masters.bonuses(cid, lvl)
        meds = {i: median(v) for i, v in stats.items()}
        base_med = median(sorted(meds.values())[:3])
        parts = []
        for i in range(5):
            v = sorted(stats.get(i, []))
            if not v:
                continue
            m = median(v)
            p10, p90 = v[int(len(v) * .1)], v[min(len(v) - 1, int(len(v) * .9))]
            # An E-stat sits far above the card's base trio.
            is_e = m - base_med > 300 or initial[i] > 0
            parts.append(f"{STAT_NAMES[i]}{'*' if is_e else ''}:"
                         f"{m:+6.0f}[{p10:+.0f}..{p90:+.0f}]")
        print(f"{cid:>7} {lvl:>3} {n:>4}  " + "  ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

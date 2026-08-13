"""Per-(card, level) offset intervals against the known scenario constants.

The primary instrument since 2026-08-11 (see uma-it-web docs/it-formula.md,
"interval sweep"). For every pal-free run in a deterministic scenario:

    obs = floor(u_s * T(races) * (C_s + axis + dx))

admits dx in [obs/(uT) - C_hi - axis, (obs+1)/(uT) - C_lo - axis).
Intersecting per (card, level) across runs boxes each card's drift; an
EMPTY intersection means no constant offset fits (run-dependent).

Scope rules learned the hard way:
- Unity (scenario 2) is excluded: non-deterministic from 22 races on,
  and C_Unity is only wedged, not pinned.
- Filter pal runs via load_run's has_pal — pal ROWS are already stripped
  from rows, so "no pal id among rows" filters nothing.
- Dedupe twins by (scenario, races, deck-with-levels): twins are
  byte-identical here and add no information.
- C_URA is an interval; both ends are folded in conservatively.
- --stat sweeps one stat index (0=spd..4=wiz) instead of the base (min);
  specialty/initial stats have NO constant dx (they ride the E channel).

Usage:
    python offset_sweep.py --mdb master.mdb --runs <dir> [--min-n 3]
        [--stat N] [--card 20016]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from it_formula import Masters, load_run

U = {1: 0.000132839, 3: 0.000149987, 4: 0.000124227}
# URA's constant is RACE-DEPENDENT (recalibrated 2026-08-13): the fixed
# [2798, 2854) interval was the shadow of a race tilt. C_eff(races) =
# 2738 + 1.30 * races (+-25), which lands on the community's old 2750
# at 9 races - that number was right for short careers all along.
URA_C_BASE, URA_C_SLOPE, URA_C_HALFWIDTH = 2738.4, 1.30, 25.0


def c_bounds(scenario: int, races: int) -> tuple[float, float]:
    if scenario == 1:
        mid = URA_C_BASE + URA_C_SLOPE * races
        return mid - URA_C_HALFWIDTH, mid + URA_C_HALFWIDTH
    c = {3: 1825.0, 4: 3400.0}[scenario]
    return c, c
# Measured turn curve. 13/14/15 added 2026-08-13; T(14) is the softest
# point (+-0.3) — offset precision chains to T precision at the run's
# race counts.
T_POINTS = {4: 75.60, 5: 74.99, 6: 73.46, 7: 72.73, 8: 71.15, 9: 70.44,
            10: 69.31, 11: 68.17, 12: 66.98, 13: 65.96, 14: 65.50,
            15: 63.94, 16: 63.07, 20: 58.51, 24: 54.30, 25: 53.36,
            26: 51.90, 27: 51.18, 28: 50.74, 29: 49.00, 30: 48.67,
            31: 46.82, 32: 46.60, 33: 44.82, 34: 44.53, 35: 42.55,
            36: 42.46, 37: 40.55, 38: 40.29, 39: 38.32, 40: 38.11}
STAT_FIELDS = ("<Speed>k__BackingField", "<Stamina>k__BackingField",
               "<Power>k__BackingField", "<Guts>k__BackingField",
               "<Wiz>k__BackingField")


def turns(races: int) -> float | None:
    ks = sorted(T_POINTS)
    for a, b in zip(ks, ks[1:], strict=False):
        if a <= races <= b:
            return T_POINTS[a] + (T_POINTS[b] - T_POINTS[a]) * (races - a) / (b - a)
    return None


def sweep(runs_dir: Path, masters: Masters, stat: int | None = None):
    """-> {(card, level): [lo, hi]}, {(card, level): n}"""
    iv: dict = defaultdict(lambda: [-1e9, 1e9])
    nn: dict = defaultdict(int)
    seen: set = set()
    for p in sorted(runs_dir.glob("*/*.json")):
        try:
            r = load_run(p, masters)
        except Exception:
            continue
        if not r or r["scenario"] not in U or r.get("has_pal"):
            continue
        if not r["races"] or not (4 <= r["races"] <= 40):
            continue
        key = (r["scenario"], r["races"],
               tuple(sorted((x.card_id, x.level) for x in r["rows"])))
        if key in seen:
            continue
        seen.add(key)
        t = turns(r["races"])
        ut = U[r["scenario"]] * t
        clo, chi = c_bounds(r["scenario"], r["races"])
        if stat is None:
            cells = [(row.card_id, row.level, row.base, row.axis)
                     for row in r["rows"] if row.card_id != 30078]
        else:
            raw = json.loads(p.read_text(encoding="utf-8"))
            lv = {x.card_id: (x.level, x.axis) for x in r["rows"]}
            cells = []
            for e in raw.get("SupportCardGainInfo") or []:
                cid = e["<SupportCardId>k__BackingField"]
                if cid not in lv or cid == 30078:
                    continue
                v = e["<GainInfo>k__BackingField"][STAT_FIELDS[stat]]
                cells.append((cid, lv[cid][0], v, lv[cid][1]))
        for cid, level, obs, axis in cells:
            k = (cid, level)
            iv[k][0] = max(iv[k][0], obs / ut - chi - axis)
            iv[k][1] = min(iv[k][1], (obs + 1) / ut - clo - axis)
            nn[k] += 1
    return iv, nn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True,
                    help="directory containing per-user run dirs")
    ap.add_argument("--min-n", type=int, default=3)
    ap.add_argument("--stat", type=int, choices=range(5),
                    help="sweep one stat index instead of the base (min)")
    ap.add_argument("--card", type=int, help="only this card id")
    args = ap.parse_args()

    masters = Masters(args.mdb)
    iv, nn = sweep(args.runs, masters, args.stat)
    print(f"{'card':>7} {'lv':>3} {'n':>4}  offset X            name")
    for k in sorted(iv, key=lambda k: iv[k][0] + iv[k][1]):
        cid, level = k
        if nn[k] < args.min_n or (args.card and cid != args.card):
            continue
        lo, hi = iv[k]
        s = "EMPTY/varies" if lo > hi else f"[{lo:+6.0f},{hi:+6.0f})"
        print(f"{cid:>7} {level:>3} {nn[k]:>4}  {s:<19} "
              f"{masters.card_name.get(cid, '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

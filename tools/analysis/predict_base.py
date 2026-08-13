"""Predict a support card's base stat contribution for one IT run.

`base` is what a card adds to the stats it does NOT specialise in — the flat
channel every card contributes to every stat. It is the quantity the formula
research in ../uma-it-web/docs/it-formula.md models:

    base = floor(g * (C_scenario + 5*Mood + 21*TrainingEffect))
    g    = u * T(races)     — T is the MEASURED turn curve, not 78 - races

Accuracy, held-out half of the pal-free corpus (2026-08-10, T-curve model):

    within +-1   96.6%
    exact        82.0%       cold  (was 78.8% under u * (78 - races))
    exact        90.7%       cold at 20 races or fewer  (was 76.7%)

The gain is the measured turn curve T(races) replacing 78 - races — the
old form ran ~1.5 turns low on short careers. Stats are deterministic
(twin runs are byte-identical at <=40 races), so the remaining misses are
X-table granularity, not randomness. Our Grand Concert's constant is the
least trustworthy of the four.

Usage:
    python predict_base.py --card 30010 --level 50 --scenario 4 --races 9
    python predict_base.py --deck 30010:50,30074:50 --scenario 4 --races 9
"""
from __future__ import annotations

import argparse
from pathlib import Path

from it_formula import (
    SCENARIO_CONST,
    Masters,
    axis_of,
    const_for,
)

# u = g / T, fitted per scenario over the pal-free corpus with no per-run
# freedom, against the MEASURED turn curve T(races) below rather than 78-r.
U_BY_SCENARIO = {1: 0.000132839, 2: 0.000125950, 3: 0.000149987,
                 4: 0.000124227}
SCEN_NAME = {1: "URA", 2: "Unity Cup", 3: "Our Grand Concert",
             4: "Trackblazer"}

# T(races): the effective training-turn count, measured from deck 3fbf95's
# 19-consecutive-race-count sweep (specialty stats pin the run scalar to
# ~1%, exposing what 78 - races only approximates). Deck-independent to
# <=0.5% and shared across scenarios at 9-35 races (36ee8e dual rows, and
# a URA six-count deck). 78 - r runs ~1.5 turns LOW below ~28 races and
# high above ~35, which is why the old form missed short careers.
# Linear interpolation between measured points; outside 4-40 races the
# curve is unmeasured (41+ is also schedule-dependent — twin runs differ).
_T_POINTS = [(4, 75.60), (5, 74.99), (6, 73.46), (7, 72.73), (8, 71.15),
             (9, 70.44), (10, 69.31), (11, 68.17), (12, 66.98), (13, 65.96),
             (14, 65.50), (15, 63.94), (16, 63.07),
             # 17-19 and 21-23 are PATTERN-FILLED, not measured (+-0.3):
             # the staircase is race-count parity accounting (odd
             # transitions ~-1.9 turns, even ~-0.25, placement-independent
             # per RaceHistory), and continuing it from 16 hits measured
             # T(20) within 0.24 and from 20 hits T(24) within 0.1.
             (17, 61.17), (18, 60.92), (19, 59.02), (20, 58.51),
             (21, 56.61), (22, 56.36), (23, 54.46), (24, 54.30),
             (25, 53.36), (26, 51.90), (27, 51.18), (28, 50.74), (29, 49.00),
             (30, 48.67), (31, 46.82), (32, 46.60), (33, 44.82), (34, 44.53),
             (35, 42.55), (36, 42.46), (37, 40.55), (38, 40.29), (39, 38.32),
             (40, 38.11)]


def turns_for(races: int) -> float | None:
    """Measured T(races), or None outside the calibrated 4-40 range."""
    for (a, ta), (b, tb) in zip(_T_POINTS, _T_POINTS[1:], strict=False):
        if a <= races <= b:
            return ta + (tb - ta) * (races - a) / (b - a)
    return None
# Initial bonus on all five stats, so no adder-free stat exists to read a
# base off. Excluded from every fit; refuse to predict it rather than lie.
UNREADABLE = {30078}


def predict(masters: Masters, card_id: int, level: int, scenario: int,
            races: int) -> dict:
    fb, mood, te, initial, conditional = masters.bonuses(card_id, level)
    axis = axis_of(fb, mood, te)
    const = const_for(scenario)
    if scenario == 1:
        # URA's constant is race-dependent (recalibrated 2026-08-13):
        # C_eff = 2738 + 1.30 * races. The static 2750 it replaces was
        # exactly right at 9 races; the correction lifts URA from 77.4%
        # to 82.3% exact over the corpus, level with GL/TB at 83.6%.
        const = 2738.4 + 1.30 * races
    n = turns_for(races)
    if n is None:
        # Fall back to the linear approximation outside the measured range,
        # and say so — 41+ races is also schedule-dependent.
        n = 78 - races
    u = U_BY_SCENARIO[scenario]
    point = int(u * n * (const + axis))
    return {
        "card_id": card_id, "level": level, "mood": mood, "training": te,
        "friendship": fb, "axis": axis, "const": const, "turns": n,
        "base": point, "low": max(point - 1, 0), "high": point + 1,
        "conditional": conditional, "initial": initial,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True, help="master.mdb")
    ap.add_argument("--card", type=int, help="support card id")
    ap.add_argument("--level", type=int, help="card level")
    ap.add_argument("--deck", help="comma list of id:level")
    ap.add_argument("--scenario", type=int, required=True,
                    choices=sorted(SCENARIO_CONST))
    ap.add_argument("--races", type=int, required=True)
    args = ap.parse_args()

    if not args.deck and not (args.card and args.level):
        ap.error("give either --card with --level, or --deck")

    entries = []
    if args.deck:
        for chunk in args.deck.split(","):
            cid, _, lv = chunk.partition(":")
            entries.append((int(cid), int(lv)))
    else:
        entries.append((args.card, args.level))

    masters = Masters(args.mdb)
    t = turns_for(args.races)
    print(f"scenario {args.scenario} ({SCEN_NAME[args.scenario]})  "
          f"races {args.races}  training turns "
          f"{f'{t:.1f}' if t is not None else f'~{78 - args.races} (unmeasured range)'}  "
          f"C {const_for(args.scenario)}")
    if args.races > 40:
        print("  ! 41+ races: turn economy is race-schedule dependent — "
              "twin runs differ even in stats")
    if args.scenario == 3:
        print("  ! Our Grand Concert: constant unresolved, errors reach +2")
    print()
    print(f"{'card':>7} {'lv':>3} {'mood':>5} {'TE':>4} {'axis':>6} "
          f"{'base':>6} {'range':>9}  name")

    total = 0
    for cid, lv in entries:
        if cid in UNREADABLE:
            print(f"{cid:>7} {lv:>3}  -- base is unreadable for this card "
                  f"(initial bonus on all five stats)")
            continue
        if cid not in masters.trainer_cards:
            print(f"{cid:>7} {lv:>3}  -- not a trainer card in this master.mdb")
            continue
        r = predict(masters, cid, lv, args.scenario, args.races)
        total += r["base"]
        flag = " [conditional unique]" if r["conditional"] else ""
        print(f"{cid:>7} {lv:>3} {r['mood']:>5} {r['training']:>4} "
              f"{r['axis']:>6} {r['base']:>6} {r['low']:>4}-{r['high']:<4} "
              f" {masters.card_name.get(cid, '?')}{flag}")
    if len(entries) > 1:
        print(f"{'':>7} {'':>3} {'':>5} {'':>4} {'total':>6} {total:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

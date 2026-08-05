"""Experiment design: which lab deck actually pins the formula constant C?

`base = floor(g_run * (C + axis))` is linear in axis, so C is the
INTERCEPT — recoverable only from the slope, i.e. from how much `base`
moves per unit of axis. At 4 races g ~= 0.021, so 100 axis points move
the base by only ~2.1 stat, and each observation carries +-1 of floor
noise. That makes deck choice and race coverage the whole ballgame.

Method: assume a truth (C, a), generate the integer bases a deck would
produce, then ask which C values still admit SOME g reproducing every
integer. The width of that feasible set is the design's power (smaller
is better). Worst-cased over several assumed truths so the answer does
not depend on guessing C right.

Usage:
    python deck_design.py --mdb master.mdb            # evaluate presets
    python deck_design.py --mdb master.mdb --search   # search card pool
"""
from __future__ import annotations

import argparse
import sqlite3
from itertools import product
from pathlib import Path

from it_formula import Masters, axis_of

LEVEL_CAP = {1: 40, 2: 45, 3: 50}
FACILITY = {101: "Speed", 102: "Power", 103: "Guts", 105: "Stamina", 106: "Wit"}
RARITY_LABEL = {1: "R", 2: "SR", 3: "SSR"}

# Cards whose prod rows the formula does not yet reproduce — keep them
# OUT of a deck meant to measure C (they would bias it). See the
# research log's debugging queue.
KNOWN_MISFITS = {30078, 30074, 30101, 30008, 30028, 30084}

# (C, a) pairs to worst-case over, spanning the current uncertainty.
TRUTHS = ((1400, 0.4232), (1450, 0.4232), (1500, 0.4232), (1450, 0.4260))
C_GRID = range(1000, 2401, 5)


def feasible_width(axes: list[int], race_counts: tuple[int, ...]) -> int:
    """Worst-case width of the feasible-C set across TRUTHS."""
    worst = 0
    for c_true, a_true in TRUTHS:
        observed = {
            races: [int((a_true * (76 - races) / c_true) * (c_true + a)) for a in axes]
            for races in race_counts
        }
        feasible = []
        for const in C_GRID:
            ok = True
            for races in race_counts:
                lo, hi = 0.0, float("inf")
                for axis, base in zip(axes, observed[races]):
                    weight = const + axis
                    lo = max(lo, base / weight)
                    hi = min(hi, (base + 1) / weight)
                if lo >= hi:
                    ok = False
                    break
            if ok:
                feasible.append(const)
        worst = max(worst, (max(feasible) - min(feasible)) if feasible else 9999)
    return worst


def load_pool(mdb: Path, *, drop_misfits: bool = True,
              drop_conditional: bool = True) -> dict[int, dict]:
    masters = Masters(mdb)
    db = sqlite3.connect(f"file:{mdb}?mode=ro", uri=True)
    pool: dict[int, dict] = {}
    for card_id, command in db.execute(
        "SELECT id, command_id FROM support_card_data WHERE support_card_type = 1"
    ):
        if command not in FACILITY or card_id not in masters.rarity:
            continue
        if drop_misfits and card_id in KNOWN_MISFITS:
            continue
        level = LEVEL_CAP[masters.rarity[card_id]]
        fb, mood, te, _initial, conditional = masters.bonuses(card_id, level)
        if drop_conditional and conditional:
            continue
        pool[card_id] = {
            "axis": axis_of(fb, mood, te),
            "facility": FACILITY[command],
            "rarity": masters.rarity[card_id],
            "name": masters.card_name.get(card_id, "?"),
            "fb": fb, "mood": mood, "te": te,
        }
    db.close()
    return pool


PRESETS: dict[str, list[int]] = {
    "lab ladder (what was already run)": [205, 205, 205, 270, 285, 295],
    "evenly spread across the range": [40, 105, 170, 235, 290, 355],
    "hand-picked stress deck": [40, 205, 270, 285, 295, 355],
    "3x Tracen R + 2 high (all 5 facilities)": [30, 40, 40, 270, 280, 310],
    "3x Tracen R + low SSR + 2 high": [30, 40, 40, 70, 270, 310],
}


def cmd_presets() -> None:
    print("worst-case feasible-C width (smaller = better), by race coverage:\n")
    print(f"  {'deck':<42} {'1 run':>7} {'@4,5':>7} {'@4-8':>7}")
    for name, axes in PRESETS.items():
        w1 = feasible_width(axes, (4,))
        w2 = feasible_width(axes, (4, 5))
        w5 = feasible_width(axes, (4, 5, 6, 7, 8))
        print(f"  {name:<42} {w1:>7} {w2:>7} {w5:>7}")
    print("\n  Reading: the lab deck cannot pin C at any race coverage — it has")
    print("  no low-axis card, so every row sits on one short stretch of the")
    print("  line. A near-zero-axis anchor (Tracen Academy R) is what matters;")
    print("  extra race counts then dither the floor and tighten the rest.")


def cmd_search(pool: dict[int, dict]) -> None:
    by_facility: dict[str, list[int]] = {}
    for facility in FACILITY.values():
        axes = sorted({c["axis"] for c in pool.values() if c["facility"] == facility})
        by_facility[facility] = axes[:3] + axes[-3:]      # informative extremes

    scored: dict[tuple[int, ...], int] = {}
    for combo in product(*by_facility.values()):
        for sixth in sorted({a for axes in by_facility.values() for a in axes}):
            key = tuple(sorted(combo + (sixth,)))
            if key not in scored:
                scored[key] = feasible_width(list(key), (4, 5))
    ranked = sorted(scored.items(), key=lambda kv: kv[1])

    print("best axis sets (one card per facility + a free sixth), runs @4 and @5:\n")
    for axes, width in ranked[:3]:
        print(f"  width {width}   axes {list(axes)}")
    print("\ncards realising the best set:")
    for axis in sorted(set(ranked[0][0])):
        options = sorted(
            (cid for cid, c in pool.items() if c["axis"] == axis),
            key=lambda cid: -pool[cid]["rarity"],
        )
        for cid in options[:2]:
            c = pool[cid]
            print(f"  axis {axis:>3}: {cid} {RARITY_LABEL[c['rarity']]:>3} "
                  f"{c['facility']:<8} (FB{c['fb']} M{c['mood']} TE{c['te']}) {c['name']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mdb", type=Path, default=Path("master.mdb"))
    parser.add_argument("--search", action="store_true",
                        help="search the card pool instead of scoring presets")
    args = parser.parse_args()

    if args.search:
        if not args.mdb.is_file():
            print(f"master.mdb not found at {args.mdb}")
            return 1
        cmd_search(load_pool(args.mdb))
    else:
        cmd_presets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

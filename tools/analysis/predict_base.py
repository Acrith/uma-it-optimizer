"""Predict a support card's base stat contribution for one IT run.

`base` is what a card adds to the stats it does NOT specialise in — the flat
channel every card contributes to every stat. It is the quantity the formula
research in ../uma-it-web/docs/it-formula.md models:

    base = floor(g * (C_scenario + 5*Mood + 21*TrainingEffect))
    g    = u * N,   N = 78 - races

Accuracy, measured leave-one-card-out over 127 independent deck x race cells
(660 card-rows, pal-free):

    within +-1   100.0%      <- has never been exceeded
    exact         88.2%      when g is fitted from the rest of the deck
    exact        ~78%        cold, using u * N with no deck context

Cold accuracy is the honest number when you name a single card, so this tool
reports the interval and not just a point. Our Grand Concert is the weak
scenario: its constant is unresolved and errors there reach +2.

Usage:
    python predict_base.py --card 30010 --level 50 --scenario 4 --races 9
    python predict_base.py --deck 30010:50,30074:50 --scenario 4 --races 9
"""
from __future__ import annotations

import argparse
from pathlib import Path

from it_formula import (
    Masters,
    SCENARIO_CONST,
    axis_of,
    const_for,
)

# u = g / N, fitted per scenario over the pal-free corpus with no per-run
# freedom. Our Grand Concert's is least trustworthy — see the doc.
U_BY_SCENARIO = {1: 0.000134560, 2: 0.000127300, 3: 0.000150000,
                 4: 0.000125955}
SCEN_NAME = {1: "URA", 2: "Unity Cup", 3: "Our Grand Concert",
             4: "Trackblazer"}
# Initial bonus on all five stats, so no adder-free stat exists to read a
# base off. Excluded from every fit; refuse to predict it rather than lie.
UNREADABLE = {30078}


def predict(masters: Masters, card_id: int, level: int, scenario: int,
            races: int) -> dict:
    fb, mood, te, initial, conditional = masters.bonuses(card_id, level)
    axis = axis_of(fb, mood, te)
    const = const_for(scenario)
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
    print(f"scenario {args.scenario} ({SCEN_NAME[args.scenario]})  "
          f"races {args.races}  training turns {78 - args.races}  "
          f"C {const_for(args.scenario)}")
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

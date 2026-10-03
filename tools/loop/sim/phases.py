"""Two phases: the URA event (cheap runs, URA hints Racing Spirits), then
another scenario. The box carries over; the scenario switch resets the
caches. Usage:
    python phases.py --master ... --account ... --rental ... \
        "<s1>:<days1>:<strategy1>|<s2>:<days2>:<strategy2>" runs/day borrows reps
"""
from __future__ import annotations

import argparse
import random
import statistics

import cli
import sim
import strategies as S
from world import load_box, load_rental


def run_phases(phases, runs_per_day, borrows, seed, base):
    rng = random.Random(seed)
    vets, trainees, rental = base
    st = S.State(vets, trainees, rental)
    out = []
    n = 0
    for sc, days, strategy in phases:
        sim.set_scenario(sc)
        st._proxy.clear()
        made4 = made5 = sparks = 0
        for _ in range(days):
            plan = S.plan_day(strategy, runs_per_day, n)
            use = S.borrow_plan(strategy, plan, borrows)
            for card, b in zip(plan, use):
                e, p1, p2, dk, per = st.best_setup(card, b)
                child = sim.run(rng, card, trainees[card], p1, p2, dk)
                st.kids.append(child)
                k = S.targets_of(child)
                made4 += k >= 4; made5 += k >= 5; sparks += k
                n += 1
        end = st.best_setup(S.FIERY, True)
        out.append({"made4": made4, "made5": made5, "sparks": sparks, "p4": sim.best_of_two_4plus(end[4]), "e": end[0]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    cli.inputs(ap)
    ap.add_argument("phases", help='"<scenario>:<days>:<strategy>|..." (strategies.py\'s strategies)')
    ap.add_argument("runs_per_day", type=int)
    ap.add_argument("borrows", type=int)
    ap.add_argument("reps", type=int)
    ap.add_argument("--fiery-potential", type=int, default=5)
    args = ap.parse_args()
    cli.init(args)
    phases = [(int(a), int(b), c) for a, b, c in (p.split(":", 2) for p in args.phases.split("|"))]
    runs_per_day, borrows, reps = args.runs_per_day, args.borrows, args.reps
    vets, trainees = load_box()
    trainees[S.FIERY] = args.fiery_potential
    rental = load_rental()
    sim.RENTAL = rental
    res = []
    for r in range(reps):
        res.append(run_phases(phases, runs_per_day, borrows, 7000 + r, (vets, trainees, rental)))
        S.clear_kid_cache()
    parts = []
    for i, (sc, days, strategy) in enumerate(phases):
        f = lambda k: statistics.mean(x[i][k] for x in res)
        any5 = sum(1 for x in res if x[i]["made5"] > 0) / reps
        parts.append(f"[{ {1: 'URA', 2: 'UC', 3: 'GC'}[sc]} {days}d {strategy}] 4+ {f('made4'):.1f}, 5/5 {f('made5'):.2f} (any {any5:.0%}), end Fiery {f('e'):.2f}/roll 4+ {f('p4'):.1%}")
    tot5 = statistics.mean(sum(p["made5"] for p in x) for x in res)
    tot4 = statistics.mean(sum(p["made4"] for p in x) for x in res)
    print(" → ".join(parts) + f"  | total 4+ {tot4:.1f}, 5/5 {tot5:.2f}", flush=True)


if __name__ == "__main__":
    main()

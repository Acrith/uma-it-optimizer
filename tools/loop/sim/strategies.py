"""Strategies over days of runs, from a player's real box: which trainee
each run, which parents (own pair or the day's borrows) and deck, the better
of two rolls kept, the new veteran back in the box.

    python strategies.py --master ... --account ... --rental ... \
        fiery,rot12-bx 28 10 5 200      # strategies, days, runs/day, borrows/day, replications
"""
from __future__ import annotations

import argparse
import random
import statistics
from dataclasses import dataclass, field

import cli
import sim
from world import TARGETS, load_box, load_rental

FIERY, NICE, MAYANO = 100802, 106002, 102401
K = 8  # candidate parents per trainee (by their value beside the rental)


@dataclass
class State:
    vets: list
    trainees: dict
    rental: object
    kids: list = field(default_factory=list)
    _proxy: dict = field(default_factory=dict)

    def proxy(self, card, v):
        """A parent's worth for this trainee: the run's expected sparks with
        the rental as the other parent (best deck)."""
        key = (card, v.id)
        if key not in self._proxy:
            best = 0.0
            for dk in sim.DECKS:
                r = sim.expected(card, self.trainees[card], v, self.rental, dk)
                if r:
                    best = max(best, r[0])
            self._proxy[key] = best
        return self._proxy[key]

    def best_setup(self, card, borrow: bool):
        """The (expected, p1, p2, deck) with the most expected sparks."""
        pool = [v for v in self.vets + self.kids if v.chara != card // 100]
        # The best few, at most two of one character (two parents can't share one).
        top, per = [], {}
        for v in sorted(pool, key=lambda v: self.proxy(card, v), reverse=True):
            if per.get(v.chara, 0) < 2:
                top.append(v); per[v.chara] = per.get(v.chara, 0) + 1
            if len(top) == K:
                break
        best = None
        pairs = [(a, b) for i, a in enumerate(top) for b in top[i + 1:]]
        if borrow:
            pairs += [(a, self.rental) for a in top]
        for a, b in pairs:
            for dk in sim.DECKS:
                r = sim.expected(card, self.trainees[card], a, b, dk)
                if r and (best is None or r[0] > best[0]):
                    best = (r[0], a, b, dk, r[1])
        return best


def plan_day(strategy: str, day_runs: int, run_index: int) -> list[int]:
    """The day's trainees in order. Also "solo:<card>" and
    "rot:<main>:<x>:<x every n runs>[-bx|-bf]"."""
    out = []
    for i in range(day_runs):
        n = run_index + i
        if strategy.startswith("solo:"):
            out.append(int(strategy.split(":")[1].split("-")[0]))
            continue
        if strategy.startswith("rot:"):
            _, main_, x, every = strategy.split("-")[0].split(":")
            out.append(int(x) if n % int(every) == 0 else int(main_))
            continue
        if strategy == "fiery":
            out.append(FIERY)
        elif strategy.startswith("rot11"):
            out.append(NICE if n % 2 == 0 else FIERY)
        elif strategy.startswith("rot12"):
            out.append(NICE if n % 3 == 0 else FIERY)
        elif strategy.startswith("rot21"):
            out.append(FIERY if n % 3 == 2 else NICE)
        else:
            raise ValueError(strategy)
    return out


def borrow_plan(strategy: str, day: list[int], borrows: int) -> list[bool]:
    """Which runs get the day's borrows: X runs first ("-bx"), the Fiery runs
    first ("-bf"), else the first runs of the day."""
    use = [False] * len(day)
    main_ = int(strategy.split(":")[1]) if strategy.startswith("rot:") else FIERY
    if strategy.endswith("-bx"):
        order = [i for i, c in enumerate(day) if c != main_] + [i for i, c in enumerate(day) if c == main_]
    elif strategy.endswith("-bf"):
        order = [i for i, c in enumerate(day) if c == main_] + [i for i, c in enumerate(day) if c != main_]
    else:
        order = list(range(len(day)))
    for i in order[:borrows]:
        use[i] = True
    return use


def targets_of(v) -> int:
    return sum(1 for t in TARGETS if t in v.sparks)


def simulate(strategy: str, days: int, runs_per_day: int, borrows: int, seed: int, base):
    rng = random.Random(seed)
    vets, trainees, rental = base
    st = State(vets, trainees, rental)
    log = []
    n = 0
    for day in range(days):
        plan = plan_day(strategy, runs_per_day, n)
        use = borrow_plan(strategy, plan, borrows)
        for card, b in zip(plan, use):
            e, p1, p2, dk, per = st.best_setup(card, b)
            child = sim.run(rng, card, trainees[card], p1, p2, dk)
            st.kids.append(child)
            log.append((day, card, b, e, targets_of(child)))
            n += 1
    # The end state: what a Fiery run can expect now, with and without a borrow.
    main_ = int(strategy.split(":")[1].split("-")[0]) if strategy.startswith(("rot:", "solo:")) else FIERY
    end_b = st.best_setup(main_, True)
    end_o = st.best_setup(main_, False)
    kids = st.kids
    return {
        "prod_borrow": end_b[0], "prod_own": end_o[0],
        "p4_borrow": sim.best_of_two_4plus(end_b[4]), "p4_own": sim.best_of_two_4plus(end_o[4]),
        "made_4": sum(1 for k in kids if targets_of(k) >= 4),
        "made_5": sum(1 for k in kids if targets_of(k) >= 5),
        "sparks": sum(targets_of(k) for k in kids),
        "best_value": max(sim.value(v) for v in vets + kids),
        "log": log,
    }


def clear_kid_cache():
    for key in [k for k in sim._SETUP if k[2] >= 10_000 or k[3] >= 10_000]:
        del sim._SETUP[key]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cli.inputs(ap)
    ap.add_argument("strategies", help='comma-separated: fiery, rot11-bx, rot12-bx, rot12-bf, rot21, "solo:<card>", "rot:<main>:<x>:<every n>[-bx|-bf]"')
    ap.add_argument("days", type=int)
    ap.add_argument("runs_per_day", type=int)
    ap.add_argument("borrows", type=int, help="borrows a day (the game allows 5)")
    ap.add_argument("reps", type=int, help="replications (200 for the numbers in the README)")
    ap.add_argument("--fiery-potential", type=int, default=5, help="Vodka [Fiery Aqua Vitae]'s potential level")
    ap.add_argument("--decoys", type=int, help="a fixed number of decoy Racing Spirits bought every run (0-4)")
    args = ap.parse_args()
    cli.init(args)
    sim.set_scenario(args.scenario)
    sim.DECOYS_FIXED = args.decoys
    strategies = args.strategies.split(",")
    days, runs_per_day, borrows, reps = args.days, args.runs_per_day, args.borrows, args.reps
    vets, trainees = load_box()
    trainees[FIERY] = args.fiery_potential
    rental = load_rental()
    sim.RENTAL = rental
    base = (vets, trainees, rental)
    for s in strategies:
        res = []
        for r in range(reps):
            res.append(simulate(s, days, runs_per_day, borrows, 1000 + r, base))
            clear_kid_cache()
        f = lambda k: statistics.mean(x[k] for x in res)
        p5 = sum(1 for x in res if x["made_5"] > 0) / reps
        print(f"{s:14} end: Fiery+borrow {f('prod_borrow'):.2f}/roll (4+ {f('p4_borrow'):5.1%}) · own pair {f('prod_own'):.2f} (4+ {f('p4_own'):5.1%})"
              f" · made: 4+ {f('made_4'):.1f}, 5/5 {f('made_5'):.2f} (P(any 5/5) {p5:.0%}) · target sparks kept {f('sparks'):.0f} · best rating {f('best_value'):.2f}",
              flush=True)


if __name__ == "__main__":
    main()

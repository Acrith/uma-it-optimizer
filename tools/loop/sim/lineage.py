"""Lineage progression over months: the community's looping process played
out from a real box (the looping guide: "the parent from (1) + Rental until
you hit again"; uma.guide: replace the own side each time a skill is added,
never accept a parent that loses one; GameTora's legacy loop: the trainee
rotates through the characters).

- The own parent is the best veteran by lineage value (sim.value: the
  target sparks a child gets from it and the rental, through carriers and
  inspiration). The newest child takes over once it beats the old line; a
  child that loses a target never does (the ratchet).
- The trainee is any owned character fit for the run (turf and medium B
  after pinks) other than the parents': a child can't parent its own
  character, so the trainee rotates as the line moves ("rotate"). "fiery"
  is the earlier plan for comparison: Vodka [Fiery Aqua Vitae] every run,
  so no Vodka can be a parent.
- Borrow runs pair the line with the rental; the other runs with the best
  own line of another character, so both sides of the lineage grow.
- Every candidate target's sparks are tracked from the start (every hinted
  one bought: SP is not limited). The active list starts with the needed
  ones and grows by one when a veteran carries all of it; the next is the
  candidate a run sparks most often at that point ("cheap") or the sheet's
  order ("tier").

Reports, per list size n: the day a veteran first carried all n (median
over replications, and the share that got there within the horizon), the
trainees used, and the chance a run makes an n/n child at the end.

    python lineage.py --master ... --account ... --rental ... --scenario 2 \\
        --deck 30052,10060,30012,30021,30085,30080 [--policy rotate,fiery] \\
        [--days 90] [--runs 10] [--borrows 5] [--reps 20] [--order cheap]
"""
from __future__ import annotations

import argparse
import collections
import random
import statistics

import cli
import sim
import world
from world import TARGETS, load_box, load_rental

# The loop sheet's Late list (released skills), tier order; Ramp Up is the
# sheet's T2 but Unity Cup gives its gold every run.
LATE = [
    "Racing Spirit: Stamina", "Racing Spirit: Power", "Uma Stan", "Nimble Navigator",
    "Pedal to the Metal",
    "Tail Held High", "Risky Business", "Full Throttle",
    "Slipstream", "Playtime's Over!", "Slick Surge", "Late Surger Corners ○",
    "Late Surger Straightaways ○", "1,500,000 CC",
    "Ramp Up",
]
NEEDED = 5
FIERY = 100802


def set_active(active: list[str]) -> None:
    sim.WEIGHTS.clear()
    sim.WEIGHTS.update({t: 1.0 if t in active else 0.0 for t in TARGETS})
    sim._VALUE_EPOCH[0] += 1


def all_of(v, active) -> bool:
    return all(t in v.sparks for t in active)


def p_full(card, pot, p1, p2, dk, active) -> float:
    """Chance one run's kept child (better of two rolls) carries every
    active target: per target bought white / gold / not, both rolls
    sharing what was bought; E[1 - (1 - x)^2] = 2E[x] - E[x^2]."""
    s = sim.setup(card, pot, p1, p2, dk)
    if s is None:
        return 0.0
    hints, _ = s
    e1 = e2 = 1.0
    for t, (h, g, k) in zip(TARGETS, hints, strict=True):
        if t not in active:
            continue
        rg, rn = min(1.0, sim.BASE["gold"] * 1.1 ** k), sim.BASE["normal"] * 1.1 ** k
        e1 *= g * rg + (h - g) * rn
        e2 *= g * rg ** 2 + (h - g) * rn ** 2
    return 2 * e1 - e2


class Loop:
    def __init__(self, vets, trainees, rental, policy, order, rng):
        self.vets, self.trainees, self.rental = list(vets), trainees, rental
        self.policy, self.order, self.rng = policy, order, rng
        self.active = LATE[:NEEDED]
        self.reached: dict[int, float] = {}
        self.used = collections.Counter()
        self._best: dict = {}
        set_active(self.active)

    def pool(self):
        if self.policy == "fiery":
            return [v for v in self.vets if v.chara != FIERY // 100]
        return self.vets

    def best_run(self, p1, p2):
        """The trainee (and deck) a run with these parents is best with."""
        key = (p1.id, p2.id, len(self.active))
        if key not in self._best:
            best = None
            for card, pot in self.trainees.items():
                if self.policy == "fiery" and card != FIERY:
                    continue
                if card // 100 in (p1.chara, p2.chara):
                    continue
                for dk in sim.DECKS:
                    r = sim.expected(card, pot, p1, p2, dk)
                    if r and (best is None or r[0] > best[0]):
                        best = (r[0], card, pot, dk)
            self._best[key] = best
        return self._best[key]

    def pick(self, borrow: bool):
        """Own parent by lineage value (the best that has a run), the other
        parent, and the run's trainee and deck."""
        pool = sorted(self.pool(), key=sim.value, reverse=True)
        for p in pool[:12]:
            if borrow:
                if p.chara == self.rental.chara:
                    continue
                other = self.rental
            else:
                other = next((q for q in pool if q.chara != p.chara), None)
                if other is None:
                    continue
            b = self.best_run(p, other)
            if b:
                return p, other, b
        raise RuntimeError("no run possible")

    def grow(self, day: float) -> None:
        """Add targets while some veteran carries the whole list."""
        while len(self.active) < len(LATE) and any(all_of(v, self.active) for v in self.vets):
            self.reached.setdefault(len(self.active), day)
            rest = [t for t in LATE if t not in self.active]
            if self.order == "tier":
                nxt = rest[0]
            else:
                p, other, (_, card, pot, dk) = self.pick(True)
                _, per = sim.expected(card, pot, p, other, dk)
                rate = dict(zip(TARGETS, per, strict=True))
                nxt = max(rest, key=lambda t: rate[t])
            self.active = self.active + [nxt]
            set_active(self.active)
            self._best.clear()

    def run_days(self, days: int, runs: int, borrows: int) -> None:
        for d in range(days):
            for r in range(runs):
                p, other, (_, card, pot, dk) = self.pick(r < borrows)
                child = sim.run(self.rng, card, pot, p, other, dk)
                self.vets.append(child)
                self.used[card] += 1
                if all_of(child, self.active):
                    self.grow(d + (r + 1) / runs)
        if any(all_of(v, self.active) for v in self.vets):
            self.reached.setdefault(len(self.active), days)

    def end_chance(self) -> float:
        p, other, (_, card, pot, dk) = self.pick(True)
        return p_full(card, pot, p, other, dk, self.active)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cli.inputs(ap)
    ap.add_argument("--deck", help="card ids (6, the friend card included): the deck's hint rates from card_hints.json")
    ap.add_argument("--policy", default="rotate,fiery")
    ap.add_argument("--order", choices=["cheap", "tier"], default="cheap")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--borrows", type=int, default=5)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    cli.init(args)
    world.set_targets(LATE)
    if args.deck:
        sim.DECK_CARDS[:] = [int(c) for c in args.deck.split(",")]
        sim.CARD_HINTS = str(cli.COMPANION_DATA / "card_hints.json")
    sim.set_scenario(args.scenario)
    names = world.names()["uma_cards"]

    vets0, trainees = load_box()
    rental = load_rental()
    sim.RENTAL = rental
    for policy in args.policy.split(","):
        rng = random.Random(args.seed)
        reached = collections.defaultdict(list)
        used = collections.Counter()
        ends, sizes = [], []
        for _ in range(args.reps):
            loop = Loop(vets0, trainees, rental, policy, args.order, rng)
            loop.run_days(args.days, args.runs, args.borrows)
            for n in range(NEEDED, len(LATE) + 1):
                reached[n].append(loop.reached.get(n))
            used.update(loop.used)
            ends.append(loop.end_chance())
            sizes.append(len(loop.active))
        print(f"\n== {policy}, {args.days} days x {args.runs} runs ({args.borrows} borrows), {args.reps} reps, order {args.order}")
        marks = [m for m in (30, 60, 90, 120, 180) if m <= args.days] or [args.days]
        print("  first veteran carrying n/n, share of replications by day " + " / ".join(map(str, marks)))
        for n in range(NEEDED, len(LATE) + 1):
            got = [d for d in reached[n] if d is not None]
            if not got:
                continue
            shares = " / ".join(f"{100 * sum(1 for d in got if d <= m) / args.reps:3.0f}%" for m in marks)
            print(f"  {n:2}/{n:<2}  {shares}   (median day of those {statistics.median(got):5.1f})")
        tot = sum(used.values())
        top = ", ".join(f"{names.get(str(c), {}).get('name', c)} {100 * k / tot:.0f}%" for c, k in used.most_common(6))
        print(f"  trainees: {top}")
        print(f"  list at the end: median {statistics.median(sizes)} targets; a run's chance of an n/n child then: "
              f"median {100 * statistics.median(ends):.2f}%")


if __name__ == "__main__":
    main()

"""The best setups for Vodka [Fiery Aqua Vitae] per looping scenario (URA
Finale, Unity Cup): own pair and with the rental, expected target sparks a
run and the chance of a 4+ of 5 parent (best of two rolls), then the top
own pairs.

    python scenarios.py --master ... --account ... --rental ...
"""
from __future__ import annotations

import argparse

import cli
import sim
import strategies as S
from world import load_box, load_rental, names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cli.inputs(ap)
    ap.add_argument("--fiery-potential", type=int, default=5)
    args = ap.parse_args()
    cli.init(args)
    cards = names()["uma_cards"]

    def name(c):
        return cards.get(str(c), {}).get("name", c)

    def lab(u):
        return f"{name(u.card)} {u.rank:,}" if getattr(u, "rank", 0) else f"{name(u.card)} (rental)"

    vets, trainees = load_box()
    trainees[S.FIERY] = max(trainees.get(S.FIERY, 1), args.fiery_potential)
    rental = load_rental()
    sim.RENTAL = rental
    print(len(vets), "veterans; Fiery potential", trainees[S.FIERY])
    for sc, sname in ((1, "URA Finale"), (2, "Unity Cup")):
        sim.set_scenario(sc)
        st = S.State(vets, trainees, rental)
        own = st.best_setup(S.FIERY, False)
        rent = st.best_setup(S.FIERY, True)
        for tag, b in (("own pair", own), ("with the rental", rent)):
            e, p1, p2, dk, per = b
            print(f"{sname:<11} {tag:<16} {lab(p1)} x {lab(p2)} | deck {dk.name.split('/')[0]} | {e:.2f} target sparks/run"
                  f" | 4+ of 5 per run (best of two rolls) {sim.best_of_two_4plus(per):.1%}")
        # The top own pairs.
        pool = [v for v in vets if v.chara != S.FIERY // 100]
        top = sorted(pool, key=lambda v: st.proxy(S.FIERY, v), reverse=True)[:10]
        pairs = []
        for i, a in enumerate(top):
            for b in top[i + 1:]:
                if a.chara == b.chara:
                    continue
                for dk in sim.DECKS:
                    r = sim.expected(S.FIERY, trainees[S.FIERY], a, b, dk)
                    if r:
                        pairs.append((r[0], sim.best_of_two_4plus(r[1]), lab(a), lab(b), dk.name.split("/")[0]))
        pairs.sort(reverse=True)
        seen = set()
        for p in pairs:
            if (p[2], p[3]) in seen:
                continue
            seen.add((p[2], p[3]))
            print(f"     {p[2]} x {p[3]} ({p[4]}): {p[0]:.2f}, 4+ {p[1]:.1%}")
            if len(seen) == 5:
                break


if __name__ == "__main__":
    main()

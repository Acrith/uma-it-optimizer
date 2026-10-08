"""Parity fixtures for the companion's all-targets chance (its setup.ts
`keptAll`): lineage.p_full on given per-target (hint, gold, carriers), the
setup itself stubbed out. Synthetic numbers, no player data.

    python fixture_full.py [--out <umaladder-companion>/ui/src/loop/fixtures/full.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lineage
import sim
import world

# (name, per target (hint, gold, carriers of the six)); gold never above
# hint, as sim.setup makes it.
CASES = [
    ("one white target, 3 carriers", [(0.6, 0.0, 3)]),
    ("one target, gold half the time, 6 carriers (gold roll 70.9%)", [(0.8, 0.5, 6)]),
    ("her own skill: hint and gold certain", [(1.0, 1.0, 2)]),
    ("a target never hinted", [(0.0, 0.0, 4), (0.9, 0.0, 2)]),
    ("six targets, a Unity Cup line",
     [(1.0, 1.0, 6), (1.0, 1.0, 5), (0.97, 0.0, 6), (1.0, 1.0, 6), (0.62, 0.0, 6), (0.55, 0.0, 5)]),
    ("five white targets, few carriers",
     [(0.5, 0.0, 1), (0.4, 0.0, 0), (0.7, 0.1, 2), (0.3, 0.0, 1), (0.9, 0.2, 3)]),
]
COMPANION = Path(__file__).resolve().parents[4] / "umaladder-companion"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(COMPANION / "ui/src/loop/fixtures/full.json"))
    args = ap.parse_args()
    cases = []
    for name, per in CASES:
        targets = [f"target {i}" for i in range(len(per))]
        world.TARGETS[:] = targets          # in place: lineage and sim read this list
        sim.setup = lambda *_, per=per: (tuple(per), 0)
        p = lineage.p_full(0, 0, None, None, None, targets)
        rows = [{"hint": h, "gold": g, "carriers": k} for h, g, k in per]
        cases.append({"name": name, "per": rows, "expect": p})
    source = ("uma-it-optimizer tools/loop/sim/fixture_full.py: lineage.p_full on given per-target "
              "(hint, gold, carriers); the kept child of two rolls carries every target")
    out = {"_source": source, "cases": cases}
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cases)} cases -> {args.out}")


if __name__ == "__main__":
    main()

"""In-breeding and the G1s (owner, 2026-10-26: "Selfcest is not properly done on website I think?").
An in-bred grandparent (the trainee's own character) adds no trio relation: measured 2026-10-05
(affinity.py). Untested so far: whether the G1s she and her child (the parent) both won still add
their 3 points each, to her affinity and to her child's. The site and the companion count them.

PREDICTION (written before the run): they still count. Her factors and her child's fire as the
model predicts with the G1s kept; with them dropped as well, the prediction falls short of what
fired.

Per inspiration event (Classic, Senior), every factor carried by exactly one ancestor: fired
against min(1, base x (1 + affinity / 100)) for three affinities: as modelled (trio zero, G1s
kept), G1s dropped too, and the trio counted (the model before 2026-10-05).

    python inbred_g1.py --master master.mdb --receipts runs/

RESULT 2026-10-26 (36,786 IT runs to 2026-10-19, 13,129 with an in-bred grandparent; she and her
child had won 19 G1s both, median): CONFIRMED, the G1s still count. Her whites fired 8.30%
(8.16-8.44) against 8.33% modelled, 5.43% with the G1s dropped, 9.61% with the trio counted; her
child's 17.07% (16.86-17.29) against 17.15% / 14.30% / 18.42%. The site's "in-bred" row (relation
zero, the G1s added) is right.
"""
# ruff: noqa: E501  (report lines)

from __future__ import annotations

import argparse
import collections
import glob

from affinity import Affinity
from hint_tests import BASE, TYPES, _factors, _load, _Master, _wins, wilson
from loopdata import Uma


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--receipts", required=True)
    args = ap.parse_args()
    master = _Master(args.master)
    kind = {fid: (TYPES.get(t), r) for fid, t, r in master.db.execute("select factor_id, factor_type, rarity from succession_factor")}
    aff = Affinity(master)
    # role -> [trials, fired, p modelled, p G1s dropped, p trio counted]
    rows: dict[str, list[float]] = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    seen, runs, inbred_runs, g1s = set(), 0, 0, collections.Counter()
    for path in glob.glob(f"{args.receipts}/*/*.json*"):
        try:
            d = _load(path)
            smc = d["SingleModeChara"][0]
            gain = {y["<Year>k__BackingField"]: {g["<FactorId>k__BackingField"] for g in y["<GainFactorInfoArray>k__BackingField"]}
                    for y in d["SuccessionFactorGainInfo"]}
            parents = d["Parents"]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        key = (smc.get("start_time"), smc.get("card_id"), smc.get("succession_trained_chara_id_1"))
        if key in seen or len(parents) != 2 or 2 not in gain or 3 not in gain:
            continue
        seen.add(key)
        facts: dict[int, list[int]] = {}
        umas = []
        for p in parents:
            lst = p.get("<SuccessionCharaList>k__BackingField") or {}
            gps = [g for g in (lst.get("_items") or [])[: lst.get("_size") or 0] if isinstance(g, dict) and g.get("_positionId") in (10, 20)]
            gu = [Uma(g["<CardId>k__BackingField"], {}, _wins(g)) for g in gps]
            u = Uma(p["_cardId"], {}, _wins(p), gu)
            umas.append(u)
            facts[id(u)] = _factors(p)
            for g, x in zip(gu, gps, strict=True):
                facts[id(g)] = _factors(x)
        r = aff.evaluate(smc["card_id"], *umas)
        if not r or len(r["members"]) != 6:
            continue
        runs += 1
        t = smc["card_id"] // 100
        inbred = [(p, g) for p in umas for g in p.parents if g.chara == t]
        if not inbred:
            continue
        inbred_runs += 1
        drop: collections.Counter = collections.Counter()   # the G1 points each member would lose
        trio: collections.Counter = collections.Counter()   # the trio points each member would gain
        roles = {}
        for p, g in inbred:
            race = aff.race(p, g)
            g1s[race // 3] += 1
            drop[id(g)] += race
            drop[id(p)] += race
            rel = aff.rel(t, p.chara, g.chara)
            trio[id(g)] += rel
            trio[id(p)] += rel
            roles[id(g)] = "in-bred grandparent"
            roles[id(p)] = "its child (a parent)"
        carriers = collections.Counter(f for fs in facts.values() for f in fs)
        for m, a, _ in r["members"]:
            role = roles.get(id(m))
            if role is None:
                continue
            for f in facts[id(m)]:
                if carriers[f] != 1:
                    continue
                tt, stars = kind.get(f, (None, 0))
                if tt not in BASE:
                    continue
                base = BASE[tt][stars - 1]
                for y in (2, 3):
                    for label in (role, f"{role} · {'whites' if tt == 'white' else 'others'}"):
                        row = rows[label]
                        row[0] += 1
                        row[1] += f in gain[y]
                        row[2] += min(1.0, base * (1 + a / 100))
                        row[3] += min(1.0, base * (1 + (a - drop[id(m)]) / 100))
                        row[4] += min(1.0, base * (1 + (a + trio[id(m)]) / 100))
    print(f"{runs} runs read, {inbred_runs} with an in-bred grandparent; G1s she and her child both won: "
          f"median {sorted(g1s.elements())[len(list(g1s.elements())) // 2] if g1s else 0}")
    print(f"\n{'role':42s} {'trials':>8s} {'fired':>7s} {'95% CI':>15s}   {'modelled':>8s} {'G1s dropped':>11s} {'trio counted':>12s}")
    for label in sorted(rows):
        n, y, pm, pd, pt = rows[label]
        lo, hi = wilson(y, n)
        print(f"{label:42s} {int(n):8d} {y / n:7.2%} {lo:7.2%}-{hi:6.2%}   {pm / n:8.2%} {pd / n:11.2%} {pt / n:12.2%}")


if __name__ == "__main__":
    main()

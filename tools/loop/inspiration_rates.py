"""Check the inspiration rule against site receipts.

A receipt records which factors fired at the Classic and Senior inspiration
(SuccessionFactorGainInfo years 2 and 3), next to the trainee's 2 parents and
4 grandparents with their factors. A factor id carried by exactly one of the
6 ancestors is attributed to it; each (ancestor, factor, event) is a trial.
Prints fired vs predicted by type, stars and position: base x (1 + that
ancestor's affinity / 100) from affinity.py, and the same with grandparents
halved.

    python inspiration_rates.py --master master.mdb --receipts runs/

`runs/` as pulled from the site: runs/<user>/<file>.json (or .json.gz).
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import sqlite3

from affinity import Affinity
from loopdata import Uma

TYPES = {1: "blue", 2: "pink", 3: "green", 4: "white", 5: "race", 6: "scenario"}
BASE = {"blue": (0.70, 0.80, 0.90), "pink": (0.01, 0.03, 0.05), "green": (0.05, 0.10, 0.15),
        "white": (0.03, 0.06, 0.09), "race": (0.01, 0.02, 0.03), "scenario": (0.03, 0.06, 0.09)}


class _Master:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)


def _factors(x: dict) -> list[int]:
    return [f["<FactorId>k__BackingField"] for f in x.get("<FactorDataArray>k__BackingField") or []
            if isinstance(f, dict) and "<FactorId>k__BackingField" in f]


def _wins(x: dict) -> list[int]:
    return [w for w in x.get("_winSaddleIdArray") or [] if isinstance(w, int)]


def _load(path: str) -> dict:
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def trials(receipts: str, aff: Affinity):
    """Yield (position, factor id, affinity, fired) per attributable trial."""
    seen = set()
    for path in glob.glob(f"{receipts}/*/*.json*"):
        try:
            d = _load(path)
            smc = d["SingleModeChara"][0]
            gain = {}
            for y in d["SuccessionFactorGainInfo"]:
                fired = y["<GainFactorInfoArray>k__BackingField"]
                gain[y["<Year>k__BackingField"]] = [g["<FactorId>k__BackingField"] for g in fired]
            parents = d["Parents"]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        key = (smc.get("start_time"), smc.get("card_id"), smc.get("succession_trained_chara_id_1"))
        if len(parents) != 2 or 2 not in gain or 3 not in gain or key in seen:
            continue
        seen.add(key)
        facts: dict[int, list[int]] = {}
        umas = []
        for p in parents:
            gps = [g for g in p["<SuccessionCharaList>k__BackingField"]["_items"]
                   if isinstance(g, dict) and g.get("_positionId") in (10, 20)]
            gu = [Uma(g["<CardId>k__BackingField"], {}, _wins(g)) for g in gps]
            u = Uma(p["_cardId"], {}, _wins(p), gu)
            umas.append(u)
            facts[id(u)] = _factors(p)
            for g, x in zip(gu, gps, strict=True):
                facts[id(g)] = _factors(x)
        r = aff.evaluate(smc["card_id"], *umas)
        if not r or len(r["members"]) != 6:
            continue
        carriers = collections.Counter(f for fs in facts.values() for f in fs)
        for i, (m, a, _) in enumerate(r["members"]):
            for f in facts[id(m)]:
                if carriers[f] == 1:
                    for y in (2, 3):
                        yield ("parent" if i < 2 else "grandparent"), f, a, f in gain[y]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--receipts", required=True)
    args = ap.parse_args()
    master = _Master(args.master)
    kind = {fid: (TYPES.get(t), r) for fid, t, r in
            master.db.execute("select factor_id, factor_type, rarity from succession_factor")}
    agg: dict[tuple, list[float]] = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for pos, f, a, fired in trials(args.receipts, Affinity(master)):
        t, stars = kind.get(f, (None, 0))
        if t not in BASE:
            continue
        p = BASE[t][stars - 1] * (1 + a / 100)
        row = agg[(t, stars, pos)]
        row[0] += 1
        row[1] += fired
        row[2] += min(1.0, p)
        row[3] += min(1.0, p / 2 if pos == "grandparent" else p)
        row[4] += a
    print(f"{'type':8} {'stars':>5} {'position':11} {'trials':>7} {'fired':>6} {'formula':>7}"
          f" {'gp half':>7} {'affinity':>8}")
    for (t, stars, pos), (n, fired, p, half, a) in sorted(agg.items()):
        print(f"{t:8} {stars:5} {pos:11} {n:7.0f} {fired / n:6.1%} {p / n:7.1%}"
              f" {half / n:7.1%} {a / n:8.0f}")


if __name__ == "__main__":
    main()

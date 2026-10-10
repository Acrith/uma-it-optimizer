"""Spark luck: can a player's white sparks be called lucky or unlucky?

Each spark screen's two rolls against the measured roll rule (spark_rolls.py,
2026-10-08): a white skill she owns sparks at 20.0 / 25.5 / 39.9% (white /
◎ / gold) x 1.101 per carrier of her six ancestors, every skill on its own,
the two rolls independent. Per roll: expected whites E = sum p, variance
V = sum p(1 - p), got. Per player: z = (got - E) / sqrt(V) over their rolls.
If the rule is all there is, z is luck and nothing else; if a player's z
carries over from one half of their rolls to the other, the rule misses
something about how they play, and "unlucky" would be a wrong label.

Also, as groundwork for a 3★ board (no luck drawn from it yet): the stars of
each spark kind, blue by the picked stat's final value, pink and the rest by
the run's final grade.

PREDICTIONS, written 2026-10-10 before the first run:
  L1  players with 20+ rolls: z has mean within ±0.15 and sd 0.9-1.2.
  L2  |z| > 2 for 2-9% of them (4.6% if normal).
  L3  per roll, the randomized P(Y < got) + u P(Y = got) is uniform: each
      tenth holds 10% ± 2 points of the rolls.
  L4  luck doesn't carry over: a player's z on the first half of their rolls
      (by time) and on the second half correlate at |r| < 0.15 (40+ rolls).
  L5  z doesn't follow how many carriers they bring: players' mean z by the
      tercile of their mean carriers per owned white within ±0.3 of 0.
  S1  blue 3★: none below 600 in the picked stat; about 5.5% at 600-699
      rising to about 10.4% at 1200+ (the parenting guide's chart).
  S2  pink stars don't move with the final grade (3★ within ±2 points
      across grade bands).
  S3  green (unique) stars follow the white table by grade: 3★ about 5%
      below SS, about 10% at SS and up.

RESULTS, 2026-10-10 (site copy of 2026-10-07: 4,749 rolls of 112 players,
whites got / expected 1.005):
  L1  pass: 20+ rolls, 64 players: mean +0.13, sd 1.03.
  L2  pass: 4.7%.
  L3  pass: tenths 9.5-10.6%. Tails: P(at least got) <= 5% in 3.1% of rolls,
      <= 1% in 0.63%, <= 0.1% in 0.063%.
  L4  pass: r +0.04 (41 players with 40+ rolls), -0.04 (18 with 80+).
  L5  marginal: +0.26 / -0.31 / +0.42 (about 21 players each, SE about
      0.22; not monotonic): no sign of a bias by carriers.
  S1  pass, and the split follows the picked stat's grade: below 600
      90/10/0, 600-1099 about 50/45/5, 1100-1199 24/68/8, 1200+ 19/69/12.
  S2  pass: pink 20/70/10 whatever the grade.
  S3  pass: green below S 51/43/6, like the whites (50/44/5).
  The run's grade floor and ceiling straddle a band in about 80% of rolls:
  the final grade isn't known from the run (S2/S3 bands are thin for it).
So a player's z over their rolls is luck: the site's spark luck
(uma-it-web services/spark_luck.py) scores every roll this way.

    uv run python tools/loop/spark_luck.py --db prod-copy.sqlite \\
        --runs runs/ --master master.mdb [--out rolls.json]

Prints aggregates only: no player, run or veteran is named. --out writes the
per-roll numbers (with the site's user ids: keep it out of this repo).
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import random
import sqlite3

import numpy as np
from spark_rolls import ancestors, load_master, owned, white_groups

RATE = {"normal": 0.200, "double": 0.255, "gold": 0.399}
PER_CARRIER = 1.101
STATS = ("speed", "stamina", "power", "guts", "wiz")
# Final grade bands by rank (uma-it-web lookups.LETTER_GRADE_BY_RANK): 15 S, 17 SS, 39 UE.
BANDS = ((None, "below S"), (15, "S, S+"), (17, "SS to UF"), (39, "UE and up"))


def band(lo, hi) -> str:
    if lo is None or hi is None:
        return "unknown"
    name = lambda r: [n for s, n in BANDS if s is None or r >= s][-1]  # noqa: E731
    return name(lo) if name(lo) == name(hi) else "between"


def pbinom(ps: list[float]) -> list[float]:
    """The Poisson-binomial distribution of independent trials: P(Y = n)."""
    d = [1.0]
    for p in ps:
        nd = [0.0] * (len(d) + 1)
        for n, q in enumerate(d):
            nd[n] += q * (1 - p)
            nd[n + 1] += q * p
        d = nd
    return d


def load(db: str, runs: str, ms):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ranks = {
        (u, f): (lo, hi)
        for u, f, lo, hi in c.execute(
            "select user_id, filename, rank_floor, rank_ceiling from runs"
        )
    }
    rolls, stars, stats = [], collections.Counter(), collections.Counter()
    for uid, run_file, raw in c.execute(
        "select user_id, run_file, record from spark_screens order by captured_at"
    ):
        stats["screens"] += 1
        rec = json.loads(raw)
        try:
            doc = json.load(gzip.open(f"{runs}/{uid}/{run_file}.gz"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            stats["no receipt"] += 1
            continue
        anc = ancestors(doc)
        if anc is None:
            stats["no full lineage"] += 1
            continue
        chara = (doc.get("SingleModeChara") or [{}])[0]
        grade = band(*ranks.get((uid, run_file), (None, None)))
        anc_groups = [white_groups(f, ms) for _, f in anc]
        mine = owned(rec, ms)
        for roll in sorted(rec.get("rolls") or [], key=lambda r: r.get("lottery_id", 0))[:2]:
            fids = roll.get("factors") or []
            got = white_groups(fids, ms)
            ps, y, ks = [], 0, []
            for sg, v in mine.items():
                g, pg = ms.plain[sg], ms.plus.get(sg)
                if pg is not None and pg in got:
                    stats["came up as its +"] += 1
                    continue
                k = sum(1 for gs in anc_groups if g in gs)
                ps.append(min(0.99, RATE[v] * PER_CARRIER**k))
                ks.append(k)
                y += g in got
            rolls.append(
                {
                    "u": uid,
                    "at": rec.get("captured_at") or 0,
                    "ps": ps,
                    "y": y,
                    "k": ks,
                    "grade": grade,
                }
            )
            stats["rolls"] += 1
            # Stars by kind: blue by the picked stat's final value, the rest by grade.
            for f in fids:
                _, s, t = ms.factor.get(f, (None, 0, 0))
                if t == 1:
                    stat = STATS[f // 100 - 1] if 1 <= f // 100 <= 5 else None
                    val = chara.get(stat) if stat else None
                    if val is not None:
                        stars[("blue", min(12, max(5, val // 100)), s)] += 1
                elif t in (2, 3, 4):
                    stars[({2: "pink", 3: "green", 4: "white"}[t], grade, s)] += 1
    return rolls, stars, stats


def zscore(rs) -> float:
    e = sum(sum(r["ps"]) for r in rs)
    v = sum(p * (1 - p) for r in rs for p in r["ps"])
    return (sum(r["y"] for r in rs) - e) / math.sqrt(v) if v > 0 else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    rolls, stars, stats = load(args.db, args.runs, load_master(args.master))
    print("data:", dict(stats))
    by = collections.defaultdict(list)
    for r in rolls:
        by[r["u"]].append(r)
    e_all = sum(sum(r["ps"]) for r in rolls)
    got_all = sum(r["y"] for r in rolls)
    print(
        f"rolls {len(rolls)}, players {len(by)}; whites got {got_all} / expected {e_all:.0f}"
        f" = {got_all / e_all:.3f}; mean expected a roll {e_all / len(rolls):.2f}"
    )

    print("\n== L1, L2: players' z (whites got vs expected over all their rolls)")
    for n_min in (5, 20, 40):
        zs = np.array([zscore(rs) for rs in by.values() if len(rs) >= n_min])
        print(
            f"   {n_min:>2}+ rolls: {len(zs):>3} players,"
            f" z mean {zs.mean():+.2f} sd {zs.std(ddof=1):.2f},"
            f" |z|>2 {np.mean(abs(zs) > 2):5.1%}, min {zs.min():+.2f} max {zs.max():+.2f}"
        )

    print("\n== L3: each roll's randomized PIT, by tenths (uniform: 10% each)")
    rng = random.Random(7)
    pit = []
    for r in rolls:
        d = pbinom(r["ps"])
        pit.append(sum(d[: r["y"]]) + rng.random() * d[r["y"]])
    h = np.histogram(pit, bins=10, range=(0, 1))[0] / len(pit)
    print("   " + " ".join(f"{x:5.1%}" for x in h))
    tail = np.array([sum(pbinom(r["ps"])[r["y"] :]) for r in rolls])
    print(
        f"   rolls at P(at least got) <= 5%: {np.mean(tail <= 0.05):.1%},"
        f" <= 1%: {np.mean(tail <= 0.01):.2%}, <= 0.1%: {np.mean(tail <= 0.001):.3%}"
    )

    print("\n== L4: does luck carry over? first half vs second half of a player's rolls (by time)")
    for n_min in (40, 80):
        a, b = [], []
        for rs in by.values():
            if len(rs) >= n_min:
                rs = sorted(rs, key=lambda r: r["at"])
                a.append(zscore(rs[: len(rs) // 2]))
                b.append(zscore(rs[len(rs) // 2 :]))
        if len(a) >= 5:
            print(f"   {n_min}+ rolls: {len(a)} players, r = {np.corrcoef(a, b)[0, 1]:+.2f}")

    print("\n== L5: z by the tercile of a player's mean carriers per owned white (20+ rolls)")
    rows = [
        (np.mean([k for r in rs for k in r["k"]]), zscore(rs))
        for rs in by.values()
        if len(rs) >= 20
    ]
    rows.sort()
    for i, part in enumerate(np.array_split(np.array(rows), 3)):
        print(
            f"   tercile {i + 1}: carriers {part[:, 0].min():.2f}-{part[:, 0].max():.2f},"
            f" players {len(part)}, mean z {part[:, 1].mean():+.2f}"
        )

    print("\n== S1: blue stars by the picked stat's final value")
    for b in range(5, 13):
        n = sum(stars[("blue", b, s)] for s in (1, 2, 3))
        if n:
            lab = "<600" if b == 5 else "1200+" if b == 12 else f"{b * 100}-{b * 100 + 99}"
            print(
                f"   {lab:>9}: {n:>5}  "
                + "  ".join(f"{s}★ {stars[('blue', b, s)] / n:5.1%}" for s in (1, 2, 3))
            )
    for kind, label in (("pink", "S2"), ("green", "S3"), ("white", "(whites, for reference)")):
        print(f"\n== {label}: {kind} stars by final grade")
        for g in sorted({k[1] for k in stars if k[0] == kind}):
            n = sum(stars[(kind, g, s)] for s in (1, 2, 3))
            if n >= 30:
                print(
                    f"   {g:>10}: {n:>5}  "
                    + "  ".join(f"{s}★ {stars[(kind, g, s)] / n:5.1%}" for s in (1, 2, 3))
                )

    if args.out:
        with open(args.out, "w") as f:
            json.dump(rolls, f)
        print(f"\nper-roll numbers -> {args.out}")


if __name__ == "__main__":
    main()

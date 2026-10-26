"""Homebrew (H2): does the spark roll hold on own pairs, and does a veteran who sits on both sides
count as two carriers? Companion spark screens joined to their receipts, as spark_rolls.py reads
them: one trial per white skill she owned per roll, against 20 / 25 / 40% x 1.1 per carrier. The
carriers counted over all six (as the rule has it) and over distinct veterans (a copy counted once),
by run kind (own pair / a borrowed parent).

Predictions: ~/workspace/uma-loop-local/homebrew/PREDICTIONS.md (H2), written before the run.

    python homebrew_rolls.py --db prod-copy.sqlite --runs runs/ --master master.mdb

Prints aggregates only.

RESULT 2026-10-26 (15,598 spark screens joined to receipts to 2026-10-19: 8,691 own pairs, 6,907 borrow runs):
CONFIRMED. Own pairs spark at 1.001 of the rule (322,975 trials), borrow runs 0.997 (301,089). Where a carrier sits
twice among the six, counting every copy fits (own 1.003, borrow 0.991) and counting veterans once doesn't (1.123,
1.090): a veteran on both sides is two carriers for the roll too.
"""
# ruff: noqa: E501  (report lines)

from __future__ import annotations

import argparse
import collections
import gzip
import json
import sqlite3

from spark_rolls import BASE, factor_ids, load_master, owned, white_groups, wilson


def lineage(doc: dict) -> tuple[list[tuple[int, tuple]], str] | None:
    """The six as (card, sorted factor ids), and the run's kind."""
    out = []
    parents = doc.get("Parents") or []
    for p in parents:
        out.append((p.get("_cardId"), tuple(sorted(factor_ids(p)))))
        lst = p.get("<SuccessionCharaList>k__BackingField") or {}
        for g in (lst.get("_items") or [])[: lst.get("_size") or 0]:
            if g and g.get("_positionId") in (10, 20):
                out.append((g.get("<CardId>k__BackingField"), tuple(sorted(factor_ids(g)))))
    if len(parents) != 2 or len(out) != 6:
        return None
    return out, "borrow" if any(p.get("_ownerViewerId") for p in parents) else "own"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--master", required=True)
    args = ap.parse_args()
    ms = load_master(args.master)
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    # bucket -> [trials, sparked, rule over all six, rule over distinct veterans]
    rows: dict[tuple, list[float]] = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    stats = collections.Counter()
    for uid, run_file, raw in c.execute("select user_id, run_file, record from spark_screens"):
        if not run_file:
            continue
        try:
            doc = json.load(gzip.open(f"{args.runs}/{uid}/{run_file}.gz"))
        except (FileNotFoundError, OSError, ValueError):
            stats["no receipt"] += 1
            continue
        got = lineage(doc)
        if got is None:
            stats["no full lineage"] += 1
            continue
        six, kind = got
        rec = json.loads(raw)
        rolls = sorted(rec.get("rolls") or [], key=lambda r: r.get("lottery_id", 0))
        if not rolls:
            continue
        stats[f"screens {kind}"] += 1
        groups = [(sig, white_groups(list(sig[1]), ms)) for sig in six]
        mine = owned(rec, ms)
        for roll in rolls[:2]:
            fired = white_groups(roll.get("factors") or [], ms)
            for sg, v in mine.items():
                g, pg = ms.plain[sg], ms.plus.get(sg)
                if pg is not None and pg in fired:
                    continue                      # came up as its "+": says nothing of the plain spark
                carriers = [sig for sig, gs in groups if g in gs]
                k_all, k_one = len(carriers), len(set(carriers))
                p_all = min(1.0, BASE[v] * 1.1 ** k_all)
                p_one = min(1.0, BASE[v] * 1.1 ** k_one)
                hit = g in fired
                keys = [(kind, "all"), (kind, f"{v}")]
                if k_all > k_one:
                    keys.append((kind, f"a carrier twice ({k_all} carriers, {k_one} veterans)" if k_all - k_one == 1 and k_all <= 6 else "a carrier twice (more)"))
                    keys.append((kind, "a carrier twice: all"))
                for key in keys:
                    r = rows[key]
                    r[0] += 1
                    r[1] += hit
                    r[2] += p_all
                    r[3] += p_one
    print("screens:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    print(f"\n{'kind':7s} {'bucket':44s} {'trials':>7s} {'sparked':>8s} {'95% CI':>15s} {'k all six':>10s} {'obs/rule':>8s} {'k distinct':>10s} {'obs/rule':>8s}")
    for key in sorted(rows):
        n, y, e, e1 = rows[key]
        lo, hi = wilson(y, n)
        print(f"{key[0]:7s} {key[1]:44s} {int(n):7d} {y / n:8.2%} {lo:7.2%}-{hi:6.2%} {e / n:10.2%} {y / e:8.3f} {e1 / n:10.2%} {y / e1:8.3f}")


if __name__ == "__main__":
    main()

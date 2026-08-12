"""Solve the per-card skill-point weight table W from run JSONs.

The SP channel's structure (validated 2026-08-13):

    sp_card = floor(h_run * W_card)

W is a GLOBAL property of (card, level) — the same across decks,
scenarios and race counts (pair ratios stable to ~1-2%, pure floor
noise). h_run is a per-run scalar that absorbs scenario, race count
(roughly tracking T(races)) and the run's randomness (~±5-6% between
identical setups; SP is the one non-deterministic channel in the
deterministic scenarios).

Unity Cup runs are excluded: its long careers carry a variable run
scalar on stats as well (see it-formula.md 2026-08-13), so nothing
from Unity is used to calibrate anything.

Solved by alternating fixed effects: h_run = sum(sp)/sum(W) per run,
W = mean(sp/h) per (card, level). Converges in a few dozen rounds.

Usage:
    python sp_weights.py --mdb master.mdb --runs <dir-of-user-dirs> \
        [--ref 30010:50] [--min-n 5]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from it_formula import Masters, load_run


def collect(runs_dir: Path, masters: Masters) -> list[dict]:
    """One record per usable run: {scen, races, sp: {(card, level): sp+0.5}}."""
    out = []
    for p in sorted(runs_dir.glob("*/*.json")):
        try:
            r = load_run(p, masters)
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not r or r["scenario"] == 2 or r.get("has_pal"):
            continue
        if not r["races"] or not (4 <= r["races"] <= 40):
            continue
        lv = {x.card_id: x.level for x in r["rows"]}
        sps = {}
        for e in raw.get("SupportCardGainInfo") or []:
            cid = e["<SupportCardId>k__BackingField"]
            if cid in lv:
                sp = e["<GainInfo>k__BackingField"].get("<SkillPoint>k__BackingField")
                if sp:
                    # +0.5: floor-midpoint, same convention as the stat sweep
                    sps[(cid, lv[cid])] = sp + 0.5
        if len(sps) >= 2:
            out.append({"scen": r["scenario"], "races": r["races"], "sp": sps})
    return out


def solve(runs: list[dict], rounds: int = 60) -> dict[tuple[int, int], float]:
    W: dict[tuple[int, int], float] = defaultdict(lambda: 1.0)
    for _ in range(rounds):
        acc = defaultdict(list)
        for o in runs:
            h = sum(o["sp"].values()) / sum(W[k] for k in o["sp"])
            for k, v in o["sp"].items():
                acc[k].append(v / h)
        W = {k: sum(v) / len(v) for k, v in acc.items()}
    return W


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True,
                    help="directory containing per-user run dirs")
    ap.add_argument("--ref", default="30010:50",
                    help="card:level whose W is normalized to 100")
    ap.add_argument("--min-n", type=int, default=5)
    args = ap.parse_args()

    masters = Masters(args.mdb)
    runs = collect(args.runs, masters)
    W = solve(runs)
    cnt: dict[tuple[int, int], int] = defaultdict(int)
    for o in runs:
        for k in o["sp"]:
            cnt[k] += 1

    rc, rl = (int(x) for x in args.ref.split(":"))
    ref = W.get((rc, rl))
    if not ref:
        print(f"reference {args.ref} not in data; using raw scale")
        ref = 1.0

    resid = []
    for o in runs:
        h = sum(o["sp"].values()) / sum(W[k] for k in o["sp"])
        for k, v in o["sp"].items():
            resid.append(abs(v / (h * W[k]) - 1))
    print(f"{len(runs)} runs, {len(W)} (card,level) cells, "
          f"median |resid| {100 * median(resid):.2f}%")
    print(f"{'card':>7} {'lv':>3} {'W':>7} {'n':>4}  name")
    for (cid, lvv), w in sorted(W.items(), key=lambda kv: -kv[1]):
        if cnt[(cid, lvv)] < args.min_n:
            continue
        print(f"{cid:>7} {lvv:>3} {w / ref * 100:>7.1f} {cnt[(cid, lvv)]:>4}  "
              f"{masters.card_name.get(cid, '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

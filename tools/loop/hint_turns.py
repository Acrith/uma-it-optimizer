"""A support card's training hints against the run's training turns.

Every IT run ends at turn 78 (all four scenarios); each race takes a turn,
so a run trains on at most T = 78 - races turns (rest and outing turns are
not recorded: T is an upper bound). A card on the trained facility can show
a hint; a training hint lands in the card's own gain bucket
(`SupportCardGainInfo[i].<GainInfo>.<SkillTipsArray>`, clean of other cards'
and the trainee's events), with the levels it added. One trial per run x
card x skill on the card's training hint list (`single_mode_hint_gain`,
type 0): did the run get that skill's hint from that card.

PREDICTIONS, written 2026-10-08 before the first run:
  H1  P(card c hints skill s in a run) = 1 - (1 - q_cs)^T with one per-turn
      q_cs: by T band the observed counts match the fit (pooled observed /
      predicted 0.97-1.03 in every band) and at most ~10% of card x skill
      cells reject it at p < 0.05.
  H2  a card's training skills share one per-turn rate (a hint picks one of
      its skills evenly): one q per card fits about as well as one per skill
      (at most ~15% of cards reject the shared rate at p < 0.05).
  H3  the hint levels a card adds grow in proportion to T (levels per
      training turn flat across T bands, within 10%).

    uv run python tools/loop/hint_turns.py --runs <receipts dir> --master <master.mdb>

Aggregates only.
"""
# ruff: noqa: E501  (report lines)

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import math
import sqlite3

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import chi2

TURNS = 78
T_BANDS = [(0, 39), (40, 47), (48, 55), (56, 63), (64, 78)]


def band(t: int) -> int:
    return next(i for i, (lo, hi) in enumerate(T_BANDS) if lo <= t <= hi)


def fit_q(ts: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """Per-turn q maximising the likelihood of P = 1 - (1-q)^T; returns
    (q, log-likelihood)."""

    def nll(lq):
        q = 1 / (1 + math.exp(-lq))
        p = np.clip(1 - (1 - q) ** ts, 1e-12, 1 - 1e-12)
        return -float(np.sum(ys * np.log(p) + (1 - ys) * np.log1p(-p)))

    r = minimize_scalar(nll, bounds=(-12, 4), method="bounded")
    return 1 / (1 + math.exp(-r.x)), -r.fun


def ll_bands(ts, ys) -> float:
    """Log-likelihood with a free rate per T band (the saturated model)."""
    ll = 0.0
    for b in range(len(T_BANDS)):
        m = np.array([band(int(t)) == b for t in ts])
        n, k = int(m.sum()), int(ys[m].sum())
        if n and 0 < k < n:
            p = k / n
            ll += k * math.log(p) + (n - k) * math.log(1 - p)
    return ll


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--min-trials", type=int, default=300)
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.master}?mode=ro", uri=True)
    group = {i: g for i, g in db.execute("select id, group_id from skill_data")}
    train: dict[int, set[int]] = collections.defaultdict(set)
    for card, sid in db.execute(
        "select support_card_id, hint_value_1 from single_mode_hint_gain where hint_gain_type=0"
    ):
        if sid in group:
            train[card].add(group[sid])
    names = {i: t for i, t in db.execute('select "index", text from text_data where category=75')}

    trials = collections.defaultdict(lambda: ([], [], []))  # (card, group) -> T, y, scenario
    by_user = collections.defaultdict(lambda: ([], []))  # (user, card, group) -> T, y
    by_lb = collections.defaultdict(lambda: ([], []))  # (card, group, limit break) -> T, y
    levels = collections.defaultdict(lambda: [0, 0])  # T band -> [levels, card-runs x T]
    per_card_levels = collections.defaultdict(list)  # card -> (T, levels)
    runs = 0
    for path in glob.glob(f"{args.runs}/*/*.gz"):
        try:
            d = json.load(gzip.open(path))
            ch = d["SingleModeChara"][0]
            scs = d["SupportCardGainInfo"]
        except Exception:
            continue
        if ch.get("turn") != TURNS or len(scs) != 6:
            continue
        races = len(d.get("RaceHistory") or [])
        t = TURNS - races
        runs += 1
        user = path.rsplit("/", 2)[-2]
        lb_of = {
            int(c.get("support_card_id") or 0): c.get("limit_break_count")
            for c in ch.get("support_card_array") or []
        }
        for c in scs:
            cid = c["<SupportCardId>k__BackingField"]
            tips = (c.get("<GainInfo>k__BackingField") or {}).get(
                "<SkillTipsArray>k__BackingField"
            ) or []
            got = {
                h["group_id"]: h.get("level", 1)
                for h in tips
                if isinstance(h, dict) and "group_id" in h
            }
            if not train.get(cid):
                continue
            lv = sum(v for g, v in got.items() if g in train[cid])
            levels[band(t)][0] += lv
            levels[band(t)][1] += t
            per_card_levels[cid].append((t, lv))
            for g in train[cid]:
                ts, ys, sc = trials[(cid, g)]
                ts.append(t)
                ys.append(1 if g in got else 0)
                sc.append(ch.get("scenario_id"))
                ut, uy = by_user[(user, cid, g)]
                ut.append(t)
                uy.append(1 if g in got else 0)
                lt, ly = by_lb[(cid, g, lb_of.get(cid))]
                lt.append(t)
                ly.append(1 if g in got else 0)

    print(f"runs {runs}; card x skill cells {len(trials)}")
    # H1: per card x skill, the per-turn model against the T bands.
    obs = np.zeros(len(T_BANDS))
    pred = np.zeros(len(T_BANDS))
    nb = np.zeros(len(T_BANDS))
    rejects = tested = 0
    flat_better = 0
    qs: dict[tuple, float] = {}
    for key, (ts, ys, _) in trials.items():
        if len(ts) < args.min_trials:
            continue
        ts_a, ys_a = np.array(ts, float), np.array(ys, float)
        if ys_a.sum() < 10:
            continue
        q, ll = fit_q(ts_a, ys_a)
        qs[key] = q
        sat = ll_bands(ts_a, ys_a)
        used = sum(1 for b in range(len(T_BANDS)) if any(band(int(t)) == b for t in ts_a))
        if used >= 3:
            tested += 1
            if 2 * (sat - ll) > chi2.ppf(0.95, used - 1):
                rejects += 1
        # The flat model (no T): one rate for every run.
        p0 = ys_a.mean()
        ll_flat = float(np.sum(ys_a * math.log(p0) + (1 - ys_a) * math.log(1 - p0)))
        flat_better += ll_flat > ll
        for b in range(len(T_BANDS)):
            m = np.array([band(int(t)) == b for t in ts_a])
            obs[b] += ys_a[m].sum()
            pred[b] += float(np.sum(1 - (1 - q) ** ts_a[m]))
            nb[b] += m.sum()
    print(f"\n== H1: per-turn model, {len(qs)} card x skill cells with {args.min_trials}+ trials")
    print(
        f"   {'T band':>9} {'races':>7} {'trials':>8} {'hinted':>8} {'predicted':>9} {'obs/pred':>8}"
    )
    for b, (lo, hi) in enumerate(T_BANDS):
        if nb[b]:
            print(
                f"   {lo:>3}-{hi:<5} {TURNS - hi:>3}-{TURNS - lo:<3} {int(nb[b]):>8} {int(obs[b]):>8} {pred[b]:9.0f} {obs[b] / pred[b]:8.3f}"
            )
    print(
        f"   cells rejecting the per-turn model at p<0.05: {rejects} of {tested}; "
        f"cells where ignoring T fits better: {flat_better} of {len(qs)}"
    )
    vals = sorted(qs.values())
    print(
        f"   per-turn q: median {np.median(vals):.4f}, 10-90% {vals[len(vals) // 10]:.4f}-{vals[9 * len(vals) // 10]:.4f}"
        f"  (at T=50: P = {1 - (1 - np.median(vals)) ** 50:.1%})"
    )

    # H2: one rate per card for all its training skills.
    print("\n== H2: one per-turn rate per card (all its training skills)")
    by_card = collections.defaultdict(list)
    for cid, g in qs:
        by_card[cid].append(g)
    rej = tot = 0
    spread = []
    for cid, gs in by_card.items():
        if len(gs) < 2:
            continue
        lls, all_t, all_y = 0.0, [], []
        for g in gs:
            ts, ys, _ = trials[(cid, g)]
            q, ll = fit_q(np.array(ts, float), np.array(ys, float))
            lls += ll
            all_t += ts
            all_y += ys
        _, ll_shared = fit_q(np.array(all_t, float), np.array(all_y, float))
        tot += 1
        if 2 * (lls - ll_shared) > chi2.ppf(0.95, len(gs) - 1):
            rej += 1
        q_g = [qs[(cid, g)] for g in gs]
        spread.append(max(q_g) / min(q_g))
    print(
        f"   cards: {tot}; shared rate rejected at p<0.05 for {rej}; max/min per-skill q within a card: "
        f"median {np.median(spread):.2f}, 90% {sorted(spread)[9 * len(spread) // 10]:.2f}"
    )

    # H3: hint levels per training turn by T band.
    print("\n== H3: training-hint levels a card adds, per training turn")
    for b, (lo, hi) in enumerate(T_BANDS):
        lv, tt = levels[b]
        if tt:
            print(f"   T {lo:>2}-{hi:<2}: {lv / tt:.4f} levels per card per turn")

    # H1 within a player: each player's own per-turn q per card x skill.
    print(
        "\n== H1 within players (a q per player x card x skill, cells of 30+ runs over 2+ T bands)"
    )
    obs_u = np.zeros(len(T_BANDS))
    pred_u = np.zeros(len(T_BANDS))
    flat_u = np.zeros(len(T_BANDS))
    n_u = np.zeros(len(T_BANDS))
    cells_u = 0
    ll_turn = ll_flat_u = 0.0
    for _key, (ts, ys) in by_user.items():
        if len(ts) < 30 or len({band(t) for t in ts}) < 2 or sum(ys) < 3:
            continue
        ts_a, ys_a = np.array(ts, float), np.array(ys, float)
        q, ll = fit_q(ts_a, ys_a)
        p0 = ys_a.mean()
        ll_turn += ll
        if 0 < p0 < 1:
            ll_flat_u += float(np.sum(ys_a * math.log(p0) + (1 - ys_a) * math.log(1 - p0)))
        cells_u += 1
        for b in range(len(T_BANDS)):
            m = np.array([band(int(t)) == b for t in ts_a])
            obs_u[b] += ys_a[m].sum()
            pred_u[b] += float(np.sum(1 - (1 - q) ** ts_a[m]))
            flat_u[b] += p0 * m.sum()
            n_u[b] += m.sum()
    print(
        f"   cells {cells_u}; log-likelihood per-turn {ll_turn:.1f} vs flat (no T) {ll_flat_u:.1f}"
    )
    for b, (lo, hi) in enumerate(T_BANDS):
        if n_u[b]:
            print(
                f"   T {lo:>2}-{hi:<2}: trials {int(n_u[b]):>7}, hinted {int(obs_u[b]):>6}, per-turn {pred_u[b]:8.0f} "
                f"({obs_u[b] / pred_u[b]:.3f}), flat {flat_u[b]:8.0f} ({obs_u[b] / flat_u[b]:.3f})"
            )

    # The card's limit break: q by LB against the card x skill's own q.
    print("\n== Per-turn q by the card's limit break (against the card x skill's pooled q)")
    ratio = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for (cid, g, lb), (ts, ys) in by_lb.items():
        if (cid, g) not in qs or lb is None or len(ts) < 50:
            continue
        ts_a, ys_a = np.array(ts, float), np.array(ys, float)
        pr = float(np.sum(1 - (1 - qs[(cid, g)]) ** ts_a))
        r = ratio[lb]
        r[0] += ys_a.sum()
        r[1] += pr
        r[2] += len(ts)
    for lb in sorted(ratio):
        o, p_, n = ratio[lb]
        print(f"   LB {lb}: trials {n:>7}, hinted / predicted from the pooled q {o / p_:.3f}")

    # Examples: the most-run cards.
    print("\n== The most-run cards: per-turn q per training skill, and P at T = 40 / 50 / 60")
    top = sorted(by_card, key=lambda c: -len(trials[(c, by_card[c][0])][0]))[:8]
    for cid in top:
        n = len(trials[(cid, by_card[cid][0])][0])
        qv = [qs[(cid, g)] for g in by_card[cid]]
        qm = float(np.mean(qv))
        print(
            f"   {names.get(cid, cid)[:34]:34} runs {n:>5}, {len(qv)} skills: q {min(qv):.4f}-{max(qv):.4f} "
            f"-> {1 - (1 - qm) ** 40:.0%} / {1 - (1 - qm) ** 50:.0%} / {1 - (1 - qm) ** 60:.0%}"
        )


if __name__ == "__main__":
    main()

"""The spark roll, measured: what a white skill she owns needs to spark.

Companion users' spark screens (the site's `spark_screens`: both rolls with
their factors, and the skills she had at the screen) joined to each run's
receipt (her six ancestors with their factors). One trial per white skill
she owned per roll: did its spark come up, with how many of the six carrying
its plain spark (parents and grandparents apart) and how many its "+"
variant (`succession_factor_effect`: a "+" group adds a stat and points at
the same skill). A roll where the skill came up as its "+" (the URA tax)
says nothing about the plain spark: left out and counted.

PREDICTIONS, written 2026-10-08 before the first run (the community's rules,
in our tools and in Rappy's Maximizing Loopa alike):
  P1  a owned white sparks at 20% x 1.1^k (k: the six carrying its plain
      spark), a ◎ at 25%, a gold at 40%. The owner's 456 trials gave 88% of
      that (whites 89%, golds 81%): expect 85-95% here.
  P2  a "+" carrier adds nothing to the plain spark's roll (q = 1).
  P3  a parent and a grandparent carrier count the same.
  P4  roll 2 is independent of roll 1, given what she owns.
  P5  a new white's stars: 1/2/3 at about 42/53/5% (one test box).
  P6  white sparks a roll add up as independent trials (no cap).

    uv run python tools/loop/spark_rolls.py --db prod-copy.sqlite \\
        --runs runs/ --master master.mdb

Prints aggregates only: no player, run or veteran is named.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import sqlite3
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

BASE = {"normal": 0.20, "double": 0.25, "gold": 0.40}
VERSIONS = ("normal", "double", "gold")
BETTER = {"normal": 0, "double": 1, "gold": 2}
SCENARIOS = {1: "URA Finale", 2: "Unity Cup", 3: "Grand Concert"}


@dataclass(frozen=True)
class Master:
    factor: dict  # factor id -> (group, stars, type)
    plain: dict  # skill group -> its plain white factor group
    plus: dict  # skill group -> its "+" factor group
    skill: dict  # skill id -> (rarity, group, group_rate)


def load_master(path: str) -> Master:
    m = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    factor = {
        f: (g, s, t)
        for f, g, s, t in m.execute(
            "select factor_id, factor_group_id, rarity, factor_type from succession_factor"
        )
    }
    effects = collections.defaultdict(list)
    for g, tt, v1 in m.execute(
        "select factor_group_id, target_type, value_1 from succession_factor_effect"
    ):
        effects[g].append((tt, v1))
    skill = {
        i: (r, g, gr)
        for i, r, g, gr in m.execute("select id, rarity, group_id, group_rate from skill_data")
    }
    plain, plus = {}, {}
    for g in {g for g, _, t in factor.values() if t == 4}:
        is_plus = any(1 <= tt <= 6 for tt, _ in effects[g])
        for tt, sid in effects[g]:
            if tt != 41 or sid not in skill:
                continue
            target = plus if is_plus else plain
            prev = target.setdefault(skill[sid][1], g)
            assert prev == g, (
                f"skill group {skill[sid][1]} has two {'plus' if is_plus else 'plain'} sparks"
            )
    return Master(factor, plain, plus, skill)


def factor_ids(o: dict) -> list[int]:
    return [
        f["<FactorId>k__BackingField"]
        for f in (o.get("<FactorDataArray>k__BackingField") or [])
        if f
    ]


def ancestors(doc: dict) -> list[tuple[str, list[int]]] | None:
    """The six: two parents, each with her two parents (positions 10, 20)."""
    out = []
    for p in doc.get("Parents") or []:
        out.append(("parent", factor_ids(p)))
        lst = p.get("<SuccessionCharaList>k__BackingField") or {}
        for g in (lst.get("_items") or [])[: lst.get("_size") or 0]:
            if g and g.get("_positionId") in (10, 20):
                out.append(("grandparent", factor_ids(g)))
    if [w for w, _ in out].count("parent") != 2 or len(out) != 6:
        return None
    return out


@dataclass
class Trial:
    version: str
    k_par: int
    k_gp: int
    plus_par: int
    plus_gp: int
    has_plus: bool  # the skill has a "+" variant at all
    stars: int  # the plain carriers' stars, summed
    roll: int  # 1, or 2 after a reroll
    scenario: int
    y: int

    @property
    def k(self) -> int:
        return self.k_par + self.k_gp

    @property
    def plus(self) -> int:
        return self.plus_par + self.plus_gp


def owned(rec: dict, ms: Master) -> dict[int, str]:
    """Skill group -> the best version she owns of it (white, ◎, gold), for
    the groups that have a plain white spark."""
    out: dict[int, str] = {}
    for sid, _level in rec.get("skills") or []:
        row = ms.skill.get(sid)
        if row is None or row[0] > 2 or row[1] not in ms.plain:
            continue
        v = "gold" if row[0] == 2 else "double" if row[2] == 2 else "normal"
        cur = out.get(row[1])
        if cur is None or BETTER[v] > BETTER[cur]:
            out[row[1]] = v
    return out


def white_groups(fids: list[int], ms: Master) -> dict[int, int]:
    """Factor group -> stars, white sparks only."""
    out = {}
    for f in fids:
        g, s, t = ms.factor.get(f, (None, 0, 0))
        if t == 4:
            out[g] = s
    return out


def load(db: str, runs: str, ms: Master):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    trials: list[Trial] = []
    new_stars = collections.Counter()
    per_roll = []  # (roll, scenario, white sparks seen, trial indices)
    pairs = []  # (trial index roll 1, trial index roll 2)
    stats = collections.Counter()
    players = set()
    scores = {
        (u, f): (lo, hi)
        for u, f, lo, hi in c.execute(
            "select user_id, filename, score_floor, score_ceiling from runs"
        )
    }
    grades = {
        (u, f): (lo, hi)
        for u, f, lo, hi in c.execute(
            "select user_id, filename, rank_floor, rank_ceiling from runs"
        )
    }
    for uid, run_file, raw in c.execute("select user_id, run_file, record from spark_screens"):
        stats["screens"] += 1
        rec = json.loads(raw)
        if not run_file:
            stats["no run file"] += 1
            continue
        try:
            doc = json.load(gzip.open(f"{runs}/{uid}/{run_file}.gz"))
        except (FileNotFoundError, OSError, ValueError):
            stats["no receipt"] += 1
            continue
        anc = ancestors(doc)
        if anc is None:
            stats["no full lineage"] += 1
            continue
        rolls = sorted(rec.get("rolls") or [], key=lambda r: r.get("lottery_id", 0))
        if not rolls:
            stats["no roll"] += 1
            continue
        stats["used"] += 1
        players.add(uid)
        anc_groups = [(who, white_groups(f, ms)) for who, f in anc]
        mine = owned(rec, ms)
        scen = rec.get("scenario_id") or 0
        lo, hi = scores.get((uid, run_file), (None, None))
        band = score_band(lo)
        grade = grade_band(*grades.get((uid, run_file), (None, None)))
        index_of: dict[tuple[int, int], int] = {}
        mine_plain = {ms.plain[sg] for sg in mine}
        mine_any = mine_plain | {ms.plus[sg] for sg in mine if sg in ms.plus}
        for ri, roll in enumerate(rolls[:2], 1):
            got = white_groups(roll.get("factors") or [], ms)
            idx = []
            for sg, v in mine.items():
                g, pg = ms.plain[sg], ms.plus.get(sg)
                if pg is not None and pg in got:
                    stats["came up as its +"] += 1
                    continue
                kp = sum(1 for who, gs in anc_groups if who == "parent" and g in gs)
                kg = sum(1 for who, gs in anc_groups if who == "grandparent" and g in gs)
                pp = sum(1 for who, gs in anc_groups if who == "parent" and pg in gs) if pg else 0
                pgp = (
                    sum(1 for who, gs in anc_groups if who == "grandparent" and pg in gs)
                    if pg
                    else 0
                )
                st = sum(gs[g] for _, gs in anc_groups if g in gs)
                trials.append(
                    Trial(v, kp, kg, pp, pgp, pg is not None, st, ri, scen, int(g in got))
                )
                idx.append(len(trials) - 1)
                index_of[(ri, sg)] = len(trials) - 1
                if g in got:
                    new_stars[(v, got[g])] += 1
                    new_stars[("band", band, got[g])] += 1
                    new_stars[("grade", grade, got[g])] += 1
            # Whites that came up without being owned: none expected.
            stats["whites not owned"] += sum(1 for g in got if g not in mine_any)
            per_roll.append((ri, scen, sum(1 for g in got if g in mine_plain), idx))
        if len(rolls) >= 2:
            stats["rerolled"] += 1
            for sg in mine:
                if (1, sg) in index_of and (2, sg) in index_of:
                    pairs.append((index_of[(1, sg)], index_of[(2, sg)]))
    stats["players"] = len(players)
    return trials, new_stars, per_roll, pairs, stats


# ── fitting (cells: identical covariates share one probability) ─────────


def cells(trials, key):
    agg = collections.defaultdict(lambda: [0, 0])
    for t in trials:
        a = agg[key(t)]
        a[0] += 1
        a[1] += t.y
    return agg


def fit(trials, terms: list[str], free_base=True):
    """P = c_version x prod(ratio_term ^ count_term), maximum likelihood.
    `terms`: Trial attributes counted (k_par, k_gp, ...). Returns
    (params dict, log-likelihood)."""
    agg = cells(trials, lambda t: (t.version, *(getattr(t, a) for a in terms)))
    keys = list(agg)
    n = np.array([agg[k][0] for k in keys], float)
    y = np.array([agg[k][1] for k in keys], float)
    vi = np.array([VERSIONS.index(k[0]) for k in keys])
    X = np.array([k[1:] for k in keys], float).reshape(len(keys), len(terms))

    def unpack(th):
        lc = th[:3] if free_base else np.log([BASE[v] for v in VERSIONS]) + th[0]
        lr = th[3:] if free_base else th[1:]
        return lc, lr

    def nll(th):
        lc, lr = unpack(th)
        lp = np.minimum(lc[vi] + X @ lr, math.log(0.999))
        p = np.exp(lp)
        return -float(np.sum(y * lp + (n - y) * np.log1p(-p)))

    th0 = np.concatenate(
        [
            np.log([BASE[v] for v in VERSIONS]) if free_base else [0.0],
            np.full(len(terms), math.log(1.1)),
        ]
    )
    r = minimize(
        nll,
        th0,
        method="Nelder-Mead",
        options={"xatol": 1e-7, "fatol": 1e-7, "maxiter": 20000, "maxfev": 40000},
    )
    r = minimize(nll, r.x, method="BFGS")
    lc, lr = unpack(r.x)
    params = (
        {f"c_{v}": math.exp(lc[i]) for i, v in enumerate(VERSIONS)}
        if free_base
        else {"scale": math.exp(r.x[0])}
    )
    params.update({f"r_{a}": math.exp(lr[i]) for i, a in enumerate(terms)})
    return params, -r.fun, (nll, r.x, unpack)


def profile_ci(trials, terms, which: int, free_base=True, grid=None):
    """95% profile-likelihood interval for the ratio of terms[which]."""
    best, ll, (nll, x, _) = fit(trials, terms, free_base)
    off = 3 if free_base else 1
    lo_hi = []
    for direction in (-1, 1):
        step, val = 0.002, x[off + which]
        while True:
            val += direction * step

            def fixed(th, val=val):
                full = np.insert(th, off + which, val)
                return nll(full)

            rest = np.delete(x, off + which)
            r = minimize(fixed, rest, method="BFGS")
            if 2 * (r.fun - (-ll)) > 3.841 or abs(val - x[off + which]) > 1.0:
                lo_hi.append(math.exp(val))
                break
    return lo_hi


BANDS = (
    (0, "under 8,000"),
    (8000, "8,000-8,999"),
    (9000, "9,000-9,499"),
    (9500, "9,500-9,999"),
    (10000, "10,000-10,499"),
    (10500, "10,500-10,999"),
    (11000, "11,000-11,999"),
    (12000, "12,000+"),
)


def score_band(score) -> str:
    """The run's score before the skill shop (the receipt's), in bands."""
    if score is None:
        return "unknown"
    return [name for lo, name in BANDS if score >= lo][-1]


# The game's grade ladder (uma-it-web lookups.LETTER_GRADE_BY_RANK): 11 B,
# 13 A, 15 S, 17 SS, 19 UG, then U-tier bands of 10 (29 UF, 39 UE, ...).
GRADES = (
    (None, "below B"),
    (11, "B to A+"),
    (15, "S, S+"),
    (17, "SS, SS+"),
    (19, "UG to UF9"),
    (39, "UE and up"),
)


def grade_band(lo, hi) -> str:
    """The final grade's band when the run's floor and ceiling agree on it
    (the skills she buys decide where between them she ends), else
    "between"."""
    if lo is None or hi is None:
        return "unknown"

    def band(r):
        return [name for start, name in GRADES if start is None or r >= start][-1]

    return band(lo) if band(lo) == band(hi) else f"between {band(lo)} and {band(hi)}"


def wilson(y, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = y / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--master", required=True)
    args = ap.parse_args()
    ms = load_master(args.master)
    trials, new_stars, per_roll, pairs, stats = load(args.db, args.runs, ms)
    print("data:", dict(stats))
    print(
        f"trials: {len(trials)} ({sum(t.roll == 1 for t in trials)} in roll 1), "
        f"sparked {sum(t.y for t in trials)}"
    )
    r1 = [t for t in trials if t.roll == 1]

    print(
        "\n== P1: roll 1 by version and carriers "
        "(k = parents + grandparents carrying the plain spark)"
    )
    print(
        f"   {'version':7} {'k':>2} {'trials':>7} {'sparked':>7} {'rate':>6} {'95% CI':>13} "
        f"{'nominal':>7} {'obs/nom':>7}"
    )
    for v in VERSIONS:
        for k in range(7):
            sub = [t for t in r1 if t.version == v and t.k_par + t.k_gp == k]
            if len(sub) < 30:
                continue
            y = sum(t.y for t in sub)
            nom = BASE[v] * 1.1**k
            lo, hi = wilson(y, len(sub))
            print(
                f"   {v:7} {k:>2} {len(sub):>7} {y:>7} {y / len(sub):6.1%} {lo:6.1%}-{hi:5.1%} "
                f"{nom:7.1%} {y / len(sub) / nom:7.2f}"
            )
    for v in VERSIONS:
        sub = [t for t in r1 if t.version == v]
        if sub:
            e = sum(BASE[v] * 1.1 ** (t.k_par + t.k_gp) for t in sub)
            o = sum(t.y for t in sub)
            print(f"   {v}: observed {o} / nominal {e:.0f} = {o / e:.3f}")
    for s in sorted({t.scenario for t in r1}):
        sub = [t for t in r1 if t.scenario == s]
        e = sum(BASE[t.version] * 1.1 ** (t.k_par + t.k_gp) for t in sub)
        o = sum(t.y for t in sub)
        print(
            f"   {SCENARIOS.get(s, s)}: {len(sub)} trials, "
            f"observed {o} / nominal {e:.0f} = {o / e:.3f}"
        )

    print("\n== Fits on roll 1 (maximum likelihood; P = c_version x ratio^count)")
    pk, ll_k, _ = fit(r1, ["k"])
    ci = profile_ci(r1, ["k"], 0)
    print(f"   one ratio per carrier: {fmt(pk)}  r 95% CI {ci[0]:.3f}-{ci[1]:.3f}  LL {ll_k:.1f}")
    pn, ll_n, _ = fit(r1, ["k"], free_base=False)
    print(f"   nominal bases x a common scale: {fmt(pn)}  LL {ll_n:.1f}")

    print("\n== P3: parents and grandparents apart")
    pd, ll_d, _ = fit(r1, ["k_par", "k_gp"])
    ci_p = profile_ci(r1, ["k_par", "k_gp"], 0)
    ci_g = profile_ci(r1, ["k_par", "k_gp"], 1)
    print(
        f"   {fmt(pd)}  parent CI {ci_p[0]:.3f}-{ci_p[1]:.3f}, "
        f"grandparent CI {ci_g[0]:.3f}-{ci_g[1]:.3f}  LL {ll_d:.1f} (vs {ll_k:.1f})"
    )

    print('\n== P2: "+" carriers, on the skills that have a "+" variant (roll 1)')
    fam = [t for t in r1 if t.has_plus]
    print(f'   trials {len(fam)}, with a "+" carrier {sum(1 for t in fam if t.plus)}')
    print(f"   {'k plain':>7} {'k +':>3} {'trials':>7} {'sparked':>7} {'rate':>6} {'95% CI':>13}")
    for k in range(7):
        for j in range(7):
            sub = [t for t in fam if t.k == k and t.plus == j]
            if len(sub) < 25:
                continue
            y = sum(t.y for t in sub)
            lo, hi = wilson(y, len(sub))
            print(f"   {k:>7} {j:>3} {len(sub):>7} {y:>7} {y / len(sub):6.1%} {lo:6.1%}-{hi:5.1%}")
    pq, ll_q, _ = fit(fam, ["k", "plus"])
    ci_q = profile_ci(fam, ["k", "plus"], 1)
    print(
        f'   fit on these: {fmt(pq)}  "+" ratio 95% CI {ci_q[0]:.3f}-{ci_q[1]:.3f}  '
        "(P2 says 1.0; a full carrier would be ~1.1)"
    )
    pq_all, _, _ = fit(r1, ["k", "plus"])
    ci_q_all = profile_ci(r1, ["k", "plus"], 1)
    print(
        f"   fit on all roll-1 trials: {fmt(pq_all)}  "
        f'"+" ratio 95% CI {ci_q_all[0]:.3f}-{ci_q_all[1]:.3f}'
    )

    print(
        "\n== Carriers' stars: does a 3-star carrier count more than a 1-star? "
        "(roll 1, one carrier exactly)"
    )
    for v in ("normal", "gold"):
        for s in (1, 2, 3):
            sub = [t for t in r1 if t.version == v and t.k == 1 and t.stars == s]
            if len(sub) >= 30:
                y = sum(t.y for t in sub)
                lo, hi = wilson(y, len(sub))
                print(
                    f"   {v:6} one carrier at {s}★: {len(sub):>6} trials "
                    f"{y / len(sub):6.1%} ({lo:5.1%}-{hi:5.1%})"
                )

    print("\n== P4: roll 2 against roll 1 (rerolled screens, the same skill in both rolls)")
    obs11 = exp11 = 0.0
    by_cell = collections.defaultdict(list)
    for a, b in pairs:
        ta, tb = trials[a], trials[b]
        by_cell[(ta.version, ta.k)].append((ta.y, tb.y))
    for ys in by_cell.values():
        n = len(ys)
        p = sum(y1 + y2 for y1, y2 in ys) / (2 * n)
        obs11 += sum(1 for y1, y2 in ys if y1 and y2)
        exp11 += n * p * p
    tot = len(pairs)
    y1s = [trials[a].y for a, _ in pairs]
    y2s = [trials[b].y for _, b in pairs]
    after_yes = [y2 for y1, y2 in zip(y1s, y2s, strict=True) if y1]
    after_no = [y2 for y1, y2 in zip(y1s, y2s, strict=True) if not y1]
    print(f"   pairs {tot}: roll 1 rate {sum(y1s) / tot:.1%}, roll 2 rate {sum(y2s) / tot:.1%}")
    print(
        f"   roll 2 after a spark in roll 1: {sum(after_yes) / max(1, len(after_yes)):.1%} "
        f"of {len(after_yes)}; after none: {sum(after_no) / max(1, len(after_no)):.1%} "
        f"of {len(after_no)}"
    )
    print(
        f"   sparked in both: {obs11:.0f} observed, {exp11:.0f} expected "
        "if independent within cells (version x carriers)"
    )

    print("\n== P5: a new white's stars (both rolls)")
    for v in VERSIONS:
        n = sum(new_stars[(v, s)] for s in (1, 2, 3))
        if n:
            print(
                f"   {v:6}: "
                + "  ".join(f"{s}★ {new_stars[(v, s)] / n:5.1%}" for s in (1, 2, 3))
                + f"  (n={n})"
            )
    print("   by the run's final grade (floor and ceiling in one band):")
    names = sorted(
        {k[1] for k in new_stars if k[0] == "grade"}, key=lambda x: (x.startswith("between"), x)
    )
    for name in names:
        n = sum(new_stars[("grade", name, s)] for s in (1, 2, 3))
        if n >= 50:
            print(
                f"   {name:34}: "
                + "  ".join(f"{s}★ {new_stars[('grade', name, s)] / n:5.1%}" for s in (1, 2, 3))
                + f"  (n={n})"
            )
    print("   by the run's score before the skill shop:")
    for _, name in (*BANDS, (None, "unknown")):
        n = sum(new_stars[("band", name, s)] for s in (1, 2, 3))
        if n >= 50:
            print(
                f"   {name:14}: "
                + "  ".join(f"{s}★ {new_stars[('band', name, s)] / n:5.1%}" for s in (1, 2, 3))
                + f"  (n={n})"
            )

    print("\n== P6: white sparks a roll against independent trials (each roll's own expectation)")
    rate = {}
    for v in VERSIONS:
        for k in range(7):
            sub = [t for t in r1 if t.version == v and t.k == k]
            rate[(v, k)] = (sum(t.y for t in sub) + 1) / (len(sub) + 2)
    res, within, high = [], [], []
    for ri, _scen, seen, idx in per_roll:
        if ri != 1 or not idx:
            continue
        ps = [rate[(trials[i].version, trials[i].k)] for i in idx]
        e = sum(ps)
        res.append(seen - e)
        within.append(sum(p * (1 - p) for p in ps))
        if e >= 10:
            high.append((seen, e))
    n_rolls = len(res)
    mean_r = sum(res) / n_rolls
    var_r = sum((r - mean_r) ** 2 for r in res) / n_rolls
    print(
        f"   rolls {n_rolls}: observed minus expected, mean {mean_r:+.2f}; "
        f"its variance {var_r:.2f} "
        f"vs {sum(within) / n_rolls:.2f} for independent trials (a cap would make it smaller)"
    )
    if high:
        print(
            f"   rolls expecting 10+: {len(high)}, "
            f"observed {sum(s for s, _ in high) / len(high):.2f} "
            f"vs expected {sum(e for _, e in high) / len(high):.2f} a roll"
        )


def fmt(p: dict) -> str:
    return ", ".join(f"{k} {v:.3f}" for k, v in p.items())


if __name__ == "__main__":
    main()

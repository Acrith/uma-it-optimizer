"""Three open tests of the hint side (uma-it-web docs/loop-pairs.md, "Data
tests still open"), on site receipts. Run once, predictions written first.

T1  The two inspiration events (Classic and Senior, SuccessionFactorGainInfo
    years 2 and 3). PREDICTION: independent (a factor that fired in one event
    fires in the other as often as its own rate says), and no cap on how many
    factors one ancestor fires in an event (the count follows the sum of
    independent trials: same variance, no cut upper tail).
    Trials as in inspiration_rates.py: a factor id carried by exactly one of
    the six ancestors is that ancestor's. Cells: type x stars x position x
    affinity band; the rates are the cell's own, so the model's error can't
    pass for a dependence.
T2  URA Finale's own event hints of Racing Spirit Stamina and Power.
    PREDICTION: independent, P(both) = P(Stamina) x P(Power), on runs where
    neither the trainee nor a deck card can hint either (as
    scenario_hints.py restricts; the Events bucket, GainInfo[0]). All Racing
    Spirit pairs reported beside it.
T3  Parent 2 of the same character as one of parent 1's grandparents (or the
    other way round): does that grandparent's trio relation (trainee, its
    child, it) still count? PREDICTION: it counts, as the model has it now.
    Fired vs predicted for that grandparent's and its child's factors, with
    the trio counted (model) and at zero (as for in-breeding).

    python hint_tests.py --master master.mdb --receipts runs/
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
from pathlib import Path

from affinity import Affinity
from loopdata import Uma

TYPES = {1: "blue", 2: "pink", 3: "green", 4: "white", 5: "race", 6: "scenario"}
BASE = {
    "blue": (0.70, 0.80, 0.90),
    "pink": (0.01, 0.03, 0.05),
    "green": (0.05, 0.10, 0.15),
    "white": (0.03, 0.06, 0.09),
    "race": (0.01, 0.02, 0.03),
    "scenario": (0.03, 0.06, 0.09),
}
WEB = Path(__file__).parent / "../../../uma-it-web/uma_it_web/enrich/data"


class _Master:
    def __init__(self, path: str):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _factors(x: dict) -> list[int]:
    return [
        f["<FactorId>k__BackingField"]
        for f in x.get("<FactorDataArray>k__BackingField") or []
        if isinstance(f, dict) and "<FactorId>k__BackingField" in f
    ]


def _wins(x: dict) -> list[int]:
    return [w for w in x.get("_winSaddleIdArray") or [] if isinstance(w, int)]


def _load(path: str) -> dict:
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def wilson(y: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = y / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--receipts", required=True)
    args = ap.parse_args()
    master = _Master(args.master)
    db = master.db
    kind = {
        fid: (TYPES.get(t), r)
        for fid, t, r in db.execute("select factor_id, factor_type, rarity from succession_factor")
    }
    aff = Affinity(master)
    group = dict(db.execute("select id, group_id from skill_data"))
    rs_groups = {}
    for sid, text in db.execute(
        "select s.id, t.text from skill_data s join text_data t on t.category = 47"
        " and t.\"index\" = s.id where t.text like 'Racing Spirit:%' and s.rarity = 1"
    ):
        rs_groups.setdefault(text.replace("Racing Spirit: ", ""), group[sid])
    cards = {
        int(k): {group.get(s) for s in v}
        for k, v in json.loads((WEB / "card_event_skills.json").read_text())["cards"].items()
    }
    trainee_skills = {}
    for k, t in json.loads((WEB / "trainee_events.json").read_text())["trainees"].items():
        ids = set(t["event_skills"]) | {s for e in t["events"] for s, _ in e["skills"]}
        trainee_skills[int(k)] = {group.get(s) for s in ids}

    # T1 accumulators
    cell = collections.defaultdict(lambda: [0, 0, 0, 0])  # n, fired y2, fired y3, both
    anc_events = []  # (cell keys of its factors, fired counts per year)
    # T2
    ura = []  # (hinted groups, groups others could hint)
    # T3: role -> [trials, fired, p_model, p_zero]
    t3 = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    t3_runs = 0
    seen = set()
    stats = collections.Counter()
    for path in glob.glob(f"{args.receipts}/*/*.json*"):
        try:
            d = _load(path)
            smc = d["SingleModeChara"][0]
            gain = {
                y["<Year>k__BackingField"]: {
                    g["<FactorId>k__BackingField"]
                    for g in y["<GainFactorInfoArray>k__BackingField"]
                }
                for y in d["SuccessionFactorGainInfo"]
            }
            parents = d["Parents"]
        except (KeyError, IndexError, TypeError, ValueError):
            stats["unreadable"] += 1
            continue
        key = (smc.get("start_time"), smc.get("card_id"), smc.get("succession_trained_chara_id_1"))
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        # T2 needs only the Events bucket.
        if smc.get("scenario_id") == 1:
            try:
                events = d["GainInfo"][0]
                deck = [sc["<SupportCardId>k__BackingField"] for sc in d["SupportCardGainInfo"]]
                hinted = {
                    h["group_id"]
                    for h in events.get("<SkillTipsArray>k__BackingField") or []
                    if isinstance(h, dict) and "group_id" in h
                }
                others = trainee_skills.get(smc["card_id"], set()).union(
                    *(cards.get(c, set()) for c in deck)
                )
                ura.append((hinted, others))
            except (KeyError, IndexError, TypeError):
                pass
        if len(parents) != 2 or 2 not in gain or 3 not in gain:
            continue
        facts: dict[int, list[int]] = {}
        umas = []
        for p in parents:
            lst = p.get("<SuccessionCharaList>k__BackingField") or {}
            gps = [
                g
                for g in (lst.get("_items") or [])[: lst.get("_size") or 0]
                if isinstance(g, dict) and g.get("_positionId") in (10, 20)
            ]
            gu = [Uma(g["<CardId>k__BackingField"], {}, _wins(g)) for g in gps]
            u = Uma(p["_cardId"], {}, _wins(p), gu)
            umas.append(u)
            facts[id(u)] = _factors(p)
            for g, x in zip(gu, gps, strict=True):
                facts[id(g)] = _factors(x)
        r = aff.evaluate(smc["card_id"], *umas)
        if not r or len(r["members"]) != 6:
            continue
        stats["runs"] += 1
        carriers = collections.Counter(f for fs in facts.values() for f in fs)
        members = r["members"]
        # T1
        for i, (m, a, _) in enumerate(members):
            pos = "parent" if i < 2 else "grandparent"
            keys, fired = [], {2: 0, 3: 0}
            for f in facts[id(m)]:
                if carriers[f] != 1:
                    continue
                t, stars = kind.get(f, (None, 0))
                if t not in BASE:
                    continue
                ck = (t, stars, pos, min(int(a // 25), 16))
                c = cell[ck]
                y2, y3 = f in gain[2], f in gain[3]
                c[0] += 1
                c[1] += y2
                c[2] += y3
                c[3] += y2 and y3
                keys.append(ck)
                fired[2] += y2
                fired[3] += y3
            if keys:
                anc_events.append((keys, fired))
        # T3: a grandparent of the other parent's character.
        t = smc["card_id"] // 100
        p1, p2 = umas
        repeated = [
            (p, g)
            for p, other in ((p1, p2), (p2, p1))
            for g in p.parents
            if g.chara == other.chara and g.chara != t
        ]
        if repeated:
            t3_runs += 1
            lost = collections.Counter()
            for p, g in repeated:
                trio = aff.trio(t, p.chara, g.chara)
                lost[id(g)] += trio
                lost[id(p)] += trio
            roles = {}
            for p, g in repeated:
                roles[id(g)] = "repeated grandparent"
                roles[id(p)] = "its child (a parent)"
                for g2 in p.parents:
                    roles.setdefault(id(g2), "the other grandparent")
            for p in (p1, p2):
                roles.setdefault(id(p), "the other parent")
                for g2 in p.parents:
                    roles.setdefault(id(g2), "the other side's grandparents")
            for m, a, _ in members:
                role = roles[id(m)]
                for f in facts[id(m)]:
                    if carriers[f] != 1:
                        continue
                    tt, stars = kind.get(f, (None, 0))
                    if tt not in BASE:
                        continue
                    base = BASE[tt][stars - 1]
                    for y in (2, 3):
                        for label in (role, f"{role} · {tt == 'white' and 'whites' or 'others'}"):
                            row = t3[label]
                            row[0] += 1
                            row[1] += f in gain[y]
                            row[2] += min(1.0, base * (1 + a / 100))
                            row[3] += min(1.0, base * (1 + (a - lost[id(m)]) / 100))
    print("data:", dict(stats))

    # ── T1 ──────────────────────────────────────────────────────────────
    print(
        "\n== T1a: both events, a factor that fired in one against its rate (cells: type x stars x position x affinity band)"
    )
    tot = collections.defaultdict(
        lambda: [0, 0.0, 0, 0, 0]
    )  # type -> n, expected both, both, y2, y3
    for (t, _stars, _pos, _band), (n, y2, y3, both) in cell.items():
        q2, q3 = y2 / n, y3 / n
        row = tot[t]
        row[0] += n
        row[1] += n * q2 * q3
        row[2] += both
        row[3] += y2
        row[4] += y3
        row = tot["all"]
        row[0] += n
        row[1] += n * q2 * q3
        row[2] += both
        row[3] += y2
        row[4] += y3
    for t, (n, exp, both, y2, y3) in sorted(tot.items()):
        print(
            f"   {t:8} trials {n:>8}  fired Classic {y2 / n:6.2%} Senior {y3 / n:6.2%}  "
            f"both: {both:>7} observed, {exp:9.1f} if independent ({both / exp if exp else float('nan'):.3f})"
        )
    # Conditional view on whites: P(fired Senior | fired Classic) vs P(Senior | not).
    wn = [0, 0, 0, 0]  # fired y2 & y3, fired y2, not y2 & y3, not y2
    for (t, *_), (n, y2, y3, both) in cell.items():
        if t == "white":
            wn[0] += both
            wn[1] += y2
            wn[2] += y3 - both
            wn[3] += n - y2
    print(
        f"   whites: Senior after a Classic fire {wn[0] / wn[1]:.2%} (n={wn[1]}); after none {wn[2] / wn[3]:.2%} (n={wn[3]}) "
        "(mixing cells: a small gap is expected even if independent)"
    )

    print(
        "\n== T1b: factors one ancestor fires in one event, against independent trials (its cells' rates)"
    )
    rate = {ck: ((y2 + y3) / (2 * n)) for ck, (n, y2, y3, _) in cell.items()}
    res, var_e = [], []
    by_exp = collections.defaultdict(lambda: [0, 0.0, 0.0])
    tail_obs = collections.Counter()
    tail_exp = collections.Counter()
    for keys, fired in anc_events:
        ps = [rate[k] for k in keys]
        mu = sum(ps)
        v = sum(p * (1 - p) for p in ps)
        # Poisson-binomial distribution of this ancestor's count.
        dist = [1.0]
        for p in ps:
            nd = [0.0] * (len(dist) + 1)
            for i, q in enumerate(dist):
                nd[i] += q * (1 - p)
                nd[i + 1] += q * p
            dist = nd
        for y in (2, 3):
            k = fired[y]
            res.append(k - mu)
            var_e.append(v)
            b = min(int(mu), 6)
            by_exp[b][0] += 1
            by_exp[b][1] += k
            by_exp[b][2] += mu
            for m in range(1, 9):
                tail_obs[m] += k >= m
                tail_exp[m] += sum(dist[m:])
    n = len(res)
    mean_r = sum(res) / n
    var_r = sum((x - mean_r) ** 2 for x in res) / n
    print(
        f"   ancestor-events {n}: observed minus expected mean {mean_r:+.3f}; variance {var_r:.3f} "
        f"vs {sum(var_e) / n:.3f} for independent trials (a cap would make it smaller)"
    )
    print(
        "   P(an ancestor fires m or more in one event): "
        + "  ".join(
            f"{m}+: {tail_obs[m] / n:.4f} vs {tail_exp[m] / n:.4f}"
            for m in range(1, 9)
            if tail_exp[m] / n > 1e-5
        )
    )
    print(
        "   by expected count: "
        + "  ".join(
            f"[{b}-{b + 1}) n={c[0]} obs {c[1] / c[0]:.2f} exp {c[2] / c[0]:.2f}"
            for b, c in sorted(by_exp.items())
        )
    )

    # ── T2 ──────────────────────────────────────────────────────────────
    print(f"\n== T2: URA Finale's own event hints of the Racing Spirits ({len(ura)} URA runs)")
    names = sorted(rs_groups)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            ga, gb = rs_groups[a], rs_groups[b]
            el = [(ga in h, gb in h) for h, o in ura if ga not in o and gb not in o]
            if len(el) < 50:
                continue
            n = len(el)
            pa = sum(x for x, _ in el) / n
            pb = sum(y for _, y in el) / n
            both = sum(1 for x, y in el if x and y)
            exp = n * pa * pb
            lo, hi = wilson(both, n)
            mark = "  <- the test" if {a, b} == {"Stamina", "Power"} else ""
            print(
                f"   {a:7} + {b:7}: runs {n:>5}  P({a}) {pa:6.1%}  P({b}) {pb:6.1%}  both {both:>5} "
                f"vs {exp:7.1f} independent ({both / exp if exp else float('nan'):.3f}; both {both / n:.1%}, "
                f"95% {lo:.1%}-{hi:.1%} vs {pa * pb:.1%}){mark}"
            )

    # How many Racing Spirits one URA run's events hint, on runs where no
    # trainee or card could hint any of them, against independent hints.
    groups = [rs_groups[x] for x in names]
    el = [h for h, o in ura if not (set(groups) & o)]
    if el:
        n = len(el)
        marg = [sum(1 for h in el if g in h) / n for g in groups]
        dist = [1.0]
        for p in marg:
            nd = [0.0] * (len(dist) + 1)
            for i, q in enumerate(dist):
                nd[i] += q * (1 - p)
                nd[i + 1] += q * p
            dist = nd
        obs = collections.Counter(sum(1 for g in groups if g in h) for h in el)
        print(
            f"   Racing Spirits hinted in one run ({n} runs, {len(groups)} skills): "
            + "  ".join(f"{k}: {obs[k] / n:5.1%} vs {dist[k]:5.1%}" for k in range(len(groups) + 1))
        )

    # ── T3 ──────────────────────────────────────────────────────────────
    print(
        f"\n== T3: a grandparent of the other parent's character ({t3_runs} runs); fired vs predicted per event"
    )
    print(f"   {'role':48} {'trials':>8} {'fired':>7} {'trio counted':>12} {'trio zero':>10}")
    for role, (n, fired, pm, pz) in sorted(t3.items()):
        print(f"   {role:48} {n:>8} {fired / n:7.2%} {pm / n:12.2%} {pz / n:10.2%}")


if __name__ == "__main__":
    main()

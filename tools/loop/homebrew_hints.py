"""Homebrew (owner, 2026-10-26: "make homebrew possible. But homebrew that's accurate"): do the
inspiration rules hold when both parents are the player's own? The rates were measured mostly on
borrowed runs (2026-10-08: 11,345). An own pair repeats its ancestors: the same veteran on both
sides (siblings as parents, a mother with her own daughter), a character twice, in-breeding.

Per run and per white skill one or more of the six carry (plain or "+"), per inspiration (years 2,
3): did a factor of that skill fire? Model: 1 - prod over carriers (1 - base(stars) x (1 + aff/100)),
the carriers independent, each at its own affinity (Affinity.evaluate). Against observed, by run
kind (own pair / a borrowed parent), carriers, and structure. For a skill a duplicated veteran
carries, also the model with her counted once (her better-placed copy).

Predictions: ~/workspace/uma-loop-local/homebrew/PREDICTIONS.md (H1), written before the run.

    python homebrew_hints.py --master master.mdb --receipts runs/

Prints aggregates only.

RESULT 2026-10-26 (36,786 Global IT runs to 2026-10-19: 19,119 own pairs, 17,667 with a borrowed parent):
CONFIRMED. Own pairs fire 1.025x the model, borrow runs 1.022x (1.04M and 1.12M trials). A veteran on both sides
fires as two carriers: her skills 36.39% observed against 35.82% modelled with both copies, 28.84% with her once.
In-bred 1.024, a character twice 1.021, no repeat 1.042. By carriers (own): 1: 1.057, 2: 1.025, 3: 1.009, 4+:
1.011, the same on borrow runs (single carriers a little over the model on both). Off, on both kinds alike: runs the
model rates under 150 affinity fire 1.41x (own) / 1.44x (borrow); 1.4% of runs, mostly sprint and dirt characters
(Sakura Bakushin O, Haru Urara, Aston Machan, Curren Chan): open.
"""
# ruff: noqa: E501  (report lines)

from __future__ import annotations

import argparse
import collections
import glob

from affinity import Affinity
from hint_tests import BASE, _factors, _load, _Master, _wins, wilson
from loopdata import Uma


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--limit", type=int, default=0, help="read only this many receipts (a smoke test)")
    args = ap.parse_args()
    master = _Master(args.master)
    db = master.db
    factor = {f: (g, s, t) for f, g, s, t in db.execute("select factor_id, factor_group_id, rarity, factor_type from succession_factor")}
    # A white factor group (plain or "+") -> the skill group it hints.
    skill_group = dict(db.execute("select id, group_id from skill_data"))
    hints_skill = {}
    for g, tt, v1 in db.execute("select factor_group_id, target_type, value_1 from succession_factor_effect"):
        if tt == 41 and v1 in skill_group:
            hints_skill.setdefault(g, skill_group[v1])
    aff = Affinity(master)

    # bucket -> [trials, fired, expected, variance, expected counting a duplicated veteran once]
    rows: dict[tuple, list[float]] = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    seen = set()
    stats = collections.Counter()
    files = sorted(glob.glob(f"{args.receipts}/*/*.json*"))
    if args.limit:
        files = files[: args.limit]
    for path in files:
        try:
            d = _load(path)
            smc = d["SingleModeChara"][0]
            gain = {y["<Year>k__BackingField"]: {g["<FactorId>k__BackingField"] for g in y["<GainFactorInfoArray>k__BackingField"]}
                    for y in d["SuccessionFactorGainInfo"]}
            parents = d["Parents"]
        except (KeyError, IndexError, TypeError, ValueError, OSError, EOFError):
            stats["unreadable"] += 1
            continue
        key = (smc.get("start_time"), smc.get("card_id"), smc.get("succession_trained_chara_id_1"))
        if key in seen or len(parents) != 2 or 2 not in gain or 3 not in gain:
            stats["duplicate or no inspiration"] += 1
            continue
        seen.add(key)
        kind = "borrow" if any(p.get("_ownerViewerId") for p in parents) else "own"
        umas, facts = [], {}
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
            stats["no full lineage"] += 1
            continue
        stats[f"runs {kind}"] += 1
        members = r["members"]                                   # p1, p2, then the four grandparents
        sig = [(m.card, tuple(sorted(facts[id(m)]))) for m, _, _ in members]
        dup_sig = {s for s in sig if sig.count(s) > 1}
        charas = [m.chara for m, _, _ in members]
        struct = []
        if dup_sig:
            struct.append("same veteran twice")
        if any(charas.count(c) > 1 for c in set(charas)) and not dup_sig:
            struct.append("a character twice (other veterans)")
        if r["inbreed"]:
            struct.append("in-bred")
        if not struct:
            struct.append("no repeat")
        for s in struct:
            stats[f"runs {kind} · {s}"] += 1
        # White skill -> its carriers: (place, stars, affinity, signature)
        carried: dict[int, list] = collections.defaultdict(list)
        for i, (m, a, _) in enumerate(members):
            for f in facts[id(m)]:
                g, stars, ft = factor.get(f, (None, 0, 0))
                if ft != 4 or g not in hints_skill:
                    continue
                carried[hints_skill[g]].append(("parent" if i < 2 else "grandparent", stars, a, sig[i]))
        fired_skills = {y: {hints_skill.get(factor.get(f, (None,))[0]) for f in gain[y]} for y in (2, 3)}
        for sk, cs in carried.items():
            p_rate = [min(1.0, BASE["white"][st - 1] * (1 + a / 100)) for _, st, a, _ in cs]
            miss = 1.0
            for q in p_rate:
                miss *= 1 - q
            p = 1 - miss
            # Counted once: a duplicated veteran's copies collapse to the one with the higher rate.
            best: dict = {}
            for (_, _, _, s), q in zip(cs, p_rate, strict=True):
                best[s] = max(best.get(s, 0.0), q)
            miss1 = 1.0
            for q in best.values():
                miss1 *= 1 - q
            p_once = 1 - miss1
            n = len(cs)
            sigs_here = [c[3] for c in cs]
            dup_here = any(sigs_here.count(s) > 1 for s in sigs_here)
            keys = [(kind, "all"), (kind, f"carriers {min(n, 4)}{'+' if n >= 4 else ''}")]
            keys += [(kind, f"run: {s}") for s in struct]
            if dup_here:
                keys.append((kind, "skill carried by the same veteran twice"))
            band = "aff <150" if r["total"] < 150 else "aff 150-249" if r["total"] < 250 else "aff 250+"
            keys.append((kind, band))
            for y in (2, 3):
                hit = sk in fired_skills[y]
                for k in keys:
                    row = rows[k]
                    row[0] += 1
                    row[1] += hit
                    row[2] += p
                    row[3] += p * (1 - p)
                    row[4] += p_once
    print("receipts:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    print(f"\n{'kind':7s} {'bucket':44s} {'trials':>8s} {'fired':>7s} {'95% CI':>15s} {'model':>7s} {'obs/model':>9s} {'z':>6s} {'once':>7s}")
    for k in sorted(rows, key=lambda k: (k[0], k[1])):
        n, y, e, v, e1 = rows[k]
        lo, hi = wilson(y, n)
        z = (y - e) / v ** 0.5 if v > 0 else 0.0
        print(f"{k[0]:7s} {k[1]:44s} {int(n):8d} {y / n:7.2%} {lo:7.2%}-{hi:6.2%} {e / n:7.2%} {y / e:9.3f} {z:+6.1f} {e1 / n:7.2%}")


if __name__ == "__main__":
    main()

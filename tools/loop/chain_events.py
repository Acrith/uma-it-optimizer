"""A trainer card's chain-event gold against the deck's pals and the run's
training turns.

A trainer card (support_card_type 1) whose events can give a gold
(uma-it-web card_event_skills.json) gives it only when its event chain gets
far enough; the companion's card_hints.json models that by the deck's pal
and group cards (`palLogit`, a logit step per pal count, and an offset per
card: sigmoid(palLogit[pals] + offset)), fitted on 19,273 runs and checked
on a half split. "Races barely matter once pals are held fixed" was written
then, not measured. A run counts for a card's gold when nothing else in it
could give that gold: no other deck card's events list it, the trainee's
events don't, the scenario's own events don't (20%+ of its runs).

PREDICTIONS, written 2026-10-08 before the first run:
  C1  with the pals held fixed, more training turns (T = 78 - races) make the
      chain gold likelier: beta > 0, about +0.1 to +0.4 log-odds per 10 turns.
  C2  the pal steps fitted with a turns term stay within 0.2 of the published
      palLogit (turns don't stand in for pals).
  C3  within players (an offset per player x card x gold), beta keeps its sign.

    uv run python tools/loop/chain_events.py --runs <receipts> --master <master.mdb> \\
        --events <card_event_skills.json> --trainee-events <trainee_events.json> \\
        --scenario-hints <scenario_event_hints.json> --card-hints <card_hints.json>

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
from scipy.optimize import minimize

TURNS = 78
TOP_PALS = 5
T_BANDS = [(0, 47), (48, 55), (56, 78)]


def load(path):
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("runs", "master", "events", "trainee-events", "scenario-hints", "card-hints"):
        ap.add_argument(f"--{a}", required=True)
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.master}?mode=ro", uri=True)
    group = {i: (g, r) for i, g, r in db.execute("select id, group_id, rarity from skill_data")}
    ctype = dict(db.execute("select id, support_card_type from support_card_data"))
    ev_r = {
        int(c): {group[s] for s in v if s in group} for c, v in load(args.events)["cards"].items()
    }
    golds = {c: {g for g, r in v if r == 2} for c, v in ev_r.items()}
    scen = {
        int(s): {int(g) for g, sh in v.get("groups", {}).items() if sh >= 0.2}
        for s, v in load(args.scenario_hints).items()
    }
    tr = {
        int(c): {
            group[s] for e in t.get("events", []) for s, _ in e.get("skills", []) if s in group
        }
        for c, t in load(args.trainee_events)["trainees"].items()
    }
    published = load(args.card_hints)["palLogit"]

    rows = []  # (cell key, user, pals, T, hit)
    for path in glob.glob(f"{args.runs}/*/*.gz"):
        try:
            d = json.load(gzip.open(path))
            ch = d["SingleModeChara"][0]
            scs, gis = d["SupportCardGainInfo"], d["GainInfo"]
        except Exception:
            continue
        if ch.get("turn") != TURNS or len(scs) != 6 or len(gis) != 8:
            continue
        cards = [c["<SupportCardId>k__BackingField"] for c in scs]
        pals = sum(
            1
            for c in ch.get("support_card_array") or []
            if ctype.get(int(c.get("support_card_id") or 0)) in (2, 3)
        )
        t = TURNS - len(d.get("RaceHistory") or [])
        sc = ch.get("scenario_id")
        user = path.rsplit("/", 2)[-2]
        ev_tips = {
            (h["group_id"], h.get("rarity", 1))
            for h in gis[0].get("<SkillTipsArray>k__BackingField") or []
            if isinstance(h, dict)
        }
        trainee_g = {g for g, r in tr.get(int(ch.get("card_id") or 0), ()) if r == 2}
        for i, c in enumerate(cards):
            if ctype.get(c) != 1 or not golds.get(c):
                continue
            own = {
                (h["group_id"], h.get("rarity", 1))
                for h in (scs[i].get("<GainInfo>k__BackingField") or {}).get(
                    "<SkillTipsArray>k__BackingField"
                )
                or []
                if isinstance(h, dict)
            }
            others = (
                set().union(*(golds.get(o, set()) for j, o in enumerate(cards) if j != i))
                | trainee_g
                | scen.get(sc, set())
            )
            for g in golds[c] - others:
                hit = (g, 2) in own or (g, 2) in ev_tips
                rows.append(((c, sc, g), user, min(pals, TOP_PALS), t, int(hit)))
    print(f"card-gold trials {len(rows)}")
    cells = collections.Counter(r[0] for r in rows)
    keep = {k for k, n in cells.items() if n >= 40}
    rows = [r for r in rows if r[0] in keep]
    keys = sorted(keep)
    kidx = {k: i for i, k in enumerate(keys)}
    ci = np.array([kidx[r[0]] for r in rows])
    pal = np.array([r[2] for r in rows])
    tt = (np.array([r[3] for r in rows], float) - 50) / 10
    y = np.array([r[4] for r in rows], float)
    print(
        f"cells (card x scenario x gold, 40+ runs): {len(keys)}; trials {len(rows)}; gold rate {y.mean():.3f}"
    )

    def nll(th, with_t=True):
        steps = np.concatenate([th[:2], [0.0], th[2:5]])  # pals 0..5, 2 pals = 0
        beta = th[5] if with_t else 0.0
        off = th[6:]
        z = steps[pal] + off[ci] + beta * tt
        return float(np.sum(np.logaddexp(0, z) - y * z))

    th0 = np.concatenate([[published[0], published[1]], published[3:6], [0.0], np.zeros(len(keys))])
    r1 = minimize(nll, th0, method="L-BFGS-B")
    r0 = minimize(lambda th: nll(th, False), th0, method="L-BFGS-B")

    # beta's standard error from the curvature along beta (others refit).
    def prof(b):
        return minimize(
            lambda th: nll(np.concatenate([th[:5], [b], th[5:]])),
            np.delete(r1.x, 5),
            method="L-BFGS-B",
        ).fun

    b = r1.x[5]
    h = 0.02
    curv = (prof(b + h) - 2 * r1.fun + prof(b - h)) / h**2
    se = 1 / math.sqrt(curv) if curv > 0 else float("nan")
    steps = np.concatenate([r1.x[:2], [0.0], r1.x[2:5]])
    print(
        "\n== C1/C2: logit P(gold) = palStep[pals] + offset[card x scenario x gold] + beta x (T - 50)/10"
    )
    print(
        f"   beta {b:+.3f} per 10 training turns (SE {se:.3f}); log-likelihood {-r1.fun:.1f} vs {-r0.fun:.1f} without turns"
    )
    print(
        "   pal steps fitted: "
        + " ".join(f"{s:+.2f}" for s in steps)
        + "   published: "
        + " ".join(f"{s:+.2f}" for s in published)
    )
    # Observed vs predicted by pals x T band.
    z = steps[pal] + r1.x[6:][ci] + b * tt
    p = 1 / (1 + np.exp(-z))
    print(f"   {'pals':>4} {'T band':>8} {'runs':>6} {'gold':>6} {'predicted':>9}")
    traw = np.array([r[3] for r in rows])
    for k in range(TOP_PALS + 1):
        for lo, hi in T_BANDS:
            m = (pal == k) & (traw >= lo) & (traw <= hi)
            if m.sum() >= 40:
                print(
                    f"   {k:>4} {lo:>3}-{hi:<4} {int(m.sum()):>6} {y[m].mean():6.1%} {p[m].mean():9.1%}"
                )

    # C3: within players.
    ucell = collections.Counter((r[1], r[0]) for r in rows)
    ukeep = {
        k
        for k, n in ucell.items()
        if n >= 15 and len({rr[3] for rr in rows if (rr[1], rr[0]) == k}) > 1
    }
    sub = [r for r in rows if (r[1], r[0]) in ukeep]
    if sub:
        uk = sorted({(r[1], r[0]) for r in sub})
        uidx = {k: i for i, k in enumerate(uk)}
        ui = np.array([uidx[(r[1], r[0])] for r in sub])
        pal2 = np.array([r[2] for r in sub])
        t2 = (np.array([r[3] for r in sub], float) - 50) / 10
        y2 = np.array([r[4] for r in sub], float)

        def nll2(th):
            steps2 = np.concatenate([th[:2], [0.0], th[2:5]])
            z2 = steps2[pal2] + th[6:][ui] + th[5] * t2
            return float(np.sum(np.logaddexp(0, z2) - y2 * z2))

        r2 = minimize(
            nll2,
            np.concatenate([steps[:2], steps[3:], [0.0], np.zeros(len(uk))]),
            method="L-BFGS-B",
        )
        print(
            f"\n== C3 within players ({len(uk)} player x card x gold cells, {len(sub)} trials): beta {r2.x[5]:+.3f} per 10 turns"
        )


if __name__ == "__main__":
    main()

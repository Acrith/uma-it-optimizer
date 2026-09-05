"""Per-card EVENT contributions by joint regression over the corpus.

Every run's events bucket, after subtracting exact race rewards
(RaceHistory + reference tables, RB-scaled), decomposes as

    resid = scenario_const + trainee_delta + sum(card event payouts)
            + races * slope_scen + noise

Cards enter as presence dummies (event payouts are story-fixed per
card, level-independent); pals are just cards here - their own events
ride their dummy, and the pal training multiplier never touches the
events channel. Event-bugged runs excluded; twins kept (events roll
fresh). Ridge-regularized least squares.

Usage: python card_events_fit.py --runs <dir> [--min-card-n 25]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

from it_formula import Masters
from predict_deck import EVENT_BUG_CHARAS, EVENT_BUG_SCENS, EVENT_BUG_WINDOW
from trainee_events import SP_FIELD, STAT_FIELDS, grade_map, race_rewards

MDB = Path(__file__).parent / "../../references/master.mdb"


def deck_rb(conn, cards: dict[int, int], cache: dict) -> float:
    """Total race bonus of the deck (effect table type 15 + uniques).
    cards: {card_id: level}."""
    BP = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    total = 0.0
    for cid, lv in cards.items():
        key = (cid, lv)
        if key not in cache:
            v = 0.0
            row = conn.execute("select * from support_card_effect_table "
                               "where id=? and type=15", (cid,)).fetchone()
            if row:
                pts = [(a, x) for a, x in zip(BP, row[2:13]) if x != -1]
                if pts and lv >= pts[0][0]:
                    v = float(pts[-1][1])
                    for (x0, v0), (x1, v1) in zip(pts, pts[1:]):
                        if lv <= x1:
                            v = v0 + (v1 - v0) * (lv - x0) / (x1 - x0)
                            break
            for gate, t0, v0, t1, v1 in conn.execute(
                    "select lv, type_0, value_0, type_1, value_1 "
                    "from support_card_unique_effect where id=?", (cid,)):
                if lv >= gate:
                    for t, x in ((t0, v0), (t1, v1)):
                        if t == 15:
                            v += x
            cache[key] = v
        total += cache[key]
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--min-card-n", type=int, default=25)
    ap.add_argument("--min-trainee-n", type=int, default=10)
    ap.add_argument("--ridge", type=float, default=30.0)
    args = ap.parse_args()

    conn = sqlite3.connect(str(MDB))
    masters = Masters(MDB)
    grades = grade_map(MDB)
    rb_cache: dict = {}

    rows = []
    for p in sorted(args.runs.glob("*/*.json")):
        parts = p.stem.split("_")
        if len(parts) < 3 or not parts[2].startswith("uma"):
            continue
        trainee = int(parts[2][3:])
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        chara = (raw.get("SingleModeChara") or [{}])[0]
        scen = int(chara.get("scenario_id") or 0)
        if scen not in (1, 2, 3, 4):
            continue
        if (trainee // 100 in EVENT_BUG_CHARAS and scen in EVENT_BUG_SCENS
                and EVENT_BUG_WINDOW[0] <= parts[0] <= EVENT_BUG_WINDOW[1]):
            continue
        deck = {int(c.get("support_card_id") or 0):
                (int(c.get("exp") or 0), int(c.get("limit_break_count") or 0))
                for c in chara.get("support_card_array") or []}
        if not deck:
            continue
        gi = raw.get("GainInfo") or []
        ev = gi[0] if gi else {}
        races = len(raw.get("RaceHistory") or [])
        if not races:
            continue
        levels = {cid: (masters.level_from_exp(cid, e, lb) or 1)
                  for cid, (e, lb) in deck.items()}
        rb = deck_rb(conn, levels, rb_cache)
        r_sp, r_st = race_rewards(raw, scen, trainee, grades, rb=rb)
        rows.append({
            "scen": scen, "trainee": trainee, "races": races,
            "cards": frozenset(deck),
            "y_sp": ev.get(SP_FIELD, 0) - r_sp,
            "y_st": sum(ev.get(f, 0) for f in STAT_FIELDS) - r_st,
        })

    card_n = Counter(c for r in rows for c in r["cards"])
    tr_n = Counter((r["trainee"]) for r in rows)
    cards = sorted(c for c, n in card_n.items() if n >= args.min_card_n)
    trainees = sorted(t for t, n in tr_n.items() if n >= args.min_trainee_n)
    ci = {c: i for i, c in enumerate(cards)}
    ti = {t: i for i, t in enumerate(trainees)}
    nc, nt = len(cards), len(trainees)
    ns = 4
    ncol = ns + nt + nc + ns          # scen consts, trainee, card, races/scen
    X = np.zeros((len(rows), ncol))
    y_sp = np.zeros(len(rows))
    y_st = np.zeros(len(rows))
    for i, r in enumerate(rows):
        X[i, r["scen"] - 1] = 1.0
        if r["trainee"] in ti:
            X[i, ns + ti[r["trainee"]]] = 1.0
        for c in r["cards"]:
            if c in ci:
                X[i, ns + nt + ci[c]] = 1.0
        X[i, ns + nt + nc + r["scen"] - 1] = r["races"]
        y_sp[i] = r["y_sp"]
        y_st[i] = r["y_st"]

    lam = args.ridge
    # don't shrink scenario constants
    P = np.eye(ncol) * lam
    for j in range(ns):
        P[j, j] = 0.0
    A = X.T @ X + P
    beta_sp = np.linalg.solve(A, X.T @ y_sp)
    beta_st = np.linalg.solve(A, X.T @ y_st)
    pred = X @ beta_sp
    res = y_sp - pred
    print(f"{len(rows)} runs, {nc} cards, {nt} trainees; "
          f"SP fit residual: median |r| {np.median(np.abs(res)):.0f}, "
          f"p90 {np.percentile(np.abs(res), 90):.0f}")
    print("\nscenario constants (SP / stat) + races slope:")
    for s in range(4):
        print(f"  scen {s+1}: {beta_sp[s]:7.0f} / {beta_st[s]:7.0f}"
              f"   slope {beta_sp[ns+nt+nc+s]:5.1f} / {beta_st[ns+nt+nc+s]:5.1f} per race")
    out = {"cards": {str(c): {"n": card_n[c],
                              "ev_sp": round(float(beta_sp[ns+nt+ci[c]]), 1),
                              "ev_st": round(float(beta_st[ns+nt+ci[c]]), 1)}
                     for c in cards},
           "trainees": {str(t): {"n": tr_n[t],
                                 "ev_sp": round(float(beta_sp[ns+ti[t]]), 1),
                                 "ev_st": round(float(beta_st[ns+ti[t]]), 1)}
                        for t in trainees}}
    outp = Path(__file__).parent / "card_events_fit.json"
    outp.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {outp}")
    print("\ntop 20 cards by fitted event SP:")
    top = sorted(cards, key=lambda c: -beta_sp[ns+nt+ci[c]])[:20]
    for c in top:
        print(f"  {c:>6} n={card_n[c]:>5}  ev_sp {beta_sp[ns+nt+ci[c]]:6.0f}"
              f"  ev_st {beta_st[ns+nt+ci[c]]:6.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

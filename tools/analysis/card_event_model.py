"""Structured card-event model: enumeration x completion rates.

Per run, expected card-event SP is built from KNOWN payouts
(event_enum.json, top-option success totals) instead of free dummies:

  resid = scen_const + trainee_delta
        + sum over MARKED cards   chain_pt(c) * rate_measured(c, scen)
        + [sum over unmarked chain_pt(c)]            * chain_rate(scen)
        + [sum over unmarked chain_pt(c) * friends]  * chain_rate_f
        + [sum over all      rnd_pt(c)]              * rnd_rate(scen)
        + races * slope(scen) + noise

Only the small rate surface is fitted (marked-card rates come straight
from their gold markers), so meta co-occurrence cannot poison
per-card attribution - payout SIZES are data, not parameters.
The same machinery runs for the stat side.

Usage: python card_event_model.py --runs <dir>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from it_formula import Masters
from predict_deck import EVENT_BUG_CHARAS, EVENT_BUG_SCENS, EVENT_BUG_WINDOW
from card_events_fit import deck_rb
from trainee_events import SP_FIELD, STAT_FIELDS, grade_map, race_rewards

MDB = Path(__file__).parent / "../../references/master.mdb"
ENUM = json.loads((Path(__file__).parent / "event_enum.json").read_text())
FRIEND_TYPES = {2, 3}   # support_card_type: pal, group


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--marker-min-n", type=int, default=30)
    ap.add_argument("--min-trainee-n", type=int, default=10)
    args = ap.parse_args()

    conn = sqlite3.connect(str(MDB))
    masters = Masters(MDB)
    grades = grade_map(MDB)
    sc_type = {r[0]: r[1] for r in conn.execute(
        "select id, support_card_type from support_card_data")}
    rb_cache: dict = {}

    runs = []
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
                for c in chara.get("support_card_array") or {}}
        races = len(raw.get("RaceHistory") or [])
        if not deck or not races:
            continue
        golds = {t["group_id"] for t in chara.get("skill_tips_array") or []
                 if t.get("rarity") == 2 and t.get("group_id")}
        gi = raw.get("GainInfo") or []
        ev = gi[0] if gi else {}
        levels = {cid: (masters.level_from_exp(cid, e, lb) or 1)
                  for cid, (e, lb) in deck.items()}
        rb = deck_rb(conn, levels, rb_cache)
        r_sp, r_st = race_rewards(raw, scen, trainee, grades, rb=rb)
        runs.append({
            "scen": scen, "trainee": trainee, "races": races,
            "cards": frozenset(deck), "golds": golds,
            "friends": sum(1 for c in deck if sc_type.get(c, 1) in FRIEND_TYPES),
            "y_sp": ev.get(SP_FIELD, 0) - r_sp,
            "y_st": sum(ev.get(f, 0) for f in STAT_FIELDS) - r_st,
        })

    # ── marker rates per (card, scen), rediscovered from this corpus ──
    n_runs = len(runs)
    with_c = Counter(c for r in runs for c in r["cards"])
    hit = Counter()
    group_total = Counter()
    for r in runs:
        for g in r["golds"]:
            group_total[g] += 1
    # candidate marker = the gold group of the card's chain-final skill
    chain_marker = {}
    m = json.loads((Path("/home/r_krawczak/workspace/uma-it-web/uma_it_web/enrich/data/masters.json")).read_text())
    skill_group = {int(sid): int(s.get("group_id") or 0) for sid, s in m["skills"].items()}
    for cid_s, e in ENUM.items():
        sk = [s for s, lv in e["chain"]["skills"] if s]
        if sk:
            g = skill_group.get(int(sk[-1]))
            if g:
                chain_marker[int(cid_s)] = g
    rate_measured: dict = {}
    for cid, g in chain_marker.items():
        n = with_c.get(cid, 0)
        if n < args.marker_min_n:
            continue
        h = sum(1 for r in runs if cid in r["cards"] and g in r["golds"])
        bg = sum(1 for r in runs if cid not in r["cards"] and g in r["golds"])
        bgn = n_runs - n
        if bgn and bg / bgn > 0.005:
            continue          # not exclusive -> not a usable marker
        per = defaultdict(lambda: [0, 0])
        for r in runs:
            if cid in r["cards"]:
                per[r["scen"]][1] += 1
                per[r["scen"]][0] += g in r["golds"]
        rate_measured[cid] = {s: a / b for s, (a, b) in per.items() if b >= 15}
    print(f"{n_runs} runs; measured marker rates for {len(rate_measured)} cards")

    # ── design ────────────────────────────────────────────────────────
    tr_n = Counter(r["trainee"] for r in runs)
    trainees = sorted(t for t, n in tr_n.items() if n >= args.min_trainee_n)
    ti = {t: i for i, t in enumerate(trainees)}
    ns, nt = 4, len(trainees)
    # cols: scen consts | trainee | unmarked-chain x scen | chainxfriends |
    #       rnd x scen | races x scen
    ncol = ns + nt + ns + 1 + ns + ns
    X = np.zeros((n_runs, ncol))
    y_sp = np.zeros(n_runs)
    y_st = np.zeros(n_runs)
    known_sp = np.zeros(n_runs)
    known_st = np.zeros(n_runs)
    for i, r in enumerate(runs):
        s = r["scen"] - 1
        X[i, s] = 1.0
        if r["trainee"] in ti:
            X[i, ns + ti[r["trainee"]]] = 1.0
        un_pt = un_st = rnd_pt = rnd_st = 0.0
        for c in r["cards"]:
            e = ENUM.get(str(c))
            if not e:
                continue
            rnd_pt += e["random"]["pt"]
            rnd_st += e["random"]["stats"]
            rates = rate_measured.get(c)
            if rates and r["scen"] in rates:
                known_sp[i] += e["chain"]["pt"] * rates[r["scen"]]
                known_st[i] += e["chain"]["stats"] * rates[r["scen"]]
            else:
                un_pt += e["chain"]["pt"]
                un_st += e["chain"]["stats"]
        X[i, ns + nt + s] = un_pt
        X[i, ns + nt + ns] = un_pt * r["friends"]
        X[i, ns + nt + ns + 1 + s] = rnd_pt
        X[i, ns + nt + ns + 1 + ns + s] = r["races"]
        y_sp[i] = r["y_sp"] - known_sp[i]
        y_st[i] = r["y_st"] - known_st[i]

    lam = 1.0
    P = np.eye(ncol) * lam
    for j in range(ns):
        P[j, j] = 0.0
    A = X.T @ X + P
    b_sp = np.linalg.solve(A, X.T @ y_sp)
    res = y_sp - X @ b_sp
    print(f"SP residual: median |r| {np.median(np.abs(res)):.0f}, "
          f"p90 {np.percentile(np.abs(res), 90):.0f}")
    scen_names = ["URA", "Unity", "GL", "TB"]
    print("\nscenario consts:", [f"{scen_names[s]} {b_sp[s]:.0f}" for s in range(4)])
    print("unmarked chain completion rate by scen:",
          [f"{scen_names[s]} {b_sp[ns+nt+s]:.2f}" for s in range(4)])
    print(f"chain rate friend term: {b_sp[ns+nt+ns]:+.3f} per friend card")
    print("random-event rate (x enumerated top-option totals) by scen:",
          [f"{scen_names[s]} {b_sp[ns+nt+ns+1+s]:.2f}" for s in range(4)])
    print("races slope:", [f"{scen_names[s]} {b_sp[ns+nt+ns+1+ns+s]:+.1f}" for s in range(4)])
    # measured marker rates for comparison
    agg = defaultdict(list)
    for cid, rates in rate_measured.items():
        for s, v in rates.items():
            agg[s].append(v)
    print("measured marker-card rates (mean) by scen:",
          {scen_names[s-1]: f"{np.mean(v):.2f} (n={len(v)})" for s, v in sorted(agg.items())})
    b_st = np.linalg.solve(A, X.T @ y_st)
    res_st = y_st - X @ b_st
    print(f"\nSTAT residual: median |r| {np.median(np.abs(res_st)):.0f}, "
          f"p90 {np.percentile(np.abs(res_st), 90):.0f}")
    print("scenario consts (stat):", [f"{scen_names[s]} {b_st[s]:.0f}" for s in range(4)])
    print("unmarked chain rate (stat channel):",
          [f"{scen_names[s]} {b_st[ns+nt+s]:.2f}" for s in range(4)])
    print(f"friend term (stat): {b_st[ns+nt+ns]:+.3f}")
    print("random rate (stat):",
          [f"{scen_names[s]} {b_st[ns+nt+ns+1+s]:.2f}" for s in range(4)])
    print("races slope (stat):", [f"{scen_names[s]} {b_st[ns+nt+ns+1+ns+s]:+.1f}" for s in range(4)])

    # ── frozen model: enumeration x (measured | scenario-mean) rates ──
    scen_mean = {s: float(np.mean(v)) for s, v in agg.items()}
    exp_sp = np.zeros(n_runs)
    exp_st = np.zeros(n_runs)
    for i, r in enumerate(runs):
        for c in r["cards"]:
            e = ENUM.get(str(c))
            if not e:
                continue
            rates = rate_measured.get(c)
            rt = (rates.get(r["scen"]) if rates and r["scen"] in rates
                  else scen_mean.get(r["scen"], 0.12))
            exp_sp[i] += e["chain"]["pt"] * rt + e["random"]["pt"]
            exp_st[i] += e["chain"]["stats"] * rt + e["random"]["stats"]
    print("\nFROZEN model - per-run expected card-event totals:")
    print(f"  SP:   median {np.median(exp_sp):.0f}  p10-p90 "
          f"{np.percentile(exp_sp, 10):.0f}..{np.percentile(exp_sp, 90):.0f}")
    print(f"  stat: median {np.median(exp_st):.0f}  p10-p90 "
          f"{np.percentile(exp_st, 10):.0f}..{np.percentile(exp_st, 90):.0f}")
    for label, y, exp in (("SP", y_sp + known_sp, exp_sp),
                          ("stat", y_st + known_st, exp_st)):
        A2 = X[:, list(range(ns + nt)) + list(range(ncol - ns, ncol))]
        for name, target in (("without card term", y),
                             ("with frozen card term", y - exp)):
            P2 = np.eye(A2.shape[1]) * 1.0
            for j in range(ns):
                P2[j, j] = 0
            b2 = np.linalg.solve(A2.T @ A2 + P2, A2.T @ target)
            r2 = target - A2 @ b2
            print(f"  {label:>4} {name}: median |resid| {np.median(np.abs(r2)):.0f}, "
                  f"p90 {np.percentile(np.abs(r2), 90):.0f}")

    out = {"marker_rates": {str(c): {str(s): round(v, 3) for s, v in r.items()}
                            for c, r in rate_measured.items()}}
    (Path(__file__).parent / "chain_rates_measured.json").write_text(json.dumps(out, indent=0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

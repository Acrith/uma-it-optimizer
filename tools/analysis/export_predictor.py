"""Bake the forward model into one JSON artifact for the website.

Everything predict_deck.py needs, precomputed so the site needs neither
master.mdb nor the run corpus at request time:

    constants: u per scenario, URA C(races) params, C for GL/TB,
               T(races) table, SP k per scenario
    cards:     per "cardid:level": axis, per-scenario dx[5] (E tables,
               scenario-keyed with pooled fallback), W, run count

Regenerate after a fresh pull and copy over
uma-it-web/uma_it_web/data/predictor_tables.json.

Usage:
    python export_predictor.py --mdb master.mdb --runs <dir> \
        --out predictor_tables.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from it_formula import Masters, axis_of
from offset_sweep import (
    T_POINTS,
    URA_C_BASE,
    URA_C_HALFWIDTH,
    URA_C_SLOPE,
    U,
)
from predict_deck import SP_K, collect_runs, fit_tables


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    masters = Masters(args.mdb)
    import sqlite3
    conn = sqlite3.connect(str(args.mdb))
    chara = {r[0]: r[1] for r in conn.execute(
        "select id, chara_id from support_card_data")}
    BP = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

    def race_bonus(cid: int, lv: int) -> float:
        row = conn.execute(
            "select * from support_card_effect_table where id=? and type=15",
            (cid,)).fetchone()
        if not row:
            return 0.0
        pts = [(a, v) for a, v in zip(BP, row[2:13], strict=False) if v != -1]
        if not pts or lv < pts[0][0]:
            return 0.0
        for (x0, v0), (x1, v1) in zip(pts, pts[1:], strict=False):
            if lv <= x1:
                return v0 + (v1 - v0) * (lv - x0) / (x1 - x0)
        return float(pts[-1][1])
    runs = collect_runs(args.runs, masters)
    (dx, dx_scen), w = fit_tables(runs)

    counts: dict = {}
    for r in runs:
        for k in r["cards"]:
            counts[k] = counts.get(k, 0) + 1

    cmd = {r[0]: r[1] for r in sqlite3.connect(str(args.mdb)).execute(
        "select id, command_id from support_card_data")}
    cards: dict = {}
    for (cid, lvl), n in sorted(counts.items()):
        if (cid, lvl, 0) not in dx:
            continue
        fb, mo, te, _ini, _c = masters.bonuses(cid, lvl)
        entry = {
            "axis": axis_of(fb, mo, te),
            "chara": chara.get(cid, cid),
            "cmd": cmd.get(cid) or 0,
            "n": n,
            "dx": [round(dx.get((cid, lvl, i), 0.0), 1) for i in range(5)],
            "dx_scen": {},
        }
        for scen in (1, 3, 4):
            if (cid, lvl, 0, scen) in dx_scen:
                entry["dx_scen"][str(scen)] = [
                    round(dx_scen.get((cid, lvl, i, scen),
                                      dx.get((cid, lvl, i), 0.0)), 1)
                    for i in range(5)]
        wt = w.get((cid, lvl))
        entry["w"] = round(wt, 2) if wt else None
        entry["rb"] = round(race_bonus(cid, lvl), 1)
        hv = [r["hints"].get((cid, lvl)) for r in runs
              if (cid, lvl) in r["hints"]]
        entry["hints"] = round(sum(hv) / len(hv), 1) if hv else None
        cards[f"{cid}:{lvl}"] = entry

    # Facility priors: mean covered dx/W per (command, scenario) - the
    # cold fallback so uncovered cards still get a credible specialty
    # estimate rather than a base-only row.
    pr_dx: dict = defaultdict(list)
    pr_w: dict = defaultdict(list)
    for e in cards.values():
        for scen, dxs in e["dx_scen"].items():
            pr_dx[(e["cmd"], scen)].append(dxs)
        if e["w"]:
            pr_w[e["cmd"]].append(e["w"])
    priors: dict = {}
    for (cmd_id, scen), rows in pr_dx.items():
        priors.setdefault(str(cmd_id), {})[scen] = [
            round(sum(r[i] for r in rows) / len(rows), 1) for i in range(5)]
    priors_w = {str(cmd_id): round(sum(v) / len(v), 2)
                for cmd_id, v in pr_w.items()}

    # Cold cells: every trainer card at every LB cap level, axis only.
    # Pals (support_card_type 2) and group cards (type 3) are included
    # with a kind flag: pals get the pal law applied deck-wide by the
    # UI, group cards carry the rough measured +2500 X group offset.
    LB_CAP = {0: 30, 1: 35, 2: 40, 3: 45, 4: 50}
    rarity = {r[0]: r[1] for r in sqlite3.connect(str(args.mdb)).execute(
        "select id, rarity from support_card_data")}
    sc_type = {r[0]: r[1] for r in conn.execute(
        "select id, support_card_type from support_card_data")}
    all_cards = sorted(sc_type)
    cold: dict = {}
    for cid in all_cards:
        if cid == 30078:
            continue
        r = rarity.get(cid, 3)
        if r == 1:
            caps = [20, 25, 30, 35, 40]
        elif r == 2:
            caps = [25, 30, 35, 40, 45]
        else:
            caps = list(LB_CAP.values())
        for lvl in caps:
            key = f"{cid}:{lvl}"
            if key in cards:
                continue
            fb, mo, te, _ini, _c = masters.bonuses(cid, lvl)
            entry_c = {"axis": axis_of(fb, mo, te),
                       "chara": chara.get(cid, cid),
                       "cmd": cmd.get(cid) or 0,
                       "rb": round(race_bonus(cid, lvl), 1)}
            k2 = sc_type.get(cid, 1)
            if k2 == 2:
                entry_c["kind"] = "pal"
            elif k2 == 3:
                entry_c["kind"] = "group"
            cold[key] = entry_c

    # Events + inspiration model per scenario (see it-formula.md
    # 2026-08-14): stat MASS is a near-constant per scenario with a
    # random split; events SP = a + b * races * (1 + deck race bonus).
    from statistics import median as med
    events = {}
    insp = {}
    for scen in (1, 3, 4):
        sub = [r for r in runs if r["scen"] == scen and any(r["ev"])]
        if len(sub) < 10:
            continue
        tots = sorted(sum(r["ev"][:5]) for r in sub)
        shape = [med([r["ev"][i] / max(1, sum(r["ev"][:5])) for r in sub])
                 for i in range(5)]
        sh = sum(shape)
        xs = [r["races"] * (1 + sum(race_bonus(c, lv) for c, lv in r["cards"])
                            / 100) for r in sub]
        ys = [r["ev"][5] for r in sub]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
        b_ = cov / sum((x - mx) ** 2 for x in xs)
        a_ = my - b_ * mx
        # Race-vs-events decomposition (2026-08-15): per-race base
        # rewards from the reference tables (normal career for URA/GL,
        # the user's canonical MANT table for TB) averaged over the
        # corpus race mix, and the events RESIDUAL after subtracting
        # exact per-run race rewards. URA's residual includes its
        # finale (3 all-stats+SP races absent from RaceHistory).
        # Measured via the reconstruction snippet in it-formula.md;
        # re-derive when the corpus shifts materially.
        RACE_EVENTS = {
            1: {"race_sp": 43.3, "race_st": 9.7, "ev_sp": 183, "ev_st": 1282},
            3: {"race_sp": 42.5, "race_st": 9.6, "ev_sp": 562, "ev_st": 1732},
            4: {"race_sp": 31.2, "race_st": 9.8, "ev_sp": 518, "ev_st": 1362},
        }
        re_ = RACE_EVENTS[scen]
        events[str(scen)] = {
            "stat_total": re_["ev_st"],
            "spread": [tots[len(tots) // 10], tots[int(len(tots) * .9)]],
            "shape": [round(v / sh, 3) for v in shape],
            "ev_sp": re_["ev_sp"],
            "race_sp": re_["race_sp"], "race_st": re_["race_st"],
            "sp_a": round(a_, 0), "sp_b": round(b_, 2),
        }
        itots = sorted(sum(r["insp"]) for r in sub)
        ishape = [med([r["insp"][i] / max(1, sum(r["insp"])) for r in sub])
                  for i in range(5)]
        ish = sum(ishape) or 1
        insp[str(scen)] = {"stat_total": round(med(itots), 0),
                           "shape": [round(v / ish, 3) for v in ishape]}

    out = {
        "meta": {"runs": len(runs), "cells": len(cards),
                 "model": "it-formula 2026-08-13 post-recalibration"},
        "constants": {
            "u": {str(k): v for k, v in U.items()},
            "ura_c": [URA_C_BASE, URA_C_SLOPE, URA_C_HALFWIDTH],
            "c": {"3": 1825.0, "4": 3400.0},
            "t": {str(k): v for k, v in T_POINTS.items()},
            "sp_k": {str(k): v for k, v in SP_K.items()},
        },
        "cards": cards,
        "cold": cold,
        "priors": {"dx": priors, "w": priors_w},
        "events": events,
        "insp": insp,
    }
    args.out.write_text(json.dumps(out, separators=(",", ":")),
                        encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB, "
          f"{len(cards)} covered + {len(cold)} cold cells, {len(runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

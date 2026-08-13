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
    chara = {r[0]: r[1] for r in sqlite3.connect(str(args.mdb)).execute(
        "select id, chara_id from support_card_data")}
    runs = collect_runs(args.runs, masters)
    (dx, dx_scen), w = fit_tables(runs)

    counts: dict = {}
    for r in runs:
        for k in r["cards"]:
            counts[k] = counts.get(k, 0) + 1

    cards: dict = {}
    for (cid, lvl), n in sorted(counts.items()):
        if (cid, lvl, 0) not in dx:
            continue
        fb, mo, te, _ini, _c = masters.bonuses(cid, lvl)
        entry = {
            "axis": axis_of(fb, mo, te),
            "chara": chara.get(cid, cid),
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
        cards[f"{cid}:{lvl}"] = entry

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
    }
    args.out.write_text(json.dumps(out, separators=(",", ":")),
                        encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB, "
          f"{len(cards)} cells from {len(runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

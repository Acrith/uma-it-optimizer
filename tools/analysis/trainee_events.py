"""Per-trainee event tables from Q15 bare-bones census runs.

A bare run (all-academy-R deck, no own-scenario pal) collapses the
card-event channel to ~nothing, so its Events bucket reads:

    events = trainee events + scenario events + race rewards

Optional races are subtracted EXACTLY via RaceHistory + the reference
grade x position tables (references/umamusume_base_race_rewards.md);
scripted payouts (debut, goal races, finale) stay in the residual on
purpose - they are part of what a per-trainee table should carry.
Trackblazer uses the canonical MANT table on every row instead (no
goal schedule exists there). Twins are KEPT: events roll fresh per
run even in byte-identical card-row twins (dedup policy 2026-08-15).

Usage: python trainee_events.py --runs <dir> [--min-n 2]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

from it_formula import PAL_BY_SCENARIO, Masters
from predict_deck import EVENT_BUG_CHARAS, EVENT_BUG_SCENS, EVENT_BUG_WINDOW

# career.py is a pure module (json + pathlib) but its package __init__
# pulls in Flask - load the file directly instead.
import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location(
    "career", Path(__file__).parent
    / "../../../uma-it-web/uma_it_web/enrich/career.py")
career = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(career)

STAT_FIELDS = ["<Speed>k__BackingField", "<Stamina>k__BackingField",
               "<Power>k__BackingField", "<Guts>k__BackingField",
               "<Wiz>k__BackingField"]
SP_FIELD = "<SkillPoint>k__BackingField"

# grade x position (1..6+), base values before x(1+RB/100)
SP_TABLE = {"G1": [45, 45, 45, 35, 35, 25], "G2": [35, 35, 35, 30, 30, 20],
            "G3": [35, 35, 35, 30, 30, 20], "OP": [30, 30, 30, 20, 20, 10]}
ST_TABLE = {"G1": [10, 8, 6, 5, 5, 4], "G2": [8, 6, 5, 4, 4, 3],
            "G3": [8, 6, 5, 4, 4, 3], "OP": [5, 4, 3, 2, 2, 0]}
# MANT (Trackblazer), canonical per-win values (losses are rare in IT
# and use the same row - fitted Aug 2026 showed no separable loss tier)
MANT_SP = {"Debut": 15, "OP": 20, "G3": 25, "G2": 25, "G1": 35}
MANT_ST = {"Debut": 9, "OP": 5, "G3": 8, "G2": 8, "G1": 10}
GRADE_KEY = {100: "G1", 200: "G2", 300: "G3", 400: "OP", 700: "OP", 800: "OP"}

PAL_IDS = {c for v in PAL_BY_SCENARIO.values() for c in v}


def grade_map(mdb: Path) -> dict[int, int]:
    c = sqlite3.connect(str(mdb))
    return {pid: g for pid, g in c.execute(
        "select p.id, r.grade from single_mode_program p "
        "join race_instance ri on ri.id = p.race_instance_id "
        "join race r on r.id = ri.race_id")}


def goal_turns(trainee_card_id: int) -> set[int]:
    out = set()
    for o in career.objectives_for(str(trainee_card_id)):
        if career.race_by_name(o.get("ObjectiveName") or ""):
            try:
                out.add(int(o.get("Turn") or 0))
            except (TypeError, ValueError):
                pass
    return out


def race_rewards(raw: dict, scen: int, trainee: int, grades: dict,
                 rb: float = 0.0) -> tuple[float, float]:
    """(sp, stat_total) the generic tables predict for this run's
    OPTIONAL races (TB: all races via MANT), scaled x(1+rb/100).
    Bare academy decks carry rb=0."""
    sp = st = 0.0
    scale = 1.0 + rb / 100.0
    goals = goal_turns(trainee) if scen != 4 else set()
    for rc in raw.get("RaceHistory") or []:
        turn = int(rc.get("turn") or 0)
        g = grades.get(int(rc.get("program_id") or 0))
        pos = min(max(int(rc.get("result_rank") or 1), 1), 6) - 1
        if scen == 4:
            key = "Debut" if g == 900 else GRADE_KEY.get(g)
            if key:
                sp += int(MANT_SP[key] * scale)
                st += int(MANT_ST[key] * scale)
            continue
        if turn > 72 or turn in goals or g == 900:
            continue                      # scripted: finale / goal / debut
        key = GRADE_KEY.get(g)
        if key:
            sp += int(SP_TABLE[key][pos] * scale)
            st += int(ST_TABLE[key][pos] * scale)
    return sp, st


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--mdb", type=Path,
                    default=Path(__file__).parent / "../../references/master.mdb")
    ap.add_argument("--min-n", type=int, default=2)
    ap.add_argument("--json-out", type=Path, default=None,
                    help="also write per-cell medians as JSON")
    args = ap.parse_args()

    masters = Masters(args.mdb)
    grades = grade_map(args.mdb)
    cells: dict = defaultdict(list)

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
        deck = {int(c.get("support_card_id") or 0)
                for c in chara.get("support_card_array") or []}
        if deck & PAL_BY_SCENARIO.get(scen, set()):
            continue
        if not deck or not all(c < 20000 for c in deck - PAL_IDS):
            continue
        races = len(raw.get("RaceHistory") or [])
        if not races or (races > 21 if scen == 2 else races > 40):
            continue
        if (trainee // 100 in EVENT_BUG_CHARAS and scen in EVENT_BUG_SCENS
                and EVENT_BUG_WINDOW[0] <= parts[0] <= EVENT_BUG_WINDOW[1]):
            continue
        gi = raw.get("GainInfo") or []
        ev = gi[0] if gi else {}
        ev_sp = ev.get(SP_FIELD, 0)
        ev_st = [ev.get(f, 0) for f in STAT_FIELDS]
        r_sp, r_st = race_rewards(raw, scen, trainee, grades)
        cells[(trainee, scen)].append({
            "races": races,
            "sp_resid": ev_sp - r_sp,
            "st_resid": sum(ev_st) - r_st,
            "st": ev_st,
        })

    scen_name = {1: "URA", 2: "Unity", 3: "GL", 4: "TB"}
    print(f"{'trainee':>8} {'scen':>5} {'n':>3} {'races':>7} "
          f"{'SP resid (p25..p75)':>22} {'stat resid':>11}  shape spd/sta/pow/gut/wiz")
    per_scen: dict = defaultdict(list)
    for (trainee, scen), rows in sorted(cells.items(), key=lambda kv: (kv[0][1], -len(kv[1]))):
        if len(rows) < args.min_n:
            continue
        sps = sorted(r["sp_resid"] for r in rows)
        sts = sorted(r["st_resid"] for r in rows)
        n = len(rows)
        shape = [median(r["st"][i] for r in rows) for i in range(5)]
        tot = sum(shape) or 1
        races_span = f"{min(r['races'] for r in rows)}-{max(r['races'] for r in rows)}"
        print(f"{trainee:>8} {scen_name[scen]:>5} {n:>3} {races_span:>7} "
              f"{median(sps):>8.0f} ({sps[n//4]:.0f}..{sps[(3*n)//4]:.0f})"
              f" {median(sts):>11.0f}  "
              + "/".join(f"{100*v/tot:.0f}" for v in shape))
        per_scen[scen].append((median(sps), median(sts)))
    print("\nscenario baselines (median across cells):")
    baselines = {}
    for scen, vals in sorted(per_scen.items()):
        baselines[scen] = {"sp": round(median(v[0] for v in vals), 1),
                           "st": round(median(v[1] for v in vals), 1),
                           "cells": len(vals)}
        print(f"  {scen_name[scen]:>5}: SP {baselines[scen]['sp']:.0f}  "
              f"stat {baselines[scen]['st']:.0f}  ({len(vals)} cells)")
    if args.json_out:
        out = {"baselines": {str(k): v for k, v in baselines.items()}, "cells": {}}
        for (trainee, scen), rows in cells.items():
            if len(rows) < args.min_n:
                continue
            shape = [median(r["st"][i] for r in rows) for i in range(5)]
            tot = sum(shape) or 1
            out["cells"][f"{trainee}:{scen}"] = {
                "n": len(rows),
                "sp": round(median(r["sp_resid"] for r in rows), 1),
                "st": round(median(r["st_resid"] for r in rows), 1),
                "shape": [round(v / tot, 3) for v in shape],
            }
        args.json_out.write_text(json.dumps(out, indent=0))
        print(f"wrote {args.json_out} ({len(out['cells'])} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

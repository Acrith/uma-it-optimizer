"""Backtest the shipped planner model against the whole corpus.

Runs the SAME model the website uses (uma-it-web/planner/model.py,
loaded standalone - it is pure) over every receipt and aggregates
predicted-vs-actual error by scenario and channel, plus a monthly
trend. Output feeds the /accuracy page.

Usage: python backtest.py --runs <dir> \
    --out ../../../uma-it-web/uma_it_web/enrich/data/accuracy_report.json
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

_WEB = Path(__file__).parent / "../../../uma-it-web/uma_it_web"


def _load(name: str, rel: str):
    spec = _ilu.spec_from_file_location(name, _WEB / rel)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


model = _load("planner_model", "planner/model.py")
career = _load("career", "enrich/career.py")

STAT = ["<Speed>k__BackingField", "<Stamina>k__BackingField",
        "<Power>k__BackingField", "<Guts>k__BackingField",
        "<Wiz>k__BackingField"]
SP = "<SkillPoint>k__BackingField"


def min_races(trainee: int, scen: int) -> int:
    if scen == 4:
        return 4
    objs = career.objectives_for(str(trainee))
    if not objs:
        return 9
    turns = {o.get("Turn") for o in objs
             if career.race_by_name(o.get("ObjectiveName") or "")}
    return len(turns) + 1 + 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    stat_d = defaultdict(list)          # scen -> deltas (covered cells)
    stat_d_adj = defaultdict(list)      # same, schedule-jitter adjusted
    sp_d = defaultdict(list)            # (scen, has_pal) -> rel SP deltas
    ev_sp_d = defaultdict(list)
    ev_st_d = defaultdict(list)
    month_stat = defaultdict(list)      # YYYY-MM -> |stat delta|
    n_runs = 0
    for p in sorted(args.runs.glob("*/*.json")):
        parts = p.stem.split("_")
        if len(parts) < 3 or not parts[2].startswith("uma"):
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = (raw.get("SingleModeChara") or [{}])[0]
        scen = int(ch.get("scenario_id") or 0)
        races = len(raw.get("RaceHistory") or [])
        trainee = int(parts[2][3:]) if parts[2][3:].isdigit() else 0
        deck = [(int(e.get("support_card_id") or 0), int(e.get("exp") or 0),
                 int(e.get("limit_break_count") or 0))
                for e in (ch.get("support_card_array") or [])]
        if not deck or not races:
            continue
        try:
            pred = model.predict_run(deck, scen, races, trainee)
        except Exception:
            continue
        if pred is None:
            continue
        n_runs += 1
        month = f"{parts[0][:4]}-{parts[0][4:6]}"
        skey = "2d" if (scen == 2 and races > 21) else str(scen)
        by_cid = {c["card_id"]: c for c in pred.cards}
        pal_ids = model.PAL_BY_SCENARIO.get(scen, set())
        has_pal = any(cid in pal_ids for cid, _e, _l in deck)
        actual_ev = None
        pairs = []
        for e in raw.get("SupportCardGainInfo") or []:
            cid = e["<SupportCardId>k__BackingField"]
            c = by_cid.get(cid)
            if not c or not c["covered"] or c["pal"]:
                continue
            g = e["<GainInfo>k__BackingField"]
            pairs.append(([g.get(f, 0) for f in STAT], c["stats"],
                          c.get("cmd") or 0))
            if c["sp"] and g.get(SP):
                sp_d[(skey, has_pal)].append((g[SP] - c["sp"]) / c["sp"])
        # Schedule jitter retrodiction (same adjustment the model check
        # displays): j = closest integer turn offset explaining the
        # whole receipt; the adjusted metric says how well the model
        # does once the run's rest/outing luck is known.
        fadj = 1.0
        t_run = model.turns_for(races)
        sa = sum(sum(a) for a, _p, _c in pairs)
        sp_sum = sum(sum(pp) for _a, pp, _c in pairs)
        # No adjustment in dice territory: the deviation there is not a
        # run-level scalar (dice hit facilities unevenly), so scaling
        # by the deck total makes rows worse, not better.
        if skey != "2d" and len(pairs) >= 3 and t_run and sp_sum:
            j = max(-3, min(3, round(t_run * (sa / sp_sum - 1))))
            fadj = (t_run + j) / t_run
        for a, pp, _cmd in pairs:
            for x, y in zip(a, pp, strict=False):
                stat_d[skey].append(x - y)
                stat_d_adj[skey].append(x - int(y * fadj))
                month_stat[month].append(abs(x - y))
        gi = raw.get("GainInfo") or []
        actual_ev = gi[0] if gi else None
        if actual_ev is not None:
            parts_ = pred.parts
            opt = max(0, races - min_races(trainee, scen))
            rmul = 1 + (parts_.get("deck_rb") or 0) / 100
            ev_sp_pred = (parts_["base"]["sp"] + parts_["trainee"]["sp"]
                          + parts_["cards"]["sp"]
                          + parts_["race_per_sp"] * opt * rmul)
            ev_st_pred = (parts_["base"]["st"] + parts_["trainee"]["st"]
                          + parts_["cards"]["st"]
                          + parts_["race_per_st"] * opt * rmul)
            ev_sp_d[scen].append(actual_ev.get(SP, 0) - ev_sp_pred)
            ev_st_d[scen].append(
                sum(actual_ev.get(f, 0) for f in STAT) - ev_st_pred)

    def agg(v):
        a = np.array(v, dtype=float)
        if not len(a):
            return None
        return {"n": len(a), "median": round(float(np.median(a)), 1),
                "med_abs": round(float(np.median(np.abs(a))), 1),
                "p90_abs": round(float(np.percentile(np.abs(a), 90)), 1),
                "within1": round(float(np.mean(np.abs(a) <= 1)), 3)}

    report = {
        "meta": {"runs": n_runs},
        "cards_stat": {s: agg(v) for s, v in sorted(stat_d.items())},
        "cards_stat_sched_adj": {s: agg(v)
                                 for s, v in sorted(stat_d_adj.items())},
        "cards_sp_rel": {f"{s}{'_pal' if pal else ''}":
                         {"n": len(v),
                          "median_pct": round(float(np.median(v)) * 100, 1),
                          "p90_abs_pct": round(float(np.percentile(
                              np.abs(v), 90)) * 100, 1)}
                         for (s, pal), v in sorted(sp_d.items()) if v},
        "events_sp": {str(s): agg(v) for s, v in sorted(ev_sp_d.items())},
        "events_st": {str(s): agg(v) for s, v in sorted(ev_st_d.items())},
        "monthly_stat_medabs": {m: round(float(np.median(v)), 2)
                                for m, v in sorted(month_stat.items())
                                if len(v) >= 200},
    }
    args.out.write_text(json.dumps(report, indent=0))
    print(json.dumps(report["cards_stat"], indent=1))
    print("SP rel:", report["cards_sp_rel"])
    print("monthly:", report["monthly_stat_medabs"])
    print(f"wrote {args.out} over {n_runs} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

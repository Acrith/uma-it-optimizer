"""Predict a full IT receipt: deck + scenario + races -> five stats + SP per card.

The optimizer's core, composing every solved channel (see
../../../uma-it-web/docs/research-handoff.md):

    stat_i = floor(u_s * T(races) * (C_s(races) + axis + dx_i))
    sp     = floor(k_s * T(races) * W_card)        +- ~6% (hint RNG)

dx_i is the per-(card, level, stat) surplus table measured from the
corpus (median; covers the base offset, the initial channel and the
facility E package in one number). W is the measured SP weight table.
Cards without corpus coverage fall back to dx=0 / W unknown and are
flagged - base-only predictions.

Pal-carrying decks apply the pal law m*(C+X+delta) with the measured
(m, delta) bands; E under a pal is unmeasured, so pal predictions are
base-and-SP only.

Validation (--validate) is COLD: dx and W tables are fitted on half the
pal-free corpus (run-key hash parity) and scored on the other half.

Usage:
    python predict_deck.py --mdb master.mdb --runs <dir> \
        --deck 20016:45,30016:50,... --scenario 3 --races 9
    python predict_deck.py --mdb master.mdb --runs <dir> --validate
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from e_table import STAT_NAMES
from it_formula import Masters, axis_of, load_run
from offset_sweep import STAT_FIELDS, U, c_bounds, turns
from sp_weights import solve as solve_w

SP_K = {1: 2.403, 3: 2.602, 4: 2.401}
# Pal law bands, (m_mid, delta_mid), measured 2026-08-13.
PAL_LAW = {"R": (1.10, -55.0), "SR": (1.127, 0.0), "SSR": (1.50, -60.0)}


def collect_runs(runs_dir: Path, masters: Masters, half: int | None = None):
    """Deduped pal-free URA/GL/TB runs; half=0/1 splits by run-key parity."""
    out = []
    seen = set()
    for p in sorted(runs_dir.glob("*/*.json")):
        try:
            r = load_run(p, masters)
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not r or r["scenario"] not in U or r.get("has_pal"):
            continue
        if not r["races"] or turns(r["races"]) is None:
            continue
        key = (r["scenario"], r["races"],
               tuple(sorted((x.card_id, x.level) for x in r["rows"])))
        if key in seen:
            continue
        seen.add(key)
        if half is not None and hash(key) % 2 != half:
            continue
        lv = {x.card_id: (x.level, x.axis) for x in r["rows"]}
        cards = {}
        sps = {}
        for e in raw.get("SupportCardGainInfo") or []:
            cid = e["<SupportCardId>k__BackingField"]
            if cid not in lv or cid == 30078:
                continue
            g = e["<GainInfo>k__BackingField"]
            cards[(cid, lv[cid][0])] = (
                [g[f] for f in STAT_FIELDS], lv[cid][1])
            sp = g.get("<SkillPoint>k__BackingField")
            if sp:
                sps[(cid, lv[cid][0])] = sp
        out.append({"scen": r["scenario"], "races": r["races"],
                    "cards": cards, "sp": sps})
    return out


def fit_tables(runs):
    """-> dx {(card,level,stat): median}, W {(card,level): weight}."""
    dx_acc = defaultdict(list)
    sp_runs = []
    for r in runs:
        ut = U[r["scen"]] * turns(r["races"])
        clo, chi = c_bounds(r["scen"], r["races"])
        cm = (clo + chi) / 2
        for (cid, lvl), (stats, axis) in r["cards"].items():
            for i, v in enumerate(stats):
                dx_acc[(cid, lvl, i)].append((v + 0.5) / ut - cm - axis)
        if len(r["sp"]) >= 2:
            sp_runs.append({"sp": {k: v + 0.5 for k, v in r["sp"].items()}})
    dx = {k: median(v) for k, v in dx_acc.items() if len(v) >= 3}
    w_raw = solve_w(sp_runs) if sp_runs else {}
    # Anchor W's arbitrary scale so that sp = k * T * W matches the
    # fitting half directly: scale = median(sp / (k*T*W_raw)).
    scales = []
    for r in runs:
        kt = SP_K[r["scen"]] * turns(r["races"])
        for k2, v in r["sp"].items():
            if k2 in w_raw and w_raw[k2] > 0:
                scales.append((v + 0.5) / (kt * w_raw[k2]))
    s = median(scales) if scales else 1.0
    return dx, {k: v * s for k, v in w_raw.items()}


def predict_card(masters, dx, w, cid, lvl, scenario, races):
    fb, mo, te, ini, _ = masters.bonuses(cid, lvl)
    axis = axis_of(fb, mo, te)
    ut = U[scenario] * turns(races)
    clo, chi = c_bounds(scenario, races)
    cm = (clo + chi) / 2
    stats = []
    covered = (cid, lvl, 0) in dx
    for i in range(5):
        d = dx.get((cid, lvl, i), 0.0)
        stats.append(int(ut * (cm + axis + d)))
    wt = w.get((cid, lvl))
    sp = int(SP_K[scenario] * turns(races) * wt) if wt else None
    return stats, sp, covered


def validate(masters, runs_dir):
    fit = collect_runs(runs_dir, masters, half=0)
    test = collect_runs(runs_dir, masters, half=1)
    dx, w = fit_tables(fit)
    ch = {"base": [0, 0, 0], "E": [0, 0, 0]}
    sp_n = 0
    sp_err = []
    for r in test:
        for (cid, lvl), (obs, _axis) in r["cards"].items():
            pred, spd, covered = predict_card(
                masters, dx, w, cid, lvl, r["scen"], r["races"])
            if not covered:
                continue
            base_val = sorted(obs)[1]
            for i in range(5):
                bucket = ch["base" if obs[i] <= base_val else "E"]
                bucket[0] += 1
                bucket[1] += pred[i] == obs[i]
                bucket[2] += abs(pred[i] - obs[i]) <= 1
            o = r["sp"].get((cid, lvl))
            if o and spd:
                sp_n += 1
                sp_err.append(abs(spd - o) / o)
    print(f"COLD validation (fit {len(fit)} runs, test {len(test)} runs)")
    for name, (n, ex, w1) in ch.items():
        print(f"  {name:>4} stats: n={n}  exact {100 * ex / n:.1f}%  "
              f"within +-1 {100 * w1 / n:.1f}%")
    sp_err.sort()
    print(f"  SP: n={sp_n}  median |err| {100 * sp_err[len(sp_err) // 2]:.1f}%  "
          f"p90 {100 * sp_err[int(len(sp_err) * .9)]:.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--deck", help="comma list of id:level")
    ap.add_argument("--scenario", type=int, choices=(1, 3, 4))
    ap.add_argument("--races", type=int)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    masters = Masters(args.mdb)
    if args.validate:
        validate(masters, args.runs)
        return 0
    if not (args.deck and args.scenario and args.races):
        ap.error("--deck, --scenario and --races (or --validate)")
    dx, w = fit_tables(collect_runs(args.runs, masters))
    print(f"{'card':>7} {'lv':>3}  " +
          " ".join(f"{n:>5}" for n in STAT_NAMES) +
          f" {'SP':>5}  name")
    tot = [0] * 5
    tsp = 0
    for chunk in args.deck.split(","):
        cid, _, lvl = chunk.partition(":")
        cid, lvl = int(cid), int(lvl)
        stats, sp, covered = predict_card(
            masters, dx, w, cid, lvl, args.scenario, args.races)
        for i in range(5):
            tot[i] += stats[i]
        tsp += sp or 0
        flag = "" if covered else "  [no corpus coverage: base only]"
        print(f"{cid:>7} {lvl:>3}  " +
              " ".join(f"{s:>5}" for s in stats) +
              f" {sp if sp else '?':>5}  "
              f"{masters.card_name.get(cid, '?')}{flag}")
    print(f"{'total':>12}  " + " ".join(f"{s:>5}" for s in tot) +
          f" {tsp:>5}   (SP +-6% per run; E stats +-8-10%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

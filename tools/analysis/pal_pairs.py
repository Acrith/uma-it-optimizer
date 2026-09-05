"""Pal-law (m, delta) feasibility from matched pairs.

Usage: python pal_pairs.py <runs_dir>

First run (2026-09-05, proddb11): 4 URA SR-Kiryuin lv45 pairs, 11
cells -> old SR law (1.127, 0) infeasible; region contains the R box;
unified (1.10, -55) scores 99.3% of 284 pal card bases within +-1 vs
84.9%. Currently URA-only; extend scenario/pal sets to re-audit GL
SSR-Hello when new low-LB pairs arrive.

Pair = pal run + pal-free run, same scenario/races/mood, all the pal
run's non-pal (card, level) cells present in the pal-free run. Per
shared card: pal-free base b0 bounds (C+X) in [b0/uT, (b0+1)/uT);
pal base b1 needs m*(C+X+delta) in [b1/uT, (b1+1)/uT).
"""
import json, sys
from pathlib import Path
from collections import defaultdict
from it_formula import Masters, load_run
from offset_sweep import U, turns

RUNS = Path(sys.argv[1])
masters = Masters(Path(__file__).parent / '../../references/master.mdb')
PALS = {10022: 'R-Kiryuin', 20021: 'SR-Kiryuin'}

palruns, freeruns = [], []
for p in sorted(RUNS.glob('*/*.json')):
    try:
        r = load_run(p, masters)
        if not r or r['scenario'] != 1 or not r['races'] or turns(r['races']) is None:
            continue
        if r['has_pal']:
            raw = json.loads(p.read_text())
            deck = {int(c.get('support_card_id') or 0): (int(c.get('exp') or 0), int(c.get('limit_break_count') or 0))
                    for c in raw['SingleModeChara'][0].get('support_card_array') or []}
            pid = next((c for c in deck if c in PALS), None)
            if pid is None: continue
            plv = masters.level_from_exp(pid, *deck[pid])
            r['pal'] = (pid, plv)
            palruns.append(r)
        else:
            freeruns.append(r)
    except Exception:
        continue

# index pal-free by (races, mood) -> {(card,level): [bases]}
idx = defaultdict(list)
for r in freeruns:
    idx[(r['races'], r['mood'])].append(r)

def cells(r):
    return {(c.card_id, c.level): c.base for c in r['rows']}

constraints_by_pal = defaultdict(list)   # (pal_id, pal_lv) -> [(cx_lo, cx_hi, lo1, hi1, tag)]
pairs = 0
seen_pairs = set()
for pr in palruns:
    pcells = cells(pr)
    if len(pcells) < 4: continue
    for (races, mood), frs in idx.items():
      if races != pr['races']: continue
      for fr in frs:
        fcells = cells(fr)
        shared = set(pcells) & set(fcells)
        if len(shared) < 5: continue
        if mood != pr['mood']:
            # run-motivation reaches a card through its Mood bonus -
            # only Mood-0 cards constrain across a mood mismatch
            shared = {cl for cl in shared
                      if masters.bonuses(cl[0], cl[1])[1] == 0}
            if len(shared) < 2: continue
        key = (pr['file'], tuple(sorted(shared)))
        if key in seen_pairs: continue
        seen_pairs.add(key)
        uT = U[1] * turns(pr['races'])
        pairs += 1
        for cl in shared:
            b0, b1 = fcells[cl], pcells[cl]
            constraints_by_pal[pr['pal']].append(
                (b0 / uT, (b0 + 1) / uT, b1 / uT, (b1 + 1) / uT,
                 f"{pr['file'][:15]} r{pr['races']} m{pr['mood']} card{cl[0]}@{cl[1]}"))

print(f'URA runs: {len(palruns)} pal / {len(freeruns)} pal-free; matched pairs: {pairs}')
for pal, cons in sorted(constraints_by_pal.items()):
    pid, plv = pal
    feas, near = [], []
    M = [1.0 + 0.002 * i for i in range(300)]
    D = list(range(-160, 61, 2))
    best_viol, best_cells = 10**9, None
    for m in M:
        for d in D:
            viol = sum(1 for lo0, hi0, lo1, hi1, _ in cons
                       if not (m * (hi0 + d) > lo1 and m * (lo0 + d) < hi1))
            if viol == 0: feas.append((m, d))
            if viol < best_viol: best_viol = viol
    if feas:
        ms = [f[0] for f in feas]; ds = [f[1] for f in feas]
        print(f'{PALS[pid]} lv{plv}: n={len(cons)} cells  FEASIBLE  m [{min(ms):.3f}, {max(ms):.3f}]  delta [{min(ds)}, {max(ds)}]')
        at0 = [m for m, d in feas if d == 0]
        if at0: print(f'   at delta=0: m [{min(at0):.3f}, {max(at0):.3f}]')
        near_law = [d for m, d in feas if abs(m - 1.127) < 0.002]
        if near_law: print(f'   at m=1.127 (current SR law): delta [{min(near_law)}, {max(near_law)}]')
        print(f'   law point (1.127, 0) feasible: {any(abs(m-1.127)<0.002 and d==0 for m,d in feas)}')
        rbox = [(m, d) for m, d in feas if 1.091 <= m <= 1.112 and -89 <= d <= -24]
        print(f'   overlap with R-pal law box (m 1.091-1.112, delta -89..-24): {len(rbox)} grid pts'
              + (f', e.g. {rbox[:3]}' if rbox else ''))
        at_r = [d for m, d in feas if abs(m - 1.10) < 0.002]
        if at_r: print(f'   at m=1.10 (R law mid): delta [{min(at_r)}, {max(at_r)}]')
    else:
        print(f'{PALS[pid]} lv{plv}: n={len(cons)} cells  EMPTY (best leaves {best_viol} violated)')
        # drop-k tolerant: find region with <= best_viol violations
        for m in M:
            for d in D:
                viol = [t for lo0, hi0, lo1, hi1, t in cons
                        if not (m * (hi0 + d) > lo1 and m * (lo0 + d) < hi1)]
                if len(viol) == best_viol: near.append((m, d, viol))
        ms = [x[0] for x in near]; ds = [x[1] for x in near]
        from collections import Counter
        cc = Counter(t for x in near for t in x[2])
        print(f'   drop-{best_viol}: m [{min(ms):.3f}, {max(ms):.3f}] delta [{min(ds)}, {max(ds)}]; most-violated: {cc.most_common(3)}')

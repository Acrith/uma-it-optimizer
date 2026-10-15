"""Does a trainer card's deck slot change how often its event chain finishes?

The owner, 2026-10-15, from manual careers: cards in later slots seem to
finish their chains less often than slot 1 or 2. Kris S in the friend slot
(slot 6) finished once in 7 manual runs; Tachyon in slot 1 gave all three
chain events every run. Does Independent Training do the same?

The chain's finish is read as in chain_events.py: a trainer card whose
events can give a gold gives it only when its chain gets far enough, and a
run counts for that gold when nothing else in it could give it (no other
deck card's events, the trainee's, the scenario's own at 20%+). The slot is
the card's `position` in SingleModeChara.support_card_array: 1-5 the
player's own cards, 6 always the borrowed friend (checked on the 2026-10-07
pull: 23,707 runs, no exception), so slot 6 and "borrowed" can't be told
apart here.

    logit P(gold) = palStep[pals] + offset[card x scenario x gold] + slotStep[slot]   (slot 1 = 0)

PREDICTIONS, written 2026-10-15 before the first run:
  S1  (what I expect) IT picks card events without regard to deck order:
      every slot step within +-0.15 log-odds of slot 1, and each slot's
      observed chain golds within 5% of what the model without slots
      predicts for its cards and pals.
  S2  (the owner's manual-career pattern, if IT shares it) slots 5 and 6
      clearly lower: slot 6's step at or below -0.3 log-odds and more than
      3 SE from 0, the steps falling with the slot number.
  S3  whichever holds, it holds within players too (an offset per player x
      card x gold): the same sign, over 2 SE.
A slot effect counts as real only if S2's size shows in both the pooled fit
and S3. Limit break is checked apart (a borrowed card is LB4 more often).

RESULT, 2026-10-15, the 2026-10-07 pull (23,707 runs; 63,931 chain-gold
trials in 114 card x scenario x gold cells, gold rate 22.2%):
  S2 rejected: no slot loses. Slots 2-5 within +0.07 of slot 1 (+0.057,
     +0.071, +0.012, +0.067; SE about 0.036); slot 6, the friend, +0.167
     (SE 0.054), the other way from S2.
  S1 holds for slots 2-5 and nearly for 6: each slot's chain golds 0.97 to
     1.03 times what the model without slots predicts (the friend 18.9%
     against 18.3% expected).
  S3 within players (468 cells, 34,144 trials): every step positive, none
     over 2 SE (slot 6 +0.26, SE 0.14).
  With an LB4 term slot 6 stays +0.21; LB4 itself -0.09 (SE 0.04).
  In IT a card's slot doesn't cost it its chain; the friend slot finishes
  a little more often, if at all. Agnes Tachyon (30101) as a sample: 33.3%
  in slots 1-5 (7,339), 26.3% as a friend (38, too few to tell). No Kris S
  card had a countable chain gold.

    uv run python tools/loop/slot_chains.py --runs <receipts> --master <master.mdb> \\
        --events <card_event_skills.json> --trainee-events <trainee_events.json> \\
        --scenario-hints <scenario_event_hints.json>

Aggregates only.
"""
# ruff: noqa: E501  (report lines)

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import sqlite3

import numpy as np
from scipy.optimize import minimize

TURNS = 78
TOP_PALS = 5
SLOTS = 6


def load(path):
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def trials(args) -> list[tuple]:
    """(card x scenario x gold, player, pals, slot, LB4, hit) per trainer card's chain gold."""
    db = sqlite3.connect(f"file:{args.master}?mode=ro", uri=True)
    group = {i: (g, r) for i, g, r in db.execute("select id, group_id, rarity from skill_data")}
    ctype = dict(db.execute("select id, support_card_type from support_card_data"))
    ev_r = {int(c): {group[s] for s in v if s in group} for c, v in load(args.events)["cards"].items()}
    golds = {c: {g for g, r in v if r == 2} for c, v in ev_r.items()}
    scen = {int(s): {int(g) for g, sh in v.get("groups", {}).items() if sh >= 0.2} for s, v in load(args.scenario_hints).items()}
    tr = {int(c): {group[s] for e in t.get("events", []) for s, _ in e.get("skills", []) if s in group}
          for c, t in load(args.trainee_events)["trainees"].items()}
    rows = []
    for path in glob.glob(f"{args.runs}/*/*.gz"):
        try:
            d = json.load(gzip.open(path))
            ch = d["SingleModeChara"][0]
            scs, gis = d["SupportCardGainInfo"], d["GainInfo"]
        except Exception:
            continue
        arr = ch.get("support_card_array") or []
        if ch.get("turn") != TURNS or len(scs) != 6 or len(gis) != 8 or len(arr) != 6:
            continue
        slot = {int(c["support_card_id"]): int(c["position"]) for c in arr}
        lb = {int(c["support_card_id"]): int(c.get("limit_break_count") or 0) for c in arr}
        cards = [c["<SupportCardId>k__BackingField"] for c in scs]
        if set(cards) != set(slot):
            continue
        pals = sum(1 for c in arr if ctype.get(int(c.get("support_card_id") or 0)) in (2, 3))
        sc = ch.get("scenario_id")
        user = path.rsplit("/", 2)[-2]
        ev_tips = {(h["group_id"], h.get("rarity", 1)) for h in gis[0].get("<SkillTipsArray>k__BackingField") or [] if isinstance(h, dict)}
        trainee_g = {g for g, r in tr.get(int(ch.get("card_id") or 0), ()) if r == 2}
        for i, c in enumerate(cards):
            if ctype.get(c) != 1 or not golds.get(c):
                continue
            own = {(h["group_id"], h.get("rarity", 1))
                   for h in (scs[i].get("<GainInfo>k__BackingField") or {}).get("<SkillTipsArray>k__BackingField") or [] if isinstance(h, dict)}
            others = set().union(*(golds.get(o, set()) for j, o in enumerate(cards) if j != i)) | trainee_g | scen.get(sc, set())
            for g in golds[c] - others:
                hit = (g, 2) in own or (g, 2) in ev_tips
                rows.append(((c, sc, g), user, min(pals, TOP_PALS), slot[c], int(lb[c] == 4), int(hit)))
    return rows


def fit(cell: np.ndarray, pal: np.ndarray, slot: np.ndarray, y: np.ndarray, extra: np.ndarray | None = None,
        with_slots: bool = True) -> tuple[np.ndarray, np.ndarray, float]:
    """Logistic fit: pal steps (2 pals = 0), slot steps (slot 1 = 0), an
    offset per cell, optionally one extra 0/1 column. The parameters, their
    standard errors (the information matrix inverted), the log-likelihood."""
    n_cells = int(cell.max()) + 1
    k_slot = SLOTS - 1 if with_slots else 0
    cols = []
    for p in (0, 1, 3, 4, 5):
        cols.append((pal == p).astype(float))
    for s in range(2, 2 + k_slot):
        cols.append((slot == s).astype(float))
    if extra is not None:
        cols.append(extra.astype(float))
    X = np.column_stack(cols) if cols else np.zeros((len(y), 0))
    C = np.zeros((len(y), n_cells))
    C[np.arange(len(y)), cell] = 1.0
    X = np.hstack([X, C])

    def nll(th):
        z = X @ th
        return float(np.sum(np.logaddexp(0, z) - y * z)), X.T @ (1 / (1 + np.exp(-z)) - y)

    r = minimize(nll, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B")
    p = 1 / (1 + np.exp(-(X @ r.x)))
    H = X.T @ (X * (p * (1 - p))[:, None])
    cov = np.linalg.pinv(H)
    return r.x, np.sqrt(np.maximum(np.diag(cov), 0)), -r.fun


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("runs", "master", "events", "trainee-events", "scenario-hints"):
        ap.add_argument(f"--{a}", required=True)
    args = ap.parse_args()
    rows = trials(args)
    print(f"chain-gold trials {len(rows)}")
    cells = collections.Counter(r[0] for r in rows)
    keep = {k for k, n in cells.items() if n >= 40}
    rows = [r for r in rows if r[0] in keep]
    kidx = {k: i for i, k in enumerate(sorted(keep))}
    cell = np.array([kidx[r[0]] for r in rows])
    pal = np.array([r[2] for r in rows])
    slot = np.array([r[3] for r in rows])
    lb4 = np.array([r[4] for r in rows])
    y = np.array([r[5] for r in rows], float)
    print(f"cells (card x scenario x gold, 40+ trials) {len(keep)}; trials {len(rows)}; gold rate {y.mean():.3f}")

    th, se, ll = fit(cell, pal, slot, y)
    th0, _, ll0 = fit(cell, pal, slot, y, with_slots=False)
    print("\n== S1/S2 pooled: slot steps (log-odds against slot 1)")
    for s in range(2, SLOTS + 1):
        b, e = th[5 + s - 2], se[5 + s - 2]
        print(f"   slot {s}{' (friend)' if s == 6 else '         '} {b:+.3f}  SE {e:.3f}  ({b / e if e else float('nan'):+.1f} SE)")
    print(f"   log-likelihood {ll:.1f} with slots vs {ll0:.1f} without (5 more parameters)")

    # Observed against what the model without slots predicts, slot by slot.
    X0 = np.column_stack([(pal == p).astype(float) for p in (0, 1, 3, 4, 5)])
    z0 = X0 @ th0[:5] + th0[5:][cell]
    p0 = 1 / (1 + np.exp(-z0))
    print(f"\n   {'slot':>8} {'trials':>7} {'gold':>6} {'expected':>9} {'ratio':>6}")
    for s in range(1, SLOTS + 1):
        m = slot == s
        print(f"   {s:>4}{' fr' if s == 6 else '   '} {int(m.sum()):>7} {y[m].mean():6.1%} {p0[m].mean():9.1%} {y[m].sum() / p0[m].sum():6.3f}")

    # LB apart: the friend is LB4 more often.
    th_l, se_l, _ = fit(cell, pal, slot, y, extra=lb4)
    print(f"\n   with an LB4 term: LB4 {th_l[10]:+.3f} (SE {se_l[10]:.3f}); slot 6 {th_l[9]:+.3f} (SE {se_l[9]:.3f})")

    # S3: within players.
    ucell = collections.Counter((r[1], r[0]) for r in rows)
    ukeep = {k for k, n in ucell.items() if n >= 15 and len({rr[3] for rr in rows if (rr[1], rr[0]) == k}) > 1}
    sub = [i for i, r in enumerate(rows) if (r[1], r[0]) in ukeep]
    if sub:
        uk = sorted(ukeep)
        uidx = {k: i for i, k in enumerate(uk)}
        ui = np.array([uidx[(rows[i][1], rows[i][0])] for i in sub])
        th2, se2, _ = fit(ui, pal[sub], slot[sub], y[sub])
        print(f"\n== S3 within players ({len(uk)} player x card x gold cells with 15+ trials in 2+ slots, {len(sub)} trials)")
        for s in range(2, SLOTS + 1):
            b, e = th2[5 + s - 2], se2[5 + s - 2]
            print(f"   slot {s}{' (friend)' if s == 6 else '         '} {b:+.3f}  SE {e:.3f}  ({b / e if e else float('nan'):+.1f} SE)")


if __name__ == "__main__":
    main()

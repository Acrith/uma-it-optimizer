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
from predict_deck import SP_K, collect_runs, event_bugged, fit_tables


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
        """Effect-table race bonus (type 15) PLUS any unique-effect race
        bonus once its level gate is met - e.g. Marvelous Sunday's SSR
        carries +5% in her unique, Turf as Nails' famous rider likewise."""
        total = 0.0
        row = conn.execute(
            "select * from support_card_effect_table where id=? and type=15",
            (cid,)).fetchone()
        if row:
            pts = [(a, v) for a, v in zip(BP, row[2:13], strict=False)
                   if v != -1]
            if pts and lv >= pts[0][0]:
                total = float(pts[-1][1])
                for (x0, v0), (x1, v1) in zip(pts, pts[1:], strict=False):
                    if lv <= x1:
                        total = v0 + (v1 - v0) * (lv - x0) / (x1 - x0)
                        break
        for gate, t0, v0, t1, v1 in conn.execute(
                "select lv, type_0, value_0, type_1, value_1 "
                "from support_card_unique_effect where id=?", (cid,)):
            if lv >= gate:
                for t, v in ((t0, v0), (t1, v1)):
                    if t == 15:
                        total += v
        return total
    runs = collect_runs(args.runs, masters)
    # min_n=1: rows are deterministic given setup+mood (2026-09-07),
    # and cold validation PREFERS single-observation cells over
    # dropping them (93.7% vs 93.1% within +-1, 329 vs 203 cells).
    (dx, dx_scen), w = fit_tables(runs, min_n=1)

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
        for scen in (1, 2, 3, 4):
            if (cid, lvl, 0, scen) in dx_scen:
                entry["dx_scen"][str(scen)] = [
                    round(dx_scen.get((cid, lvl, i, scen),
                                      dx.get((cid, lvl, i), 0.0)), 1)
                    for i in range(5)]
        # SP does NOT share the stat rows' determinism: a W observed
        # once at low level misses by ~50% on unseen runs (Unity SP p90
        # blew to 53% when min_n=1 shipped thin W). Three SP samples
        # minimum; stats keep min_n=1.
        wt = w.get((cid, lvl))
        w_n = sum(1 for r in runs if (cid, lvl) in r["sp"])
        entry["w"] = round(wt, 2) if wt and w_n >= 3 else None
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
        if not e["cmd"]:
            # friend/group rows (no facility) would pollute a cmd-0
            # bucket with group-offset-absorbed dx; keep priors trainer
            continue
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

    # Friend / group card SP weights, measured from ALL runs (their W
    # cannot come from the pal-free fit by construction: pals never
    # appear pal-free and group cards ride pal decks). SP of a non-pal
    # card in a pal deck scales by the pal multiplier m, the pal's own
    # row does not - divide it back out. Measured 2026-09-06 with
    # IQRs of a few percent (Light Hello lv50 W=3.01, Thrones 2.05).
    from statistics import median as _med
    sc_type = {r[0]: r[1] for r in conn.execute(
        "select id, support_card_type from support_card_data")}
    seen_in_receipts: set[int] = set()
    M_BY_RARITY = {1: 1.10, 2: 1.10, 3: 1.50}
    PAL_IDS_ALL = {10022, 20021, 10060, 30036, 10083, 30052}
    fg_acc: dict = defaultdict(list)
    for p_ in sorted(args.runs.glob("*/*.json")):
        try:
            raw = json.loads(p_.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = (raw.get("SingleModeChara") or [{}])[0]
        scen = int(ch.get("scenario_id") or 0)
        races = len(raw.get("RaceHistory") or [])
        from offset_sweep import turns as _turns
        from predict_deck import SP_K as _SPK
        if scen not in _SPK or not races or _turns(races) is None:
            continue
        if scen == 2 and races > 21:
            continue
        deck = {int(e.get("support_card_id") or 0):
                (int(e.get("exp") or 0), int(e.get("limit_break_count") or 0))
                for e in ch.get("support_card_array") or []}
        scen_pals = {1: {10022, 20021}, 2: {10060, 30036},
                     3: {10083, 30052}, 4: set()}[scen]
        pal_id = next((c for c in deck if c in scen_pals), None)
        m_others = (M_BY_RARITY.get(pal_id // 10000, 1.0)
                    if pal_id else 1.0)
        kt = _SPK[scen] * _turns(races)
        seen_in_receipts.update(deck)
        for e in raw.get("SupportCardGainInfo") or []:
            cid2 = e["<SupportCardId>k__BackingField"]
            if sc_type.get(cid2, 1) == 1 or cid2 not in deck:
                continue
            spv = e["<GainInfo>k__BackingField"].get(
                "<SkillPoint>k__BackingField")
            if not spv:
                continue
            lv2 = masters.level_from_exp(cid2, *deck[cid2])
            if lv2 is None:
                continue
            m2 = 1.0 if cid2 == pal_id else m_others
            fg_acc[(cid2, lv2, scen)].append(spv / (kt * m2))
    # scenario-keyed: a friend card's SP economy differs in and out of
    # its own scenario (Light Hello's W is a third lower in URA than
    # GL); pooled fallback for thin scenarios
    fg_w: dict = {}
    pooled: dict = defaultdict(list)
    for (cid2, lv2, scen2), v in fg_acc.items():
        pooled[(cid2, lv2)].extend(v)
        if len(v) >= 10:
            fg_w.setdefault((cid2, lv2), {})[str(scen2)] = round(_med(v), 2)
    for key, v in pooled.items():
        if len(v) >= 10:
            fg_w.setdefault(key, {})["*"] = round(_med(v), 2)

    # Global-release filter: master.mdb carries JP-ahead cards that
    # nobody on global can own; they rendered NAMELESS in the planner
    # picker (no EN name) and only added noise. Released = flagged in
    # the gametora reference dump OR seen in the corpus (provably
    # owned - covers releases newer than the dump).
    gt_path = (Path(__file__).parent
               / "../../references/support_cards_gametora_data"
               / "gametora_support_cards_all_lb_2026-08-07.json")
    released: set[int] = {cid for (cid, _lvl) in counts} | seen_in_receipts
    try:
        for row in json.loads(gt_path.read_text(encoding="utf-8")):
            if row.get("Released_Global_By_Snapshot"):
                released.add(int(row["Support_ID"]))
    except OSError:
        released = set()          # dump missing: filter off, keep all

    # Cold cells: every trainer card at every LB cap level, axis only.
    # Pals (support_card_type 2) and group cards (type 3) are included
    # with a kind flag: pals get the pal law applied deck-wide by the
    # UI, group cards carry the rough measured +2500 X group offset.
    LB_CAP = {0: 30, 1: 35, 2: 40, 3: 45, 4: 50}
    rarity = {r[0]: r[1] for r in sqlite3.connect(str(args.mdb)).execute(
        "select id, rarity from support_card_data")}
    all_cards = sorted(sc_type)
    cold: dict = {}
    for cid in all_cards:
        if released and cid not in released:
            continue
        r = rarity.get(cid, 3)
        # Dense level grid, not just LB caps: a level-1 card borrowing
        # the level-20 cell's axis overpredicted by 50-64 points (the
        # worst individual cells in the 2026-09-06 outlier scan).
        base_lvls = [1, 5, 10, 15]
        if r == 1:
            caps = base_lvls + [20, 25, 30, 35, 40]
        elif r == 2:
            caps = base_lvls + [20, 25, 30, 35, 40, 45]
        else:
            caps = base_lvls + [20, 25] + list(LB_CAP.values())
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
                # Measured group offsets (X units) where the corpus has
                # pal-free coverage; the planner falls back to the rough
                # +2500 otherwise. 30067@50 URA: +1726 (IQR 1680-1805,
                # n=28, 2026-09-05).
                gx = {(30067, 50): 1726}.get((cid, lvl))
                if gx is not None:
                    entry_c["gx"] = gx
            cold[key] = entry_c

    # Attach the measured friend/group SP weights to their cells
    # (cold OR covered - friend/group rows join the fits now, so their
    # cells may be covered; the measured scenario-keyed W wins).
    for (cid2, lv2), wv in fg_w.items():
        cell = cold.get(f"{cid2}:{lv2}") or cards.get(f"{cid2}:{lv2}")
        if cell is not None:
            cell["w_scen"] = wv

    # Events + inspiration model per scenario (see it-formula.md
    # 2026-08-14): stat MASS is a near-constant per scenario with a
    # random split; events SP = a + b * races * (1 + deck race bonus).
    from statistics import median as med
    events = {}
    insp = {}
    for scen in (1, 3, 4):
        # event_bugged: runs inside the official Jul 22 - Aug 13 window
        # for the six affected trainees underreport trainee events -
        # they stay in the card-channel fits but not in this one.
        sub = [r for r in runs if r["scen"] == scen and any(r["ev"])
               and not event_bugged(r)]
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
        # finale: the 3 finale races ARE in RaceHistory (turns 74/76/
        # 78) but their program ids don't resolve to a grade through
        # single_mode_program, so the reconstruction skips them and
        # their all-stats+SP payout stays in the residual.
        # Measured via the reconstruction snippet in it-formula.md;
        # re-derive when the corpus shifts materially.
        RACE_EVENTS = {
            1: {"race_sp": 43.3, "race_st": 9.7, "ev_sp": 149, "ev_st": 1270},
            3: {"race_sp": 42.5, "race_st": 9.6, "ev_sp": 532, "ev_st": 1726},
            4: {"race_sp": 31.2, "race_st": 9.8, "ev_sp": 496, "ev_st": 1352},
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

    # Preset redistribution, CONTROLLED-PAIR measurement (2026-09-05):
    # race-matched same-deck same-trainee pairs (n=1,358 Stamina vs
    # Balanced) prove card rows are EXACTLY preset-immune (E-row delta
    # 0 on every stat) - redistribution lives in the events channel
    # only, as zero-sum ADDITIVE per-stat shifts. These replace the
    # August share-based multipliers (which wrongly also scaled dx).
    presets = {
        "Balanced": [0, 0, 0, 0, 0],
        "Stamina": [-5, 50, 0, -17, -28],
        "Sprint": [18, -32, 10, 4, 12],
    }

    # Per-card EVENT contributions (level-independent): enumeration
    # (top-option success totals) x measured chain completion rate,
    # scenario-mean rate for unmarked cards. See it-formula.md
    # 2026-09-05 for the derivation and its honest limits.
    here = Path(__file__).parent
    enum = json.loads((here / "event_enum.json").read_text())
    marker = json.loads((here / "chain_rates_measured.json").read_text())["marker_rates"]
    SCEN_MEAN_RATE = {"1": 0.15, "2": 0.16, "3": 0.12, "4": 0.08}
    card_ev: dict = {}
    for cid_s, e in enum.items():
        if released and int(cid_s) not in released:
            continue
        per = {}
        for scen in ("1", "2", "3", "4"):
            rate = (marker.get(cid_s) or {}).get(scen, SCEN_MEAN_RATE[scen])
            per[scen] = [round(e["chain"]["pt"] * rate + e["random"]["pt"], 1),
                         round(e["chain"]["stats"] * rate + e["random"]["stats"], 1)]
        card_ev[cid_s] = per

    # Scenario event base + trainee deltas, from the bare-run census
    # harvest (trainee_events.json). The bare baseline includes six
    # academy R cards' own events; subtract their mean card_ev so the
    # base is deck-independent and the planner re-adds the actual
    # deck's card events.
    te = json.loads((here / "trainee_events.json").read_text())
    ev_base: dict = {}
    for scen, b in te["baselines"].items():
        acad = [card_ev[c][scen] for c in card_ev
                if int(c) < 20000 and int(c) not in
                {10022, 20021, 10060, 30036, 10083, 30052}]
        a_sp = sum(v[0] for v in acad) / len(acad) if acad else 0
        a_st = sum(v[1] for v in acad) / len(acad) if acad else 0
        ev_base[scen] = {"sp": round(b["sp"] - 6 * a_sp, 1),
                         "st": round(b["st"] - 6 * a_st, 1)}
    # per-trainee deltas + event stat shape where measured
    umas = json.loads((Path(__file__).parent
                       / "../../../uma-it-web/uma_it_web/enrich/data/masters.json"
                       ).read_text()).get("uma_cards", {})
    trainees: dict = {}
    for key, cell in te["cells"].items():
        tid, scen = key.split(":")
        b = te["baselines"][scen]
        t = trainees.setdefault(tid, {"name": "", "d": {}})
        card = umas.get(tid) or {}
        nm = card.get("chara_name") or f"?{tid}"
        title = card.get("card_title") or ""
        t["name"] = f"{nm} {title}".strip()
        t["d"][scen] = {"sp": round(cell["sp"] - b["sp"], 1),
                       "st": round(cell["st"] - b["st"], 1),
                       "shape": cell["shape"], "n": cell["n"]}

    # Exp -> level thresholds per rarity, so the site can resolve a
    # receipt's support_card exp into the level the tables are keyed
    # by (receipts store exp + limit_break, never level).
    level_exp = {}
    for rar in (1, 2, 3):
        rows = conn.execute(
            "select level, total_exp from support_card_level "
            "where rarity=? order by level", (rar,)).fetchall()
        level_exp[str(rar)] = [[lv, exp] for lv, exp in rows]

    # Unity dice staircase (2026-09-07): beyond 21 races the rows still
    # obey stat = floor(u2 * T * (C2 + axis + dx)) with a run-level T
    # (one scalar per run explains trainer rows at 93% within +-1, and
    # SP holds under the same T with k2/W). Retrodict T per receipt
    # from the fitted tables and export the median staircase.
    t2_acc: dict = defaultdict(list)
    lvl_cache: dict = {}
    for p_ in sorted(args.runs.glob("*/*.json")):
        try:
            raw = json.loads(p_.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = (raw.get("SingleModeChara") or [{}])[0]
        if int(ch.get("scenario_id") or 0) != 2:
            continue
        races = len(raw.get("RaceHistory") or [])
        if races <= 21:
            continue
        deck = {int(e.get("support_card_id") or 0):
                (int(e.get("exp") or 0), int(e.get("limit_break_count") or 0))
                for e in ch.get("support_card_array") or []}
        pal_id = next((c for c in deck if c in (10060, 30036)), None)
        sa = sb = 0.0
        n_rows = 0
        for e in raw.get("SupportCardGainInfo") or []:
            cid2 = e["<SupportCardId>k__BackingField"]
            if cid2 not in deck:
                continue
            lv2 = masters.level_from_exp(cid2, *deck[cid2])
            ent = cards.get(f"{cid2}:{lv2}")
            if ent is None or not ent.get("cmd"):
                continue
            dxs = (ent.get("dx_scen") or {}).get("2") or ent["dx"]
            g = e["<GainInfo>k__BackingField"]
            is_pal = cid2 == pal_id
            m2, d2 = ((1.0, 0.0) if is_pal or not pal_id
                      else ((1.10, -55.0) if pal_id < 20000
                            else (1.50, -60.0)))
            sa += sum(g.get(f, 0) for f in
                      ("<Speed>k__BackingField", "<Stamina>k__BackingField",
                       "<Power>k__BackingField", "<Guts>k__BackingField",
                       "<Wiz>k__BackingField"))
            sb += sum(m2 * (2130.0 + ent["axis"] + d + d2) for d in dxs)
            n_rows += 1
        if n_rows >= 3 and sb > 0:
            t2_acc[races].append(sa / (sb * U[2]))
    t_dice = {str(r): round(_med(v), 2)
              for r, v in sorted(t2_acc.items()) if len(v) >= 5}

    # Per-facility dice ratios (2026-09-07): the dice's extra sessions
    # land disproportionately on the low-baseline facilities - guts and
    # wit rows run +8-9% hot at 22-27 races. Median ratio vs the T2
    # staircase per (facility, race bucket); 1.0 where unmeasured.
    fac_acc: dict = defaultdict(list)
    for p_ in sorted(args.runs.glob("*/*.json")):
        try:
            raw = json.loads(p_.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = (raw.get("SingleModeChara") or [{}])[0]
        if int(ch.get("scenario_id") or 0) != 2:
            continue
        races = len(raw.get("RaceHistory") or [])
        if races <= 21 or str(races) not in t_dice:
            continue
        t2m = t_dice[str(races)]
        deck = {int(e.get("support_card_id") or 0):
                (int(e.get("exp") or 0), int(e.get("limit_break_count") or 0))
                for e in ch.get("support_card_array") or []}
        pal_id = next((c for c in deck if c in (10060, 30036)), None)
        bucket = ("22-27" if races <= 27 else
                  "28-31" if races <= 31 else "32+")
        for e in raw.get("SupportCardGainInfo") or []:
            cid2 = e["<SupportCardId>k__BackingField"]
            if cid2 not in deck:
                continue
            lv2 = masters.level_from_exp(cid2, *deck[cid2])
            ent = cards.get(f"{cid2}:{lv2}")
            if ent is None or not ent.get("cmd"):
                continue
            dxs = (ent.get("dx_scen") or {}).get("2") or ent["dx"]
            g = e["<GainInfo>k__BackingField"]
            is_pal = cid2 == pal_id
            m2, d2 = ((1.0, 0.0) if is_pal or not pal_id
                      else ((1.10, -55.0) if pal_id < 20000
                            else (1.50, -60.0)))
            a = sum(g.get(f, 0) for f in
                    ("<Speed>k__BackingField", "<Stamina>k__BackingField",
                     "<Power>k__BackingField", "<Guts>k__BackingField",
                     "<Wiz>k__BackingField"))
            b = sum(m2 * (2130.0 + ent["axis"] + d + d2)
                    for d in dxs) * U[2] * t2m
            if b > 0:
                fac_acc[(ent["cmd"], bucket)].append(a / b)
    t_dice_fac: dict = {}
    for (cmd_id, bucket), v in fac_acc.items():
        if len(v) >= 30:
            r_ = round(_med(v), 4)
            if abs(r_ - 1) >= 0.005:
                t_dice_fac.setdefault(str(cmd_id), {})[bucket] = r_

    # Events recentering (2026-09-07): the composed events prediction
    # (bare-census base + trainee delta + card events + race slope) runs
    # systematically LOW - +46 URA / +309 Unity-dice / +238 GL / +93 TB
    # median SP. Measure the residual line resid = a + b*(opt*rmul) per
    # scenario bucket (Unity split pre/post-dice) over the full corpus
    # and bake it as events adjustments; the model adds a to the base
    # and b to the per-race slope.
    import importlib.util as _ilu
    _cspec = _ilu.spec_from_file_location(
        "career", here / "../../../uma-it-web/uma_it_web/enrich/career.py")
    _career = _ilu.module_from_spec(_cspec)
    import sys as _sys
    _sys.modules["career"] = _career
    _cspec.loader.exec_module(_career)

    def _min_races(tr: int, scen: int) -> int:
        if scen == 4:
            return 4
        objs = _career.objectives_for(str(tr))
        if not objs:
            return 9
        tset = {o.get("Turn") for o in objs
                if _career.race_by_name(o.get("ObjectiveName") or "")}
        return len(tset) + 1 + 3

    STATF = ("<Speed>k__BackingField", "<Stamina>k__BackingField",
             "<Power>k__BackingField", "<Guts>k__BackingField",
             "<Wiz>k__BackingField")
    adj_acc: dict = defaultdict(lambda: ([], [], []))  # x, rsp, rst
    for p_ in sorted(args.runs.glob("*/*.json")):
        parts_ = p_.stem.split("_")
        if len(parts_) < 3 or not parts_[2].startswith("uma"):
            continue
        try:
            raw = json.loads(p_.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = (raw.get("SingleModeChara") or [{}])[0]
        scen = int(ch.get("scenario_id") or 0)
        if str(scen) not in ev_base:
            continue
        races = len(raw.get("RaceHistory") or [])
        if not races:
            continue
        gi = raw.get("GainInfo") or []
        if not gi:
            continue
        ev = gi[0]
        tr = int(parts_[2][3:]) if parts_[2][3:].isdigit() else 0
        deck = {int(e.get("support_card_id") or 0):
                (int(e.get("exp") or 0), int(e.get("limit_break_count") or 0))
                for e in ch.get("support_card_array") or []}
        if not deck:
            continue
        opt = max(0, races - _min_races(tr, scen))
        rmul = 1.0
        cev_sp = cev_st = 0.0
        for cid2, el in deck.items():
            lv2 = masters.level_from_exp(cid2, *el)
            if lv2:
                rmul += race_bonus(cid2, lv2) / 100
            ce = (card_ev.get(str(cid2)) or {}).get(str(scen))
            if ce:
                cev_sp += ce[0]
                cev_st += ce[1]
        td = ((trainees.get(str(tr)) or {}).get("d") or {}).get(str(scen))             or {"sp": 0, "st": 0}
        e_ = events.get(str(scen)) or {}
        per_sp = e_.get("race_sp") or 40
        per_st = e_.get("race_st") or 8
        x = opt * rmul
        pred_sp = (ev_base[str(scen)]["sp"] + td["sp"] + cev_sp + per_sp * x)
        pred_st = (ev_base[str(scen)]["st"] + td["st"] + cev_st + per_st * x)
        key = "2d" if (scen == 2 and races > 21) else str(scen)
        xs_, rsp_, rst_ = adj_acc[key]
        xs_.append(x)
        rsp_.append(ev.get("<SkillPoint>k__BackingField", 0) - pred_sp)
        rst_.append(sum(ev.get(f, 0) for f in STATF) - pred_st)
    ev_adj: dict = {}
    for key, (xs_, rsp_, rst_) in adj_acc.items():
        if len(xs_) < 50:
            continue
        mx = sum(xs_) / len(xs_)
        vx = sum((x - mx) ** 2 for x in xs_) or 1.0
        row = {}
        for tag, ys_ in (("sp", rsp_), ("st", rst_)):
            my = sum(ys_) / len(ys_)
            b_ = sum((x - mx) * (y - my)
                     for x, y in zip(xs_, ys_)) / vx
            row[f"{tag}_a"] = round(my - b_ * mx, 1)
            row[f"{tag}_b"] = round(b_, 2)
        ev_adj[key] = row

    out = {
        "meta": {"runs": len(runs), "cells": len(cards),
                 "model": "it-formula 2026-08-13 post-recalibration"},
        "constants": {
            "u": {str(k): v for k, v in U.items()},
            "ura_c": [URA_C_BASE, URA_C_SLOPE, URA_C_HALFWIDTH],
            "c": {"2": 2130.0, "3": 1825.0, "4": 3400.0},
            "t": {str(k): v for k, v in T_POINTS.items()},
            "t_dice": t_dice,
            "t_dice_fac": t_dice_fac,
            "sp_k": {str(k): v for k, v in SP_K.items()},
        },
        "cards": cards,
        "cold": cold,
        "priors": {"dx": priors, "w": priors_w},
        "events": events,
        "insp": insp,
        "presets": presets,
        "card_ev": card_ev,
        "ev_base": ev_base,
        "ev_adj": ev_adj,
        "trainees": trainees,
        "level_exp": level_exp,
        "lb_caps": {"1": [20, 25, 30, 35, 40], "2": [25, 30, 35, 40, 45],
                    "3": [30, 35, 40, 45, 50]},
    }
    args.out.write_text(json.dumps(out, separators=(",", ":")),
                        encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB, "
          f"{len(cards)} covered + {len(cold)} cold cells, {len(runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

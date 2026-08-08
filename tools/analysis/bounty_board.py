"""Bounty board: which runs would actually move the formula forward.

Every bounty below targets a specific unresolved question, and the fill
status is computed from the live corpus rather than tracked by hand — so
re-running this after an upload batch shows what is still open.

Race-count reality (matters for every spec here): the trainee's mandatory
schedule sets a FLOOR of 9 races for URA, Unity Cup and Our Grand Concert
— some trainees floor at 10, 11 or 12. Only Trackblazer can go below 9.
Race count is controllable UPWARD by entering optional races, so a spec
asks for a target and the runner reports what actually happened.

Usage:
    python bounty_board.py --runs <dir> --mdb <master.mdb>
    python bounty_board.py --runs <dir> --mdb <master.mdb> --format md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from it_formula import Masters, PAL_BY_SCENARIO, STAT_FIELDS

SCEN = {1: "URA", 2: "Unity Cup", 3: "Our Grand Concert", 4: "Trackblazer"}
RACE_FLOOR = {1: 9, 2: 9, 3: 9, 4: 4}
LADDER = [9, 15, 25, 35]          # achievable everywhere; 9 is the usual floor


# ── bounties ──────────────────────────────────────────────────────────
# `check` returns (filled, total_needed, note) given the loaded corpus.
BOUNTIES: list[dict] = [
    dict(
        id="B1", priority=0, title="Matched pal / no-pal pairs",
        why="A pal swings base by ~1.5x (16 vs 24 measured on one card), and "
            "859 of 1074 runs contain one — so most community data cannot be "
            "used by the formula at all. There is currently NOT ONE matched "
            "pair in any scenario. This is the single highest-value gap.",
        spec="Pick 5 trainer cards. Run A: those 5 + the scenario pal. "
             "Run B: those 5 + any 6th trainer card. Same scenario, same "
             "race count, same trainee. Repeat in Unity Cup and Our Grand "
             "Concert (Trackblazer has no pal).",
        needed=6, scenarios=[2, 3], races="any, but identical within a pair",
        predicts="The 5 shared cards keep the same axis ordering; only the "
                 "run scalar g moves. If the pal instead changes cards "
                 "unequally, the pal is not a simple multiplier.",
    ),
    dict(
        id="B2", priority=0, title="Race-count ladder, pal-free, one deck",
        why="The excess-over-base ratio is currently measured with race count "
            "pooled, so we cannot tell a card defect from a turn effect. This "
            "is the direct blocker on a deterministic engine.",
        spec=f"One fixed deck, one scenario, no pal, at races {LADDER}. "
             "Same trainee throughout if possible.",
        needed=4, scenarios=[1, 2, 3, 4], races=str(LADDER),
        predicts="base falls as u*(N-k); if excess/base stays flat across the "
                 "ladder, excess shares the same turn scaling and the engine "
                 "reduces to one scalar per run.",
    ),
    dict(
        id="B3", priority=1, title="URA ladder — URA has NO multi-race deck",
        why="No deck has ever been run at 3+ race counts in URA, so the turn "
            "offset k cannot be tested there at all.",
        spec=f"One deck, URA, no pal, at races {LADDER}.",
        needed=4, scenarios=[1], races=str(LADDER),
        predicts="k=1..3 as elsewhere. URA is the scenario whose fitted u is "
                 "highest, so it should show the offset most clearly.",
    ),
    dict(
        id="B4", priority=1, title="Unity ladder — Unity refuses the offset",
        why="g=u*(N-k) improves URA, Our Grand Concert and Trackblazer but "
            "gains NOTHING in Unity Cup. Either k is per-scenario or two of "
            "those gains are fitted noise.",
        spec=f"One deck, Unity Cup, no pal, at races {LADDER}.",
        needed=4, scenarios=[2], races=str(LADDER),
        predicts="If Unity genuinely has k=0 the ladder will fit u*N exactly "
                 "while the others need the offset.",
    ),
    dict(
        id="B5", priority=1, title="Same deck in URA and Our Grand Concert",
        why="URA wants mood weight >=4.70 and Our Grand Concert <=4.65 — but "
            "those came from DIFFERENT decks, so the conflict is confounded "
            "with deck composition. One deck in both removes it entirely.",
        spec="One deck, no pal, 9 races, run in URA and in Our Grand Concert.",
        needed=2, scenarios=[1, 3], races="9 (both)",
        predicts="Both fit at wMood=5 with their own constants. If they still "
                 "disagree with the deck held fixed, the weight is genuinely "
                 "per-scenario — which no current model allows.",
    ),
    dict(
        id="B6", priority=1, title="Our Grand Concert constant (C=1825 vs 2050)",
        why="Fitting cannot separate them (both accept 14/17 cells) but "
            "prediction can: C=2050 lifts held-out accuracy from 58.5% to "
            "75.6%. Needs pal-free spread, and only 33 pal-free OGC runs exist.",
        spec=f"Any pal-free Our Grand Concert runs, spread across "
             f"{LADDER}. Deck variety is fine — quantity and spread matter.",
        needed=10, scenarios=[3], races=str(LADDER),
        predicts="C=2050 with k=2 beats C=1825 with k=0 on new data.",
    ),
    dict(
        id="B7", priority=2, title="Wit-card decks at a controlled race count",
        why="Every non-compliant card group skews to Wit (20015, 20012, 30010, "
            "20016). Wit training is mechanically different — no energy cost, "
            "plus effect type 31 'wit energy recovery'.",
        spec="Decks with 2-3 Wit cards, no pal, at a FIXED race count "
             "(9 preferred), several different Wit cards across runs.",
        needed=8, scenarios=[2, 3, 4], races="9 (fixed)",
        predicts="With race count fixed, the Wit spread drops below 5% — "
                 "meaning it was a turn effect, not a card defect.",
    ),
    dict(
        id="B8", priority=2, title="Wit cards in URA",
        why="URA has 24 runs with zero Wit cards and only 4 with one. The Wit "
            "question cannot be checked in the scenario that otherwise fits "
            "best.",
        spec="URA, no pal, at least 2 Wit cards, 9 races.",
        needed=4, scenarios=[1], races="9",
        predicts="URA Wit cards behave like the others once N is controlled.",
    ),
    dict(
        id="B9", priority=2, title="One deck across 3+ scenarios, same races",
        why="Only 7 (deck, race count) cells have ever been run in 2+ "
            "scenarios, and the scenario constants rest on them. This is also "
            "the clean test of whether g is shared across scenarios.",
        spec="One deck, no pal, 9 races, run in as many scenarios as you can "
             "(ideally all four).",
        needed=4, scenarios=[1, 2, 3, 4], races="9 (identical)",
        predicts="The per-card gap between any two scenarios is FLAT — it was "
                 "exactly 10/9/6 at 9/15/35 races on the one deck we have.",
    ),
    dict(
        id="B10", priority=2, title="Team Sirius / group cards",
        why="Group cards are suspected of distorting deck totals. Heirs to the "
            "Throne was cleared (87.3% vs 88.3%), but Team Sirius has ZERO "
            "runs — it is restricted in half the scenarios.",
        spec="Any deck containing Team Sirius [Passing the Dream On] in a "
             "scenario that allows it, no pal, 9 races.",
        needed=3, scenarios=[1, 2, 3, 4], races="9",
        predicts="No distortion of the other cards, same as Heirs.",
    ),
    dict(
        id="B11", priority=3, title="Card level: lv1 vs max-for-limit-break",
        why="A probe deck with two lv1 R cards fits only at lv1-4, while an "
            "in-game screenshot shows LB0 R cards displaying as Lvl 20. "
            "Directly contradictory and still unresolved.",
        spec="A deck with 2-3 DELIBERATELY UNLEVELLED cards (lv1, never fed) "
             "alongside known cards. No pal, 9 races, any scenario.",
        needed=3, scenarios=[1, 2, 3, 4], races="9",
        predicts="Bases match the card's ACTUAL level, not the LB cap.",
    ),
    dict(
        id="B12", priority=3, title="The one impossible pair: 20035 vs 20040",
        why="In 861 ordering facts exactly one is impossible: 20035 [Turf as "
            "Nails] (mood 45) scored 34 while 20040 [Hot Hearts and Cool "
            "Drinks] (mood 50) scored 33, same TE. Strictly dominated yet "
            "higher. One observation, never reproduced.",
        spec="Both 20035 and 20040 in the same deck, no pal, any scenario, "
             "9 races. Two runs to confirm reproducibility.",
        needed=2, scenarios=[1, 2, 3, 4], races="9",
        predicts="20040 >= 20035. If 20035 wins again, one of the two cards "
                 "has a mis-decoded bonus.",
    ),
    dict(
        id="B13", priority=3, title="Facility-level conditional cards (type 111)",
        why="FACILITY_LEVEL is hardcoded to 4 for 'per facility level' "
            "uniques, but facility level CHANGES during a run and "
            "idle_single_mode_training_cut says max is 5.",
        spec="A deck containing [Sentimental Flare ♪] Maruzensky (30107) or "
             "another type-111 card, no pal, at races 9 AND 35 (facility "
             "level should differ between short and long runs).",
        needed=4, scenarios=[2, 3, 4], races="9 and 35",
        predicts="If the effective facility level differs between 9 and 35 "
                 "races, the fixed 4 is wrong and the term is turn-dependent.",
    ),
]


def load_corpus(runs_dir: Path, masters: Masters) -> list[dict]:
    out = []
    for path in sorted(runs_dir.glob("*/*.json")) + sorted(runs_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        chara = (raw.get("SingleModeChara") or [None])[0]
        if not chara:
            continue
        scen = int(chara.get("scenario_id") or 0)
        pals = PAL_BY_SCENARIO.get(scen, set())
        deck = {}
        for c in chara.get("support_card_array") or []:
            cid = int(c.get("support_card_id") or 0)
            lv = masters.level_from_exp(cid, int(c.get("exp") or 0),
                                        int(c.get("limit_break_count") or 0))
            deck[cid] = lv
        out.append(dict(
            scen=scen, races=len(raw.get("RaceHistory") or []),
            pal=bool(pals & set(deck)), ids=set(deck),
            deck=tuple(sorted((k, v) for k, v in deck.items() if v)),
            file=path.name,
        ))
    return out


def evaluate(corpus: list[dict], wit_cards: set[int]) -> dict[str, tuple[int, str]]:
    """Fill counts per bounty, computed from the corpus."""
    res: dict[str, tuple[int, str]] = {}

    # B1: a matched pair is deck_B (pal-free) containing every non-pal card of
    # deck_A plus exactly one replacement, at the same scenario and races.
    n = 0
    for scen in (2, 3):
        pals = PAL_BY_SCENARIO.get(scen, set())
        free = [r for r in corpus if r["scen"] == scen and not r["pal"]]
        for r in corpus:
            if r["scen"] != scen or not r["pal"]:
                continue
            stripped = {x for x in r["deck"] if x[0] not in pals}
            for f in free:
                if f["races"] != r["races"]:
                    continue
                other = set(f["deck"])
                if stripped <= other and len(other) == len(stripped) + 1:
                    n += 1
                    break
    res["B1"] = (n, "matched pairs found")

    # ladders: race counts covered by a single pal-free deck, per scenario
    byd = defaultdict(lambda: defaultdict(set))
    for r in corpus:
        if not r["pal"]:
            byd[r["deck"]][r["scen"]].add(r["races"])
    per_scen = {}
    for sc in byd.values():
        for s, rcs in sc.items():
            per_scen[s] = max(per_scen.get(s, 0), len(rcs))
    res["B2"] = (min((per_scen.get(s, 0) for s in (1, 2, 3, 4)), default=0),
                 "race counts on the best deck of the WORST-covered scenario")
    res["B3"] = (per_scen.get(1, 0), "race counts on the best URA deck")
    res["B4"] = (per_scen.get(2, 0), "race counts on the best Unity deck")

    # Wit coverage
    res["B7"] = (sum(1 for r in corpus if not r["pal"]
                     and len(r["ids"] & wit_cards) >= 2),
                 "pal-free runs with 2+ Wit cards")
    res["B8"] = (sum(1 for r in corpus if not r["pal"] and r["scen"] == 1
                     and len(r["ids"] & wit_cards) >= 2),
                 "pal-free URA runs with 2+ Wit cards")
    res["B11"] = (sum(1 for r in corpus if not r["pal"]
                      and sum(1 for _, lv in r["deck"] if lv and lv <= 5) >= 2),
                  "pal-free runs with 2+ cards at level <=5")

    # B5 / B9 cross-scenario
    byd2 = defaultdict(lambda: defaultdict(set))
    for r in corpus:
        if not r["pal"]:
            byd2[r["deck"]][r["races"]].add(r["scen"])
    both15 = sum(1 for d, byrc in byd2.items() for rc, ss in byrc.items()
                 if {1, 3} <= ss)
    multi = max((len(ss) for byrc in byd2.values() for ss in byrc.values()),
                default=0)
    res["B5"] = (both15, "URA+OGC cells on one deck at one race count")
    res["B9"] = (multi, "scenarios covered by one deck at one race count")

    res["B6"] = (sum(1 for r in corpus if r["scen"] == 3 and not r["pal"]),
                 "pal-free Our Grand Concert runs")
    res["B10"] = (sum(1 for r in corpus if 30081 in r["ids"]),
                  "runs containing Team Sirius")
    res["B12"] = (sum(1 for r in corpus
                      if {20035, 20040} <= r["ids"] and not r["pal"]),
                  "runs with both cards")
    res["B13"] = (sum(1 for r in corpus if 30107 in r["ids"] and not r["pal"]),
                  "pal-free runs with a type-111 card")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--format", choices=("text", "md"), default="text")
    args = ap.parse_args()

    masters = Masters(args.mdb)
    corpus = load_corpus(args.runs, masters)
    import sqlite3
    db = sqlite3.connect(f"file:{args.mdb}?mode=ro", uri=True)
    wit = {int(c) for c, t in db.execute(
        "SELECT id, command_id FROM support_card_data") if int(t) == 106}
    db.close()
    fills = evaluate(corpus, wit)

    if args.format == "md":
        print("# IT formula bounty board\n")
        print(f"_{len(corpus)} runs in the corpus "
              f"({sum(1 for r in corpus if not r['pal'])} pal-free)._\n")
        print("Race floor is **9** for URA / Unity Cup / Our Grand Concert "
              "(some trainees 10-12). Only Trackblazer goes lower.\n")
    else:
        print(f"{len(corpus)} runs "
              f"({sum(1 for r in corpus if not r['pal'])} pal-free)\n")

    for b in sorted(BOUNTIES, key=lambda x: (x["priority"], x["id"])):
        have, note = fills.get(b["id"], (0, ""))
        tag = ["CRITICAL", "HIGH", "MEDIUM", "LOW"][b["priority"]]
        if args.format == "md":
            print(f"## {b['id']} — {b['title']}  `{tag}`\n")
            print(f"**Why.** {b['why']}\n")
            print(f"**Run this.** {b['spec']}\n")
            print(f"- Runs wanted: **{b['needed']}**")
            print(f"- Scenarios: {', '.join(SCEN[s] for s in b['scenarios'])}")
            print(f"- Races: {b['races']}")
            print(f"- Have now: {have} {note}")
            print(f"- Registered prediction: {b['predicts']}\n")
        else:
            print(f"[{tag:>8}] {b['id']} {b['title']}")
            print(f"           want {b['needed']}, have {have} ({note})")
            print(f"           {b['spec']}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

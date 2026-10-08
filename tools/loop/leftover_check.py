"""Are a scenario's small event-hint shares a real source? scenario_hints.py
measures, per scenario and skill group, how often the receipt's Events bucket
has the hint in runs where neither the trainee nor a deck card could give it
through events. The companion's setup model drops shares under 20% (spark.ts
MIN_SCENARIO: "likely common events"); the loop simulation keeps them. Kept
is right if they are stable and don't depend on the deck; if some card's
presence moves them, that card's events give it and the card lists miss it.

Predictions, written before the first run (2026-10-08):
  P1 time: for shares of 5-20% with >= 300 eligible runs in each half (runs in
     upload order), the two halves differ by <= 3 points in >= 90% of them.
  P2 deck: no card present in >= 150 eligible runs and absent in >= 150 moves
     such a share by more than 10 points.
If both hold, both models count every measured share.

Result (2026-10-08, 23,706 receipts): P1 holds, 142 of 156 shares (91%)
within 3 points between halves; P2 fails, 68 card-skill pairs move a share by
more than 10 points (Grand Concert, one group: 42% with card 30017, 3.9%
without). The small shares are partly cards' events missing from the card
event lists, so neither keeping nor dropping them is right; both models drop
them for now (MIN_SCENARIO 0.2). To do: credit those events to the cards
(gen_card_hints.py) and count only the deck-free share.

    python leftover_check.py --receipts <runs dir> --master master.mdb
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
WEB = HERE / "../../../uma-it-web/uma_it_web/enrich/data"


def load(path: str) -> dict:
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--master", required=True)
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.master}?mode=ro", uri=True)
    group = dict(db.execute("select id, group_id from skill_data"))
    cards = {int(k): {group.get(s) for s in v}
             for k, v in json.loads((WEB / "card_event_skills.json").read_text())["cards"].items()}
    trainees = {}
    for k, t in json.loads((WEB / "trainee_events.json").read_text())["trainees"].items():
        ids = set(t["event_skills"]) | {s for e in t["events"] for s, _ in e["skills"]}
        trainees[int(k)] = {group.get(s) for s in ids}
    runs = []
    for path in sorted(glob.glob(f"{args.receipts}/*/*.json*"), key=os.path.getmtime):
        try:
            d = load(path)
            chara = d["SingleModeChara"][0]
            events = d["GainInfo"][0]
            deck = [sc["<SupportCardId>k__BackingField"] for sc in d["SupportCardGainInfo"]]
        except (KeyError, IndexError, TypeError, ValueError, OSError, EOFError):
            continue
        others = trainees.get(chara["card_id"], set()).union(*(cards.get(c, set()) for c in deck))
        hinted = {h["group_id"] for h in events.get("<SkillTipsArray>k__BackingField") or []
                  if isinstance(h, dict) and "group_id" in h}
        runs.append((chara["scenario_id"], hinted, others, deck))
    print(f"{len(runs)} receipts read")
    by_scen = collections.defaultdict(list)
    for scen, hinted, others, deck in runs:
        by_scen[scen].append((hinted, others, deck))

    p1_n = p1_ok = 0
    p2_flags = []
    for scen, rs in sorted(by_scen.items()):
        groups = set().union(*(h for h, _, _ in rs))
        for g in groups:
            elig = [(g in h, deck) for h, o, deck in rs if g not in o]
            if len(elig) < 600:
                continue
            share = sum(x for x, _ in elig) / len(elig)
            if not 0.05 <= share < 0.20:
                continue
            half = len(elig) // 2
            a = sum(x for x, _ in elig[:half]) / half
            b = sum(x for x, _ in elig[half:]) / (len(elig) - half)
            p1_n += 1
            p1_ok += abs(a - b) <= 0.03
            print(f"scenario {scen} group {g}: share {share:.3f} ({len(elig)} runs); "
                  f"halves {a:.3f} / {b:.3f}")
            present = collections.Counter(c for _, deck in elig for c in set(deck))
            for c, n in present.items():
                if n < 150 or len(elig) - n < 150:
                    continue
                with_c = sum(x for x, deck in elig if c in deck) / n
                without = sum(x for x, deck in elig if c not in deck) / (len(elig) - n)
                if abs(with_c - without) > 0.10:
                    p2_flags.append((scen, g, c, n, with_c, without))
    print(f"\nP1: {p1_ok} of {p1_n} shares within 3 points between halves "
          f"({p1_ok / max(1, p1_n):.0%}; predicted >= 90%)")
    print(f"P2: {len(p2_flags)} card(s) moving a share by more than 10 points (predicted none)")
    for scen, g, c, n, w, wo in p2_flags:
        print(f"  scenario {scen} group {g}: card {c} in {n} runs: {w:.3f} with, {wo:.3f} without")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Card event-chain completion rates via chain-exclusive gold hints.

User's instrument (2026-09-05, Tachyon SSR Speed / 'Unstoppable'):
some cards grant a GOLD hint only at the final link of their event
chain, and receipts carry the trainee's accumulated hint tips as
(group_id, rarity). A gold group whose presence rate is ~0 in decks
WITHOUT the card and substantial WITH it is a chain-completion marker
- P(marker | card) IS the chain finish rate. Not every card has one
(the user's caveat); discovery below finds the ones that do.

Readings from the first corpus pass (proddb11, 8,929 runs):
- ~100% rows are NOT chains: MLB talent auto-grants the card's gold
  hint at career start (both pals, Sirius). Filter by eye or LB split.
- SR Kiryuin validates the method: 83% URA, 0% Unity/GL - pal events
  only fire in the pal's own scenario, matching the pal law.
- Chain rates are strongly scenario-dependent (Tachyon SSR Speed:
  URA 64 / Unity 44 / GL 27 / TB 24%).
- Friend/group cards RAISE other cards' completion (Tachyon in GL:
  0 friends 9% -> 3 friends 54%, monotone) - chains contest event
  slots against other trainer cards, not against friends.

Usage: python chain_rates.py --runs <dir> [--min-n 40]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

SCEN = {1: "URA", 2: "Unity", 3: "GL", 4: "TB"}


def collect(runs_dir: Path):
    out = []
    for p in sorted(runs_dir.glob("*/*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        chara = (raw.get("SingleModeChara") or [{}])[0]
        deck = frozenset(int(c.get("support_card_id") or 0)
                         for c in chara.get("support_card_array") or [])
        if not deck:
            continue
        golds = frozenset(t["group_id"] for t in chara.get("skill_tips_array") or []
                          if t.get("rarity") == 2 and t.get("group_id"))
        out.append((deck, golds, int(chara.get("scenario_id") or 0),
                    len(raw.get("RaceHistory") or [])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--max-bg", type=float, default=0.005)
    args = ap.parse_args()
    runs = collect(args.runs)
    print(f"{len(runs)} runs")

    # candidate (card, gold group) pairs: count co-occurrence
    with_card: dict = defaultdict(int)
    hit: dict = defaultdict(int)
    group_total: dict = defaultdict(int)
    cards_seen: set = set()
    for deck, golds, scen, races in runs:
        for g in golds:
            group_total[g] += 1
        for c in deck:
            cards_seen.add(c)
            with_card[c] += 1
            for g in golds:
                hit[(c, g)] += 1

    markers = []
    for (c, g), h in hit.items():
        n = with_card[c]
        if n < args.min_n or h < 3:
            continue
        bg_n = len(runs) - n
        bg_h = group_total[g] - h
        if bg_n and bg_h / bg_n <= args.max_bg and h / n >= 0.02:
            markers.append((c, g, h / n, h, n, bg_h, bg_n))

    # one marker per card: the highest-rate exclusive group
    best: dict = {}
    for c, g, rate, h, n, bg_h, bg_n in markers:
        if c not in best or best[c][2] < rate:
            best[c] = (c, g, rate, h, n, bg_h, bg_n)

    print(f"\n{len(best)} cards with a chain-exclusive gold marker "
          f"(bg <= {args.max_bg:.1%}, n >= {args.min_n}):")
    print(f"{'card':>6} {'group':>6} {'chain%':>7} {'n':>5} {'bg':>7}  per-scenario")
    for c, g, rate, h, n, bg_h, bg_n in sorted(best.values(), key=lambda x: -x[4]):
        per = defaultdict(lambda: [0, 0])
        for deck, golds, scen, races in runs:
            if c in deck:
                per[scen][1] += 1
                per[scen][0] += g in golds
        scen_s = "  ".join(f"{SCEN.get(s, s)} {100*a/b:.0f}% ({b})"
                           for s, (a, b) in sorted(per.items()) if b >= 10)
        print(f"{c:>6} {g:>6} {100*rate:>6.1f}% {n:>5} {bg_h}/{bg_n}  {scen_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

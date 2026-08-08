"""Find support cards that differ ONLY in training type.

Two cards carrying identical Friendship / Mood / Training Effectiveness at the
same limit break are a free controlled experiment: put both in one deck and any
difference in what they give is caused by the training type alone, with nothing
else to disentangle. This is the construction that settled the Friendship
weight (117 pairs, every one identical).

Group membership is stable across limit breaks — the same cards stay matched,
only the shared Mood value moves (R: 15 at LB0 up to 25 at MLB). So a player
can use whatever limit break they own, provided every card in the set sits at
the SAME one.

Cards carrying a conditional unique are flagged: they still work, but their
bonus can switch on partway through a run, so a clean set is preferable.

Usage:
    python matched_cards.py --mdb <master.mdb>
    python matched_cards.py --mdb <master.mdb> --json pools.json
    python matched_cards.py --mdb <master.mdb> --rarity SSR --min-types 3
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from it_formula import Masters, PAL_BY_SCENARIO

RARITY_NAME = {1: "R", 2: "SR", 3: "SSR"}
NAME_RARITY = {v: k for k, v in RARITY_NAME.items()}
# level cap per rarity for limit breaks 0..4
CAPS = {1: [20, 25, 30, 35, 40], 2: [25, 30, 35, 40, 45], 3: [30, 35, 40, 45, 50]}
COMMAND = {101: "Speed", 102: "Power", 103: "Guts", 105: "Stamina", 106: "Wit"}
ORDER = ["Speed", "Stamina", "Power", "Guts", "Wit"]


def build(mdb: Path) -> dict:
    masters = Masters(mdb)
    db = sqlite3.connect(f"file:{mdb}?mode=ro", uri=True)
    name = {i: t for i, t in db.execute(
        'SELECT "index", text FROM text_data WHERE category = 76')}
    chara = {i: t for i, t in db.execute(
        'SELECT "index", text FROM text_data WHERE category = 6')}
    rows = list(db.execute(
        "SELECT id, chara_id, rarity, command_id FROM support_card_data"))
    db.close()
    pals = set().union(*PAL_BY_SCENARIO.values())

    pools: dict[str, dict] = {}
    for rarity, caps in CAPS.items():
        for lb, cap in enumerate(caps):
            groups = defaultdict(list)
            for cid, ch, rar, cmd in rows:
                if rar != rarity or cid in pals or cmd not in COMMAND:
                    continue
                fb, mood, training, initial, conditional = masters.bonuses(cid, cap)
                groups[(mood, training)].append(dict(
                    id=cid, type=COMMAND[cmd], friendship=fb,
                    card=name.get(cid, "?"), chara=chara.get(ch, "?"),
                    conditional=bool(conditional),
                    initial_bonus=sum(initial),
                ))
            # Friendship is NOT part of the key: it measures 0 for this stat
            # channel (117 identical-profile pairs, every one identical), so
            # splitting on it would discard usable sets for no gain.
            for (mood, training), members in groups.items():
                if len({m["type"] for m in members}) < 2:
                    continue
                key = f"{RARITY_NAME[rarity]}-LB{lb}-mood{mood}-te{training}"
                pools[key] = dict(
                    rarity=RARITY_NAME[rarity], limit_break=lb, level=cap,
                    mood=mood, training=training,
                    types=sorted({m["type"] for m in members},
                                 key=ORDER.index),
                    members=sorted(members, key=lambda m: (ORDER.index(m["type"]),
                                                           m["id"])),
                )
    return pools


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mdb", type=Path, required=True)
    ap.add_argument("--json", type=Path, help="write the full pool list here")
    ap.add_argument("--rarity", choices=("R", "SR", "SSR"))
    ap.add_argument("--limit-break", type=int, default=4)
    ap.add_argument("--min-types", type=int, default=3)
    ap.add_argument("--clean-only", action="store_true",
                    help="exclude cards with a conditional unique")
    args = ap.parse_args()

    pools = build(args.mdb)
    if args.json:
        args.json.write_text(json.dumps(pools, indent=1, ensure_ascii=False))
        print(f"wrote {len(pools)} pools to {args.json}")

    shown = 0
    for key, pool in sorted(pools.items(),
                            key=lambda kv: (-len(kv[1]["types"]),
                                            -len(kv[1]["members"]))):
        if args.rarity and pool["rarity"] != args.rarity:
            continue
        if pool["limit_break"] != args.limit_break:
            continue
        members = [m for m in pool["members"]
                   if not (args.clean_only and m["conditional"])]
        types = {m["type"] for m in members}
        if len(types) < args.min_types:
            continue
        print(f"\n{pool['rarity']} at LB{pool['limit_break']} (lv{pool['level']})"
              f"  —  Mood {pool['mood']} / Training {pool['training']}"
              f"  ·  {len(members)} cards, {len(types)} types")
        by_type = defaultdict(list)
        for m in members:
            by_type[m["type"]].append(m)
        for t in ORDER:
            if t not in by_type:
                continue
            for m in by_type[t]:
                flags = []
                if m["conditional"]:
                    flags.append("conditional unique")
                if m["initial_bonus"]:
                    flags.append(f"+{m['initial_bonus']} initial")
                tail = f"   ({', '.join(flags)})" if flags else ""
                print(f"    {t:>8}  {m['id']:>6}  {m['card']} {m['chara']}{tail}")
        shown += 1
    if not shown:
        print("no pools matched those filters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

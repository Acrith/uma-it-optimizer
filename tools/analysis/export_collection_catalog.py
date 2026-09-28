"""Write uma-it-web's collection catalog from the GLOBAL client's master.mdb:
what exists in Global, for the collection page's "owned vs missing".

- trainees: every trainee card the global client knows, with its base
  aptitudes (card_rarity_data at the card's highest rarity; G..S = 1..8)
  in the order turf, dirt, sprint, mile, medium, long, front, pace, late,
  end;
- support_cards: every support card's release time (start_date, so a
  card announced ahead shows up by itself once it is out) and its title
  ("[Fire at My Heels]"; masters.json names the character only);
- saddles: every win saddle's name and type (3 = G1, 2 = G2, 1 = G3,
  0 = a title such as the Classic Triple Crown), for a veteran's wins.

The site's masters.json cannot answer this: its support cards are
patched from the JP reference data too (JP-ahead cards included).

Usage: python export_collection_catalog.py --global-mdb <master.mdb>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "../../../uma-it-web/uma_it_web/enrich/data/collection_catalog.json"
APTITUDES = ("proper_ground_turf", "proper_ground_dirt", "proper_distance_short",
             "proper_distance_mile", "proper_distance_middle", "proper_distance_long",
             "proper_running_style_nige", "proper_running_style_senko",
             "proper_running_style_sashi", "proper_running_style_oikomi")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-mdb", type=Path, required=True)
    args = ap.parse_args()
    db = sqlite3.connect(str(args.global_mdb))
    trainees = {}
    for (card,) in db.execute("select id from card_data order by id"):
        row = db.execute(f"select {', '.join(APTITUDES)} from card_rarity_data"
                         " where card_id = ? order by rarity desc limit 1", (card,)).fetchone()
        if row:
            trainees[str(card)] = list(row)
    supports = {str(i): [d, title or ""] for i, d, title in db.execute(
        "select s.id, s.start_date, t.text from support_card_data s left join text_data t"
        " on t.category = 76 and t.\"index\" = s.id order by s.id")}
    saddles = {str(i): [name, kind] for i, kind, name in db.execute(
        "select s.id, s.win_saddle_type, t.text from single_mode_wins_saddle s"
        " join text_data t on t.category = 111 and t.\"index\" = s.id order by s.id")}
    out = {
        "_meta": {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                  "source_mtime": datetime.fromtimestamp(args.global_mdb.stat().st_mtime, UTC)
                  .isoformat(timespec="seconds"),
                  "aptitude_order": ["turf", "dirt", "sprint", "mile", "medium", "long",
                                     "front", "pace", "late", "end"]},
        "trainees": trainees,
        "support_cards": supports,
        "saddles": saddles,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(trainees)} trainees, {len(supports)} support cards, {len(saddles)} saddles"
          f" -> {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

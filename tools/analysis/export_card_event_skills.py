"""Write uma-it-web's card event skills: per support card, the skills its
events can hint (white and gold), next to the training hints the site
takes from master.mdb (`card_hint_skills`).

The game's master data has no such list (the events live in the story
assets), so the source is GameTora's per-card page data, kept as a
snapshot in references/gametora_events_<date>/ (`itemData.event_skills`,
a superset of the `sk` rewards in its event data). Checked against 8,928
site receipts on 2026-09-28: a card's event hints are credited to the
receipt's Events bucket, and these lists explain ~92% of its golds that
are not scenario golds. The file shape is the site's contract, so a source
of our own (the story assets) can replace this one later.

    python export_card_event_skills.py [--global-mdb master.mdb]

With the Global master.mdb it lists the released cards the snapshot lacks
(a refresh of those pages is due).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOT = HERE / "../../references/gametora_events_2026-09-05"
OUT = HERE / "../../../uma-it-web/uma_it_web/enrich/data/card_event_skills.json"
SOURCE = "https://gametora.com/umamusume/supports"


def read(snapshot: Path) -> dict[str, list[int]]:
    cards = {}
    for path in sorted(snapshot.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))["pageProps"]["itemData"]
        skills = sorted({int(s) for s in item.get("event_skills") or []})
        if skills:
            cards[str(item["support_id"])] = skills
    return cards


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-mdb", type=Path, help="lists released cards the snapshot lacks")
    args = ap.parse_args()
    cards = read(SNAPSHOT)
    out = {"_meta": {"source": SOURCE, "snapshot": SNAPSHOT.resolve().name.rsplit("_", 1)[-1],
                     "exported_at": datetime.now(UTC).isoformat(timespec="seconds")},
           "cards": cards}
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(cards)} cards with event skills -> {OUT.resolve()}")
    if args.global_mdb:
        db = sqlite3.connect(f"file:{args.global_mdb}?mode=ro", uri=True)
        released = [i for i, s in db.execute("select id, start_date from support_card_data")
                    if s <= time.time()]
        have = {int(p.stem) for p in SNAPSHOT.glob("*.json") if p.stem.isdigit()}
        missing = sorted(set(released) - have)
        print(f"released in Global: {len(released)}, "
              f"missing from the snapshot: {missing or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

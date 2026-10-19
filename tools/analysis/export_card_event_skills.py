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

`event_names`: per card, skill id -> the events whose choices give it (their
English names in GameTora's event data; the current version, not its
`history`), for the companion's Setup to name the event behind an EVENT mark
(owner, 2026-10-19). A choice gives a skill as a hint (`sk`), the skill
itself (`sg`) or one of a list (`sr`).

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


def event_names(event_data: str) -> dict[str, list[str]]:
    """Skill id -> the names of the events whose choices give it, in GameTora's order."""
    out: dict[str, list[str]] = {}
    for events in json.loads(event_data or "{}").values():
        for e in events if isinstance(events, list) else []:
            for choice in e.get("c") or []:
                for r in choice.get("r") or []:
                    d = r.get("d")
                    if r.get("t") in ("sk", "sg") and isinstance(d, int):
                        ids = [d]
                    elif r.get("t") == "sr" and isinstance(d, list):
                        ids = [x["d"] for x in d
                               if isinstance(x, dict) and isinstance(x.get("d"), int)]
                    else:
                        continue
                    for i in ids:
                        if e.get("n") and e["n"] not in out.setdefault(str(i), []):
                            out[str(i)].append(e["n"])
    return out


def read(snapshot: Path) -> tuple[dict[str, list[int]], dict[str, dict[str, list[str]]]]:
    cards, names = {}, {}
    for path in sorted(snapshot.glob("*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))["pageProps"]
        item = page["itemData"]
        skills = sorted({int(s) for s in item.get("event_skills") or []})
        if skills:
            cards[str(item["support_id"])] = skills
            found = event_names((page.get("eventData") or {}).get("en", ""))
            if mine := {str(s): found[str(s)] for s in skills if found.get(str(s))}:
                names[str(item["support_id"])] = mine
    return cards, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-mdb", type=Path, help="lists released cards the snapshot lacks")
    args = ap.parse_args()
    cards, names = read(SNAPSHOT)
    out = {"_meta": {"source": SOURCE, "snapshot": SNAPSHOT.resolve().name.rsplit("_", 1)[-1],
                     "exported_at": datetime.now(UTC).isoformat(timespec="seconds")},
           "cards": cards, "event_names": names}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    unnamed = sum(1 for c, v in cards.items() for s in v if str(s) not in names.get(c, {}))
    print(f"{len(cards)} cards with event skills ({unnamed} skills without an event name)"
          f" -> {OUT.resolve()}")
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

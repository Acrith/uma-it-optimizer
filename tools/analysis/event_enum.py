"""Parse GameTora per-card event data into enumerated payout totals.

references/gametora_events_2026-09-05/<id>.json (raw _next/data pulls)
-> per card: chain (arrows) link count and top-option SUCCESS totals,
plus random-event top-option totals. 'Top option' = first choice (the
community's presumed IT rule); 'success' = rewards before the first
'di' divider. Values like '+1/+3' take the first number.

Usage: python event_enum.py            # writes event_enum.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RAW = Path(__file__).parent / "../../references/gametora_events_2026-09-05"
STATS = {"sp": "speed", "st": "stamina", "po": "power", "gu": "guts", "in": "wiz"}


def _num(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"[+-]?\d+", str(v or "").split("/")[0])
    return int(m.group(0)) if m else 0


def _totals(rewards: list[dict]) -> dict:
    out = {"sp_total": 0, "pt": 0, "energy": 0, "mood": 0, "skills": []}
    for r in rewards:
        t = r.get("t")
        if t == "di":
            break                      # success segment only
        v = _num(r.get("v", ""))
        if t in STATS:
            out["sp_total"] += v       # stat mass (all five summed)
        elif t == "pt":
            out["pt"] += v
        elif t == "en":
            out["energy"] += v
        elif t == "mo":
            out["mood"] += v
        elif t == "sk":
            out["skills"].append((r.get("d"), _num(r.get("v", ""))))
    return out


def parse_card(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        ev = d["pageProps"].get("eventData") or {}
        blob = ev.get("en") or ev.get("ja")
        if not blob:
            return None
        data = json.loads(blob)
    except Exception:
        return None
    chain = {"links": 0, "stats": 0, "pt": 0, "energy": 0, "mood": 0, "skills": []}
    for link in data.get("arrows") or []:
        choices = link.get("c") or []
        if not choices:
            continue
        top = _totals(choices[0].get("r") or [])
        chain["links"] += 1
        chain["stats"] += top["sp_total"]
        chain["pt"] += top["pt"]
        chain["energy"] += top["energy"]
        chain["mood"] += top["mood"]
        chain["skills"] += top["skills"]
    rnd = {"events": 0, "stats": 0, "pt": 0}
    for e in data.get("random") or []:
        choices = e.get("c") or []
        if not choices:
            continue
        top = _totals(choices[0].get("r") or [])
        rnd["events"] += 1
        rnd["stats"] += top["sp_total"]
        rnd["pt"] += top["pt"]
    return {"chain": chain, "random": rnd}


def main() -> int:
    out = {}
    for p in sorted(RAW.glob("*.json")):
        row = parse_card(p)
        if row:
            out[p.stem] = row
    dst = Path(__file__).parent / "event_enum.json"
    dst.write_text(json.dumps(out, indent=0))
    n_chain = sum(1 for v in out.values() if v["chain"]["links"])
    print(f"{len(out)} cards parsed; {n_chain} with chains -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

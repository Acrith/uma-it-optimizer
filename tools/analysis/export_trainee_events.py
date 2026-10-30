"""Write uma-it-web's trainee events: per trainee card, the skills its events
can hint, and the events that hint a skill only when their conditions are met
(secret events: races to win), with those conditions as races.

Source: the GameTora trainee snapshot (fetch_gametora_trainees.py),
`itemData.skills_event` and `eventData.en`. A condition that names races
becomes race requirements, each `[race_instance_id, year]` (year 1-3, or
null for any year the race runs):

- `win X` (or `[X]`), `win_all [..]`, `race_w2 X` (the race in Classic and
  Senior), and the named sets (triple_crown, triple_tiara,
  spring_triple_crown, autumn_triple_crown_senior): every race, rule "all";
- `win_or a b`: rule "any"; `win_n_of n [..]`: rule "n", with `n`;
- `participate X`: entered, not won ("enter").

Other conditions (dates, strategies, rivals, fan counts...) are kept as they
are under `other`: the event may still happen, but a plan cannot aim for it.

Goal wins: winning one of her career goals hints one skill (one level), on
the race's win event. GameTora lists few of them; ours are in
goal_win_hints.json (imported once from a community sheet on
2026-10-30, each checked against the IT runs, with the evidence). Every
outfit of hers gets the high-confidence ones as an event (kind "goal_win"),
unless one of its GameTora events already hints that skill.

    python export_trainee_events.py [--snapshot DIR] --global-mdb master.mdb
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOT = HERE / "../../references/gametora_trainees_2026-10-21"
GOAL_WINS = HERE / "goal_win_hints.json"
OUT = HERE / "../../../uma-it-web/uma_it_web/enrich/data/trainee_events.json"
SOURCE = "https://gametora.com/umamusume/characters"
# Named race sets: [race_instance_id, year]. Satsuki Sho, Japanese Derby,
# Kikuka Sho; Oka Sho, Japanese Oaks, Shuka Sho; Osaka Hai, Tenno Sho
# (Spring), Takarazuka Kinen; Tenno Sho (Autumn), Japan Cup, Arima Kinen.
SETS = {
    "triple_crown": [[100501, 2], [101001, 2], [101501, 2]],
    "triple_tiara": [[100401, 2], [100901, 2], [101401, 2]],
    "spring_triple_crown": [[100301, 3], [100601, 3], [101201, 3]],
    "autumn_triple_crown_senior": [[101601, 3], [101901, 3], [102301, 3]],
}


def race_ref(x) -> list[int | None] | None:
    """`301801` or `"102301|3"` -> [race_instance_id, year or None]."""
    base, _, year = str(x).partition("|")
    if not (base.isdigit() and len(base) == 6):
        return None
    return [int(base), int(year) if year.isdigit() else None]


def refs(xs) -> list:
    out = []
    for x in xs if isinstance(xs, list) else [xs]:
        out.extend(refs(x) if isinstance(x, list) else [r for r in [race_ref(x)] if r])
    return out


def requirement(cond: list) -> dict | None:
    """One condition as a race requirement, or None when it names no races."""
    kind, args = cond[0], cond[1:]
    if kind in ("win", "win_all"):
        races = refs(args)
        return {"rule": "all", "races": races} if races else None
    if kind == "race_w2":
        return {"rule": "all", "races": [[r[0], y] for r in refs(args) for y in (2, 3)]}
    if kind == "win_or":
        return {"rule": "any", "races": refs(args)}
    if kind == "win_n_of" and args and isinstance(args[0], int):
        return {"rule": "n", "n": args[0], "races": refs(args[1:])}
    if kind == "participate":
        return {"rule": "enter", "races": refs(args)}
    if kind in SETS:
        return {"rule": "all", "races": [list(r) for r in SETS[kind]]}
    return None


def skills_of(event: dict) -> list[list[int]]:
    """[[skill id, hint levels], ...] from any of the event's outcomes."""
    out = []
    for choice in event.get("c") or []:
        for r in choice.get("r") or []:
            if r.get("t") == "sk" and isinstance(r.get("d"), int):
                lv = str(r.get("v") or "+1").lstrip("+").split("/")[0]
                out.append([r["d"], int(lv) if lv.isdigit() else 1])
    return out


def goal_wins(path: Path) -> dict[int, list[dict]]:
    """The high-confidence goal wins as events, per character id."""
    events: dict[int, list[dict]] = {}
    for h in json.loads(path.read_text(encoding="utf-8"))["hints"]:
        if h["confidence"] == "high":
            events.setdefault(h["chara"], []).append({
                "name": f"Goal win: {h['race']}", "kind": "goal_win", "skills": [[h["skill"], 1]],
                "needs": [{"rule": h["rule"], "races": h["races"]}], "other": []})
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    ap.add_argument("--global-mdb", type=Path, required=True, help="to check every race exists")
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.global_mdb}?mode=ro", uri=True)
    known = {ri for (ri,) in db.execute("select id from race_instance")}
    group = dict(db.execute("select id, group_id from skill_data"))
    goals = goal_wins(GOAL_WINS)
    trainees = {}
    unplanned = added = 0
    on_gametora: set[int] = set()
    for path in sorted(args.snapshot.glob("*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))
        item = page["itemData"]
        events = []
        for kind, evs in json.loads((page.get("eventData") or {}).get("en") or "{}").items():
            for e in evs if isinstance(evs, list) else []:
                if not isinstance(e, dict) or not e.get("conditions"):
                    continue
                skills = skills_of(e)
                if not skills:
                    continue
                needs, other = [], []
                for cond in e["conditions"]:
                    req = requirement(cond)
                    (needs if req else other).append(req or cond)
                unplanned += not needs
                events.append({"name": e.get("n", ""), "kind": kind, "skills": skills,
                               "needs": needs, "other": other})
        listed = {group.get(s) for e in events for s, _ in e["skills"]}
        for e in goals.get(int(item["card_id"]) // 100, []):
            if group.get(e["skills"][0][0]) in listed:
                on_gametora.add(int(item["card_id"]) // 100)
            else:
                events.append(e)
                added += 1
        event_skills = {int(x) for x in item.get("skills_event") or [] if str(x).isdigit()}
        trainees[str(item["card_id"])] = {"event_skills": sorted(event_skills),
                                          "events": events}
    out = {"_meta": {"source": SOURCE, "snapshot": args.snapshot.resolve().name.rsplit("_", 1)[-1],
                     "exported_at": datetime.now(UTC).isoformat(timespec="seconds")},
           "trainees": trainees}
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text + "\n", encoding="utf-8")
    n_events = sum(len(t["events"]) for t in trainees.values())
    needed = {r[0] for t in trainees.values() for e in t["events"]
              for n in e["needs"] for r in n["races"]}
    unknown = needed - known
    if unknown:
        print(f"races not in the master data: {sorted(unknown)}")
    print(f"{len(trainees)} trainees, {n_events} conditional events with a skill hint "
          f"({unplanned} with no race to plan) -> {OUT.resolve()}")
    print(f"goal wins: {added} events on {len(goals)} characters' outfits "
          f"({len(on_gametora)} characters have one as a GameTora event)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

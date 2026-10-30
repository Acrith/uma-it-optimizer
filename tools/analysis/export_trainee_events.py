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
the race's win event. GameTora lists few of them (12 of the 66 rows for
trainees on Global, 2026-10-30). They come from the community sheet
"Umamusume Guarantee Career Hint" (mostly from umamusume.wikiru.jp;
GOAL_WINS_SOURCE, saved as CSV beside the snapshots).
Each row's race is matched among her goals in the game's master
(single_mode_route_race), which gives the race instance and its year; every
outfit of hers gets the event (kind "goal_win"), unless one of its GameTora
events already hints that skill.

    python export_trainee_events.py [--snapshot DIR] [--goal-wins CSV] --global-mdb master.mdb
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOT = HERE / "../../references/gametora_trainees_2026-10-21"
GOAL_WINS = HERE / "../../references/goal_win_hints_2026-10-30.csv"
OUT = HERE / "../../../uma-it-web/uma_it_web/enrich/data/trainee_events.json"
SOURCE = "https://gametora.com/umamusume/characters"
GOAL_WINS_SOURCE = "https://docs.google.com/spreadsheets/d/1g2Ld4hV5A9yInIfq0X0QE0KLX-CXKDSN9Btp1kmkXKM"

# Sheet rows the IT runs contradict (2026-10-30, 69,133 Global runs: runs
# that won the race whose events gave the hint), left out.
GOAL_WINS_LEFT_OUT = {
    "Zenno Rob Roy": "34% of 50",
    "Tosen Jordan": "36% of 25",
    "Aston Machan": "44% of 210",
}
# The sheet's spellings that differ from the game's.
SKILL_FIX = {"rishing heat": "rising heat", "eaget": "eager",
             "competitive spirt": "competitive spirit", "nimble nav": "nimble navigator"}
CHARA_FIX = {"tm opera o": "t m opera o", "victoira pisa": "victoire pisa"}
RACE_FIX = {"spring tenno sho": "tenno sho spring", "autumn tenno sho": "tenno sho autumn",
            "m c nambu hai": "mile championship nambu hai", "nhk mile": "nhk mile cup"}
# A name's mark, best first: the plain white (○) is the skill a hint opens.
MARKS = {"○": 0, "": 1, "◎": 2, "×": 3}

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


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def goal_wins(db: sqlite3.Connection, path: Path) -> tuple[dict, dict, dict]:
    """The sheet's goal-win hints as events, per character id; the rows left
    out with why; the skill names matched loosely, to the game's name."""

    def text(cat: int) -> dict[int, str]:
        return dict(db.execute("select [index], text from text_data where category=?", (cat,)))

    charas = {norm(t): i for i, t in text(6).items()}
    skills: dict[str, list[tuple]] = {}
    for sid, rarity, name in db.execute(
            "select s.id, s.rarity, t.text from skill_data s"
            " join text_data t on t.category=47 and t.[index]=s.id"):
        skills.setdefault(norm(name), []).append((rarity, MARKS.get(name[-1:], 1), sid))
    race_names = text(32)
    # A goal names a program, or a race group (single_mode_race_group: the
    # JBC races, run at a different course each year).
    goals: dict[int, list[tuple[int, int, str]]] = {}
    for chara, turn, instance, race in db.execute(
            "select r.chara_id, g.turn, p.race_instance_id, i.race_id from single_mode_route r"
            " join single_mode_route_race g on g.race_set_id = r.race_set_id"
            " left join single_mode_race_group rg on rg.race_group_id = g.condition_id"
            " join single_mode_program p on p.id = coalesce(rg.race_program_id, g.condition_id)"
            " join race_instance i on i.id = p.race_instance_id"
            " where r.scenario_id = 0 and g.condition_type = 1 and g.turn <= 72"):
        year = (turn - 1) // 24 + 1
        goals.setdefault(chara, []).append((instance, year, race_names.get(race, "")))
    events: dict[int, list[dict]] = {}
    left: dict[str, str] = {}
    loose: dict[str, str] = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        who, hint = row["Uma"].strip(), row["Guarantee Hint"].strip()
        race = row["Career Race"].strip()
        if not who or not race or hint.lower() == "nothing":
            continue
        chara = charas.get(CHARA_FIX.get(norm(who), norm(who)))
        if chara is None or chara not in goals:
            left[who] = "no trainee on Global"
            continue
        if who in GOAL_WINS_LEFT_OUT:
            left[who] = GOAL_WINS_LEFT_OUT[who]
            continue
        k = SKILL_FIX.get(norm(hint), norm(hint))
        if k not in skills:
            k = next(iter(difflib.get_close_matches(k, skills, n=1, cutoff=0.85)), None)
            loose[f"{who}: {hint}"] = k or ""
        m = re.match(r"^Y([123])\s+(.*)$", race)
        year, want = (int(m.group(1)), m.group(2)) if m else (None, race)
        want = f" {RACE_FIX.get(norm(want), norm(want))} "
        mine = [(g, f" {norm(g[2])} ") for g in goals[chara] if year in (None, g[1])]
        found = ([g for g, n in mine if n == want]
                 or [g for g, n in mine if want in n or n in want])
        if k is None or len({(g[1], g[2]) for g in found}) != 1:
            left[who] = (f"skill {hint!r} not found" if k is None
                         else f"{race!r}: {len(found)} of her goals match")
            continue
        races = sorted([instance, y] for instance, y, _ in found)
        events.setdefault(chara, []).append({
            "name": f"Goal win: {found[0][2]}", "kind": "goal_win",
            "skills": [[min(skills[k])[2], 1]],
            "needs": [{"rule": "any" if len(races) > 1 else "all", "races": races}],
            "other": []})
    return events, left, loose


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    ap.add_argument("--goal-wins", type=Path, default=GOAL_WINS)
    ap.add_argument("--global-mdb", type=Path, required=True,
                    help="her goals and the game's names, for the goal wins; every race exists")
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.global_mdb}?mode=ro", uri=True)
    known = {ri for (ri,) in db.execute("select id from race_instance")}
    group = dict(db.execute("select id, group_id from skill_data"))
    goals, left, loose = goal_wins(db, args.goal_wins)
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
                     "goal_wins": GOAL_WINS_SOURCE, "goal_wins_file": args.goal_wins.name,
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
    print(f"goal wins: {len(goals)} characters, {added} events added to their outfits, "
          f"{len(on_gametora)} characters have it as a GameTora event")
    absent = "no trainee on Global"
    print("  left out: " + "; ".join(f"{who} ({why})" for who, why in sorted(left.items())
                                     if why != absent))
    print(f"  {absent}: {sum(why == absent for why in left.values())} rows")
    print("  skill names matched loosely: "
          + "; ".join(f"{k} -> {v or '?'}" for k, v in sorted(loose.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

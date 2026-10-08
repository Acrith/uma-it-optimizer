"""Agenda that maximises the child's race affinity with its two parents.

    python schedule.py --master master.mdb --account account.json --rental rental.json \\
        --names names.json --parent-rank-score N --trainee CARD_ID [--match both|rental|own]

Every G1 win the child shares with a parent is +3 affinity when the child
is a parent later (+6 when both parents won it). Objectives are always run
and never put at risk (must-wins stay at 100%+, top 3/5 at 80%+);
optional G1s are chosen turn by turn to maximise the expected value
(value x win chance), a tie going to the rental's race (it stays in the
lineage while the own parent leaves it), with win chances from the IT table by aptitude and
races in a row. Aptitudes: the trainee's base raised by the lineage's pinks
at the start (loopdata.start_aptitudes).
"""
from __future__ import annotations

import argparse
import functools
import json
import math

from loopdata import Data, load_account, own_veterans, trainee_events, win_chance

YEARS = ["Junior", "Classic", "Senior"]
DEFAULT_TARGETS = "Racing Spirit: Stamina,Uma Stan,Nimble Navigator,Pedal to the Metal,Racing Spirit: Power"
# How much a race an event needs won outweighs affinity: log(win chance)
# times this, so the plan keeps those races out of streaks first.
EVENT_WEIGHT = 30


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("master", "account", "rental", "names"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--parent-rank-score", type=int, required=True, help="the own parent, by rank score")
    ap.add_argument("--trainee", type=int, required=True, help="trainee card id")
    ap.add_argument("--match", choices=["both", "rental", "own"], default="both")
    ap.add_argument("--targets", default=DEFAULT_TARGETS,
                    help="skills whose hints the trainee's events should be planned for")
    ap.add_argument("--no-events", action="store_true", help="plan for affinity only")
    ap.add_argument("--no-dirt", action="store_true",
                    help="no optional dirt G1s (a trainee far from dirt A: coin-flip wins and no Dirt spark)")
    args = ap.parse_args()
    data, acct = Data(args.master, args.names), load_account(args.account)
    db = data.db
    own = data.veteran(next(v for v in own_veterans(acct) if v["_rankScore"] == args.parent_rank_score))
    rental = data.rental(json.load(open(args.rental, encoding="utf-8")))

    # A G1 by its win saddle's group: one run at another venue (the JBC
    # Classic's four) is the same G1, as affinity.py counts it.
    g1_saddle, g1_of_race = {}, {}
    for sid, group, rid in db.execute(
            "select s.id, s.group_id, ri.race_id from single_mode_wins_saddle s join race_instance ri on ri.id=s.race_instance_id_1"
            " join race r on r.id=ri.race_id where s.race_instance_id_2=0 and r.grade=100"):
        g1_saddle[sid], g1_of_race[rid] = group, group

    def g1_races(uma):
        return {g1_saddle[sid] for sid in uma.wins if sid in g1_saddle}

    own_w = g1_races(own) if args.match in ("both", "own") else set()
    ren_w = g1_races(rental) if args.match in ("both", "rental") else set()
    apt = data.start_aptitudes(args.trainee, own, rental)

    def dist_grade(m):
        return apt["short"] if m <= 1400 else apt["mile"] if m <= 1800 else apt["medium"] if m <= 2400 else apt["long"]

    def chance(ground, m, row):
        return win_chance(apt["turf"] if ground == 1 else apt["dirt"], dist_grade(m), row)

    def value(rid):
        g = g1_of_race.get(rid)
        return (3 if g in own_w else 0) + (3 if g in ren_w else 0)

    # On a tie, the rental's race: a lender borrowed every generation stays in
    # the lineage, the own parent leaves it within two. Too small to outweigh
    # any real difference in expected value.
    def pref(rid):
        return value(rid) + (0.001 if g1_of_race.get(rid) in ren_w else 0)

    name = lambda rid: (db.execute('select text from text_data where category=32 and "index"=?', (rid,)).fetchone() or ["?"])[0]
    turn = lambda year, month, half: (year - 1) * 24 + (month - 1) * 2 + half
    race_of = ("select r.id, cs.ground, cs.distance from single_mode_program p join race_instance ri on ri.id=p.race_instance_id"
               " join race r on r.id=ri.race_id join race_course_set cs on cs.id=r.course_set where p.id=?")

    # Objectives of the trainee's route (the scenario's finals excluded).
    race_set = db.execute("select race_set_id from single_mode_route where chara_id=? and scenario_id=0",
                          (args.trainee // 100,)).fetchone()[0]
    objectives, need_place = {}, {}
    for t, pid, top in db.execute("select turn, condition_id, condition_value_1 from single_mode_route_race"
                                  " where race_set_id=? and condition_id < 10000 order by sort_id", (race_set,)):
        # Two races on one turn (Oaks or Derby): the game sets the first as
        # the goal, and IT does not let the player swap it.
        if t in objectives:
            continue
        objectives[t] = db.execute(race_of, (pid,)).fetchone()
        need_place[t] = top  # finish at least this place (0: just run it)
    # Optional G1s by turn (race_permission: 1 junior, 2 classic, 3 classic+senior, 4 senior).
    options: dict[int, list] = {}
    for perm, mo, half, rid, ground, m in db.execute(
            "select p.race_permission, p.month, p.half, r.id, cs.ground, cs.distance from single_mode_program p"
            " join race_instance ri on ri.id=p.race_instance_id join race r on r.id=ri.race_id"
            " join race_course_set cs on cs.id=r.course_set where r.grade=100 and p.base_program_id=0"):
        if not value(rid) or (args.no_dirt and ground == 2):
            continue
        for year in {1: [1], 2: [2], 3: [2, 3], 4: [3]}[perm]:
            t = turn(year, mo, half)
            if t not in objectives:
                options.setdefault(t, []).append((rid, ground, m))

    # Races the trainee's own events need, when the event hints a target
    # (trainee_events.json): each must be entered, and won unless the event
    # only asks for an entry. Found by turn: an objective on that turn with
    # the same race covers it; any other race there makes the event
    # impossible.
    required: dict[int, tuple] = {}
    planned, skipped = [], []
    targets = {data.group(t.strip()) for t in args.targets.split(",")}
    by_program = ("select race_permission, month, half from single_mode_program"
                  " where race_instance_id = ? and base_program_id = 0")
    for e in [] if args.no_events else trainee_events(args.trainee):
        if not data.skill_groups(s for s, _ in e["skills"]) & targets:
            continue
        if e["other"] or not e["needs"] or any(n["rule"] not in ("all", "enter") for n in e["needs"]):
            skipped.append(e)
            continue
        plan, ok = [], True
        for need in e["needs"]:
            for ri, year in need["races"]:
                rid, ground, m, _ = data.race(ri)
                turns = [turn(y, mo, h) for perm, mo, h in db.execute(by_program, (ri,))
                         for y in {1: [1], 2: [2], 3: [2, 3], 4: [3]}[perm] if year in (None, y)]
                t = next((t for t in turns if objectives.get(t, (None,))[0] == rid), turns[0] if turns else None)
                if t is None or (t in objectives and objectives[t][0] != rid) \
                        or (t in required and required[t][0] != rid):
                    ok = False
                    break
                plan.append((t, rid, ground, m, need["rule"] == "all"))
            if not ok:
                break
        if not ok:
            skipped.append(e)
            continue
        planned.append((e, plan))
        for t, rid, ground, m, win in plan:
            win = win or (t in required and required[t][3])
            required[t] = (rid, ground, m, win)

    def plan(required):
        @functools.lru_cache(None)
        def best(t, row, used):
            """(score, picks): affinity value x win chance, plus, for a race an
            event needs won, EVENT_WEIGHT x log(win chance), so the plan first
            keeps those races out of long streaks."""
            if t > 72:
                return 0.0, ()
            need = required.get(t)
            event = EVENT_WEIGHT * math.log(max(1, min(100, chance(need[1], need[2], row + 1))) / 100) \
                if need and need[3] else 0.0
            if t in objectives:
                rid, ground, m = objectives[t]
                # Never put an objective at risk: a must-win needs a sure win
                # (100%+), a top 3/5 at least 80%. Failing one may end the run.
                floor = 100 if need_place[t] == 1 else 80 if need_place[t] else 0
                if chance(ground, m, row + 1) < floor:
                    return float("-inf"), ()
                v, rest = best(t + 1, row + 1, used | {rid})
                gain = 0 if rid in used else pref(rid) * min(chance(ground, m, row + 1), 100) / 100
                return v + gain + event, ((t, rid, ground, m, "objective"),) + rest
            if need:
                rid, ground, m, _ = need
                v, rest = best(t + 1, row + 1, used | {rid})
                gain = 0 if rid in used else pref(rid) * min(chance(ground, m, row + 1), 100) / 100
                return v + gain + event, ((t, rid, ground, m, "event"),) + rest
            choices = [best(t + 1, 0, used)]
            for rid, ground, m in options.get(t, []):
                if rid in used:
                    continue
                v, rest = best(t + 1, row + 1, used | {rid})
                choices.append((v + pref(rid) * min(chance(ground, m, row + 1), 100) / 100,
                                ((t, rid, ground, m, f"+{value(rid)}"),) + rest))
            return max(choices, key=lambda c: c[0])

        _, picks = best(1, 0, frozenset())
        rows, row, prev = {}, 0, None
        for t, *_ in picks:
            row = row + 1 if prev == t - 1 else 1
            prev = t
            rows[t] = row
        seen, expected = set(), 0.0
        for t, rid, ground, m, _ in picks:
            if rid not in seen:
                expected += value(rid) * min(chance(ground, m, rows[t]), 100) / 100
                seen.add(rid)
        return picks, rows, expected

    picks, rows, expected = plan(required)
    print(f"trainee {data.name(args.trainee)} · starts turf {apt['turf']} dirt {apt['dirt']} short {apt['short']} "
          f"mile {apt['mile']} medium {apt['medium']} long {apt['long']} · matching {args.match}\n")
    # A G1 counts once: its saddle is the same the second time (a goal or an
    # event can make her run it twice).
    most, won = 0, set()
    for t, rid, ground, m, why in picks:
        y, rem = divmod(t - 1, 24)
        mo, h = divmod(rem, 2)
        v = 0 if rid in won else value(rid)
        again = rid in won and value(rid) > 0
        won.add(rid)
        most += v
        print(f"{YEARS[y]:<7} {mo + 1:>2}/{'early' if h == 0 else 'late ':<5} {name(rid):<30} {'dirt' if ground == 2 else 'turf'} "
              f"{m}m  in a row {rows[t]}  win ~{chance(ground, m, rows[t])}%  {why}"
              f"{f' (+{v})' if v and why in ('objective', 'event') else ''}{' (again: no affinity)' if again else ''}"
              f"{'  *event' if t in required and why == 'objective' else ''}")
    print(f"\nchild's race affinity from these G1s: up to +{most}, expected ~+{expected:.0f}")
    skill = lambda sid: (db.execute('select text from text_data where category=47 and "index"=?', (sid,)).fetchone() or ["?"])[0]
    for e, races in planned:
        p = math.prod(min(chance(g, m, rows[t]), 100) / 100 for t, _, g, m, win in races if win)
        hints = ", ".join(f"{skill(s)} +{lv}" for s, lv in e["skills"])
        print(f"event '{e['name']}' ({hints}): its {len(races)} races are in the plan; all won ~{p:.0%}")
    for e in skipped:
        hints = ", ".join(f"{skill(s)} +{lv}" for s, lv in e["skills"])
        print(f"event '{e['name']}' ({hints}): conditions a plan cannot aim for or cannot meet: {e['needs'] or e['other']}")
    if planned:
        _, _, without = plan({})
        print(f"(without these events the plan would expect ~+{without:.0f} affinity)")

if __name__ == "__main__":
    main()

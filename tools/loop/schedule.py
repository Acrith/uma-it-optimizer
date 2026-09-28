"""Agenda that maximises the child's race affinity with its two parents.

    python schedule.py --master master.mdb --account account.json --rental rental.json \\
        --names names.json --parent-rank-score N --trainee CARD_ID [--match both|rental|own]

Every G1 win the child shares with a parent is +3 affinity when the child
is a parent later (+6 when both parents won it). Objectives are always run;
optional G1s are chosen turn by turn to maximise the expected value
(value x win chance), with win chances from the IT table by aptitude and
races in a row. Aptitudes: the trainee's base raised by the lineage's pinks
at the start (loopdata.start_aptitudes).
"""
from __future__ import annotations

import argparse
import functools
import json

from loopdata import Data, load_account, own_veterans, win_chance

YEARS = ["Junior", "Classic", "Senior"]


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("master", "account", "rental", "names"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--parent-rank-score", type=int, required=True, help="the own parent, by rank score")
    ap.add_argument("--trainee", type=int, required=True, help="trainee card id")
    ap.add_argument("--match", choices=["both", "rental", "own"], default="both")
    args = ap.parse_args()
    data, acct = Data(args.master, args.names), load_account(args.account)
    db = data.db
    own = data.veteran(next(v for v in own_veterans(acct) if v["_rankScore"] == args.parent_rank_score))
    rental = data.rental(json.load(open(args.rental, encoding="utf-8")))

    def g1_races(uma):
        out = set()
        for sid in uma.wins:
            r = db.execute("select ri.race_id from single_mode_wins_saddle s join race_instance ri on ri.id=s.race_instance_id_1"
                           " join race r on r.id=ri.race_id where s.id=? and s.race_instance_id_2=0 and r.grade=100", (sid,)).fetchone()
            if r:
                out.add(r[0])
        return out

    own_w = g1_races(own) if args.match in ("both", "own") else set()
    ren_w = g1_races(rental) if args.match in ("both", "rental") else set()
    apt = data.start_aptitudes(args.trainee, own, rental)

    def dist_grade(m):
        return apt["short"] if m <= 1400 else apt["mile"] if m <= 1800 else apt["medium"] if m <= 2400 else apt["long"]

    def chance(ground, m, row):
        return win_chance(apt["turf"] if ground == 1 else apt["dirt"], dist_grade(m), row)

    def value(rid):
        return (3 if rid in own_w else 0) + (3 if rid in ren_w else 0)

    name = lambda rid: (db.execute('select text from text_data where category=32 and "index"=?', (rid,)).fetchone() or ["?"])[0]
    turn = lambda year, month, half: (year - 1) * 24 + (month - 1) * 2 + half
    race_of = ("select r.id, cs.ground, cs.distance from single_mode_program p join race_instance ri on ri.id=p.race_instance_id"
               " join race r on r.id=ri.race_id join race_course_set cs on cs.id=r.course_set where p.id=?")

    # Objectives of the trainee's route (the scenario's finals excluded).
    race_set = db.execute("select race_set_id from single_mode_route where chara_id=? and scenario_id=0",
                          (args.trainee // 100,)).fetchone()[0]
    objectives = {}
    for t, pid in db.execute("select turn, condition_id from single_mode_route_race where race_set_id=? and condition_id < 10000", (race_set,)):
        objectives[t] = db.execute(race_of, (pid,)).fetchone()
    # Optional G1s by turn (race_permission: 1 junior, 2 classic, 3 classic+senior, 4 senior).
    options: dict[int, list] = {}
    for perm, mo, half, rid, ground, m in db.execute(
            "select p.race_permission, p.month, p.half, r.id, cs.ground, cs.distance from single_mode_program p"
            " join race_instance ri on ri.id=p.race_instance_id join race r on r.id=ri.race_id"
            " join race_course_set cs on cs.id=r.course_set where r.grade=100 and p.base_program_id=0"):
        if not value(rid):
            continue
        for year in {1: [1], 2: [2], 3: [2, 3], 4: [3]}[perm]:
            t = turn(year, mo, half)
            if t not in objectives:
                options.setdefault(t, []).append((rid, ground, m))

    @functools.lru_cache(None)
    def best(t, row, used):
        if t > 72:
            return 0.0, ()
        if t in objectives:
            rid, ground, m = objectives[t]
            v, rest = best(t + 1, row + 1, used | {rid})
            gain = 0 if rid in used else value(rid) * min(chance(ground, m, row + 1), 100) / 100
            return v + gain, ((t, rid, ground, m, "objective"),) + rest
        choices = [best(t + 1, 0, used)]
        for rid, ground, m in options.get(t, []):
            if rid in used:
                continue
            v, rest = best(t + 1, row + 1, used | {rid})
            choices.append((v + value(rid) * min(chance(ground, m, row + 1), 100) / 100,
                            ((t, rid, ground, m, f"+{value(rid)}"),) + rest))
        return max(choices, key=lambda c: c[0])

    expected, picks = best(1, 0, frozenset())
    print(f"trainee {data.name(args.trainee)} · starts turf {apt['turf']} dirt {apt['dirt']} short {apt['short']} "
          f"mile {apt['mile']} medium {apt['medium']} long {apt['long']} · matching {args.match}\n")
    row, prev, most = 0, None, 0
    for t, rid, ground, m, why in picks:
        row = row + 1 if prev == t - 1 else 1
        prev = t
        y, rem = divmod(t - 1, 24)
        mo, h = divmod(rem, 2)
        v = value(rid)
        most += v
        print(f"{YEARS[y]:<7} {mo + 1:>2}/{'early' if h == 0 else 'late ':<5} {name(rid):<30} {'dirt' if ground == 2 else 'turf'} "
              f"{m}m  in a row {row}  win ~{chance(ground, m, row)}%  {why}{f' (+{v})' if v and why == 'objective' else ''}")
    print(f"\nchild's race affinity from these G1s: up to +{most}, expected ~+{expected:.0f}")


if __name__ == "__main__":
    main()

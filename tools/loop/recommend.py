"""Rank own parent x rental x trainee for a set of target white sparks.

    python recommend.py --master master.mdb --account account.json \\
        --rental rental.json --names names.json [--top 6] [--targets "Uma Stan,..."]

Targets are the skills the trainee will buy, by name: a gold (It's On!) or
◎ counts toward its white's spark (Ramp Up) at the gold / ◎ rate.

For each own veteran and each owned trainee (no repeated character, no
inbreeding), per target: how many of the 6 ancestors carry its spark, the
chance to generate it at the end (linear between the loop guide's 0/6 and
6/6 values for the version bought), and the chance to get its hint from
inspiration (white 3/6/9% per ancestor per event x (1 + that ancestor's
affinity/100), grandparents included; measured by inspiration_rates.py), the
scenario's own events (scenario_hints.py, from site receipts: URA Finale
hints each Racing Spirit skill in about a third of its runs) and the
trainee's own events that need races won (trainee_events.json: all their
races won, each first in its streak at the trainee's starting aptitudes;
schedule.py plans them). Score = weight x generation x (0.5 + 0.5 x hint).
"""
from __future__ import annotations

import argparse
import json

from affinity import Affinity, symbol
from loopdata import RATES, Data, load_account, own_veterans, scenario_hint, trainee_events, win_chance

DEFAULT_TARGETS = {"Racing Spirit: Stamina": 3, "Racing Spirit: Power": 2, "Uma Stan": 1,
                   "Nimble Navigator": 1, "Pedal to the Metal": 1}
INSPIRATION = {1: 0.03, 2: 0.06, 3: 0.09}


def score(aff: dict, targets: dict[str, tuple[int, str]], other: dict[str, float] | None = None) -> tuple[float, dict]:
    """`targets`: spark name -> (weight, rate kind); `other`: spark name ->
    the chance its hint comes from somewhere else than inspiration."""
    per, total = {}, 0.0
    for s, (w, kind) in targets.items():
        k = sum(1 for m, _, _ in aff["members"] if s in m.sparks)
        base, full = RATES[kind]
        gen = base + (full - base) * k / 6
        miss = 1.0
        for m, a, f in aff["members"]:
            if s in m.sparks:
                miss *= (1 - INSPIRATION[m.sparks[s]] * (1 + a / 100) * f) ** 2
        miss *= 1 - (other or {}).get(s, 0.0)
        per[s] = (k, gen, 1 - miss)
        total += w * gen * (0.5 + 0.5 * (1 - miss))
    return total, per


def event_hint(data: Data, card: int, group: int, apt: dict[str, str]) -> float:
    """Chance the trainee's own events hint the skill group: of its events
    that need races won, the best one's chance to win them all, each race
    first in its streak (the plan keeps them there, schedule.py)."""
    best = 0.0
    for e in trainee_events(card):
        if group not in data.skill_groups(s for s, _ in e["skills"]):
            continue
        if e["other"] or not e["needs"] or any(n["rule"] not in ("all", "enter") for n in e["needs"]):
            continue
        p = 1.0
        for need in e["needs"]:
            for ri, _ in need["races"] if need["rule"] == "all" else []:
                _, ground, m, _ = data.race(ri)
                dist = apt["short"] if m <= 1400 else apt["mile"] if m <= 1800 else apt["medium"] if m <= 2400 else apt["long"]
                p *= min(win_chance(apt["turf"] if ground == 1 else apt["dirt"], dist, 1), 100) / 100
        best = max(best, p)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("master", "account", "rental", "names"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--targets",
                    help="comma-separated skills to buy (default: RS Stamina/Power + Big 4)")
    ap.add_argument("--min-turf-medium", default="B", help="trainee must start at least this on turf and medium")
    ap.add_argument("--scenario", type=int, default=1, help="the IT scenario (1 URA Finale): its own event hints")
    args = ap.parse_args()
    data, acct = Data(args.master, args.names), load_account(args.account)
    aff = Affinity(data)
    rental = data.rental(json.load(open(args.rental, encoding="utf-8")))
    wanted = {s.strip(): 1 for s in args.targets.split(",")} if args.targets else DEFAULT_TARGETS
    targets: dict[str, tuple[int, str]] = {}
    groups: dict[str, int] = {}
    for skill, w in wanted.items():
        spark, kind = data.target(skill)
        targets[spark] = (w, kind)
        groups[spark] = data.group(skill)
    rows = []
    for v in own_veterans(acct):
        p1 = data.veteran(v)
        for t in acct["trainees"]:
            card = t["<CardId>k__BackingField"]
            apt = data.start_aptitudes(card, p1, rental)
            if min("GFEDCBAS".index(apt["turf"]), "GFEDCBAS".index(apt["medium"])) < "GFEDCBAS".index(args.min_turf_medium):
                continue
            r = aff.evaluate(card, p1, rental)
            if not r or r["inbreed"]:
                continue
            other = {sp: 1 - (1 - scenario_hint(args.scenario, g)) * (1 - event_hint(data, card, g, apt))
                     for sp, g in groups.items()}
            s, per = score(r, targets, other)
            rows.append((s, v, card, r, per, apt))
    rows.sort(key=lambda x: -x[0])
    seen, shown = set(), 0
    print(f"rental: {data.name(rental.card)} (parents {', '.join(data.name(g.card) for g in rental.parents)})\n")
    for s, v, card, r, per, apt in rows:
        if v["_id"] in seen:
            continue
        seen.add(v["_id"])
        shown += 1
        print(f"#{shown} own parent {data.name(v['_cardId'])} (rank score {v['_rankScore']}; parents "
              f"{', '.join(data.name(g['<CardId>k__BackingField']) for g in v['lineage'] if g['_positionId'] in (10, 20))})")
        print(f"   trainee {data.name(card)} · affinity {r['total']} {symbol(r['total'])} (own side {r['p1']}, rental side {r['p2']})"
              f" · starts turf {apt['turf']} dirt {apt['dirt']} mile {apt['mile']} medium {apt['medium']} long {apt['long']}")
        def label(n: str) -> str:
            kind = targets[n][1]
            return n.replace("Racing Spirit: ", "RS ") + ("" if kind == "normal" else f" ({kind})")
        print("   " + " · ".join(
            f"{label(n)} {k}/6 gen {g:.0%} hint {h:.0%}" for n, (k, g, h) in per.items()))
        if shown >= args.top:
            break


if __name__ == "__main__":
    main()

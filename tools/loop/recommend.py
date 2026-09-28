"""Rank own parent x rental x trainee for a set of target white sparks.

    python recommend.py --master master.mdb --account account.json \\
        --rental rental.json --names names.json [--top 6] [--targets "Uma Stan,..."]

Targets are the skills the trainee will buy, by name: a gold (It's On!) or
◎ counts toward its white's spark (Ramp Up) at the gold / ◎ rate.

For each own veteran and each owned trainee (no repeated character, no
inbreeding), per target: how many of the 6 ancestors carry its spark, the
chance to generate it at the end (linear between the loop guide's 0/6 and
6/6 values for the version bought), and the chance to get its hint from
inspiration (white 3/6/9% per ancestor per event x (1 + affinity/100);
grandparents at half: an assumption). Score = weight x generation x
(0.5 + 0.5 x hint).
"""
from __future__ import annotations

import argparse
import json

from affinity import Affinity, symbol
from loopdata import RATES, Data, load_account, own_veterans

DEFAULT_TARGETS = {"Racing Spirit: Stamina": 3, "Racing Spirit: Power": 2, "Uma Stan": 1,
                   "Nimble Navigator": 1, "Pedal to the Metal": 1}
INSPIRATION = {1: 0.03, 2: 0.06, 3: 0.09}


def score(aff: dict, targets: dict[str, tuple[int, str]]) -> tuple[float, dict]:
    """`targets`: spark name -> (weight, rate kind)."""
    per, total = {}, 0.0
    for s, (w, kind) in targets.items():
        k = sum(1 for m, _, _ in aff["members"] if s in m.sparks)
        base, full = RATES[kind]
        gen = base + (full - base) * k / 6
        miss = 1.0
        for m, a, f in aff["members"]:
            if s in m.sparks:
                miss *= (1 - INSPIRATION[m.sparks[s]] * (1 + a / 100) * f) ** 2
        per[s] = (k, gen, 1 - miss)
        total += w * gen * (0.5 + 0.5 * (1 - miss))
    return total, per


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ("master", "account", "rental", "names"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--targets",
                    help="comma-separated skills to buy (default: RS Stamina/Power + Big 4)")
    ap.add_argument("--min-turf-medium", default="B", help="trainee must start at least this on turf and medium")
    args = ap.parse_args()
    data, acct = Data(args.master, args.names), load_account(args.account)
    aff = Affinity(data)
    rental = data.rental(json.load(open(args.rental, encoding="utf-8")))
    wanted = {s.strip(): 1 for s in args.targets.split(",")} if args.targets else DEFAULT_TARGETS
    targets: dict[str, tuple[int, str]] = {}
    for skill, w in wanted.items():
        spark, kind = data.target(skill)
        targets[spark] = (w, kind)
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
            s, per = score(r, targets)
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

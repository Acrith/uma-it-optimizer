"""How often a scenario's own events hint a skill, measured on site receipts.

A receipt's Events bucket holds every hint from events: the scenario's, the
trainee's and the deck cards'. Per scenario and skill group, this counts the
runs whose Events bucket has the hint, leaving out runs where the trainee or
a deck card could have given it through events (uma-it-web's
card_event_skills.json and trainee_events.json), so what remains is the
scenario's share. URA Finale hints every Racing Spirit skill in about a third
of its runs; the other scenarios never do.

    python scenario_hints.py --receipts runs/ --master master.mdb \\
        [--out data/scenario_event_hints.json]

Writes {scenario id: {"runs": n, "groups": {skill group: share}}}, shares of
at least MIN_SHARE with at least MIN_RUNS runs behind them.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
WEB = HERE / "../../../uma-it-web/uma_it_web/enrich/data"
MIN_SHARE = 0.03
MIN_RUNS = 50


def load(path: str) -> dict:
    with gzip.open(path) if path.endswith(".gz") else open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", type=Path, default=HERE / "data/scenario_event_hints.json")
    args = ap.parse_args()
    db = sqlite3.connect(f"file:{args.master}?mode=ro", uri=True)
    group = dict(db.execute("select id, group_id from skill_data"))
    cards = {int(k): {group.get(s) for s in v}
             for k, v in json.loads((WEB / "card_event_skills.json").read_text())["cards"].items()}
    trainees = {}
    for k, t in json.loads((WEB / "trainee_events.json").read_text())["trainees"].items():
        ids = set(t["event_skills"]) | {s for e in t["events"] for s, _ in e["skills"]}
        trainees[int(k)] = {group.get(s) for s in ids}
    by_scen: dict[int, list[tuple[set, set]]] = collections.defaultdict(list)
    for path in glob.glob(f"{args.receipts}/*/*.json*"):
        try:
            d = load(path)
            chara = d["SingleModeChara"][0]
            events = d["GainInfo"][0]
            deck = [sc["<SupportCardId>k__BackingField"] for sc in d["SupportCardGainInfo"]]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        others = trainees.get(chara["card_id"], set()).union(*(cards.get(c, set()) for c in deck))
        hinted = {h["group_id"] for h in events.get("<SkillTipsArray>k__BackingField") or []
                  if isinstance(h, dict) and "group_id" in h}
        by_scen[chara["scenario_id"]].append((hinted, others))
    runs = {scen: len(rs) for scen, rs in by_scen.items()}
    seen = collections.defaultdict(collections.Counter)
    eligible = collections.defaultdict(collections.Counter)
    for scen, rs in by_scen.items():
        groups = set().union(*(h for h, _ in rs))
        for hinted, others in rs:
            for g in groups - others:
                eligible[scen][g] += 1
                seen[scen][g] += g in hinted
    out = {}
    for scen, n in sorted(runs.items()):
        share = {g: seen[scen][g] / eligible[scen][g]
                 for g in seen[scen] if eligible[scen][g] >= MIN_RUNS}
        groups = {str(g): round(v, 3) for g, v in share.items() if v >= MIN_SHARE}
        out[str(scen)] = {"runs": n, "groups": dict(sorted(groups.items()))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for scen, v in out.items():
        print(f"scenario {scen}: {v['runs']} runs, {len(v['groups'])} skill groups "
              "hinted by its events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generation check: every bought white skill (or gold/◎) that has a spark,
in each roll of a player's spark records (the companion's
spark_screens.jsonl and the runs' receipts), against base x 1.1^carriers;
which Racing Spirit got the "+" in each roll; the box's "+" sparks by
scenario.

    python calib_gen.py --data <the companion's data folder> --master <master.mdb>
"""
import argparse
import collections
import json
import sqlite3

from cli import COMPANION_DATA

ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
ap.add_argument("--data", required=True, help="the companion's data folder (Settings > Your data > Open data folder)")
ap.add_argument("--master", required=True, help="the game's master.mdb")
ap.add_argument("--names", default=str(COMPANION_DATA / "names.json"))
args = ap.parse_args()
D, M = args.data, args.master
db = sqlite3.connect(f"file:{M}?mode=ro", uri=True)
names = json.load(open(args.names, encoding="utf-8"))
F = names["factors"]
skill = {i: (g, r, gr) for i, g, r, gr in db.execute("select id, group_id, rarity, group_rate from skill_data")}
# group -> spark name (the factor whose effect hints a skill of that group)
spark_of_group = {}
for fg, v in db.execute("select factor_group_id, value_1 from succession_factor_effect where target_type = 41"):
    if v in skill:
        nm = F.get(str(fg * 100 + 1))
        if nm and nm[2] == 4:
            spark_of_group.setdefault(skill[v][0], nm[0])
def sparks(ids):
    out = {}
    for i in ids or []:
        f = F.get(str(i))
        if f: out[f[0]] = f[1]
    return out
recs, seen = [], set()
for l in open(f"{D}/spark_screens.jsonl"):
    r = json.loads(l)
    k = (r["card_id"], r["run_start"])
    if k in seen: continue
    seen.add(k); recs.append(r)
trials = []   # (version, carriers, sparked, plus, name)
for r in recs:
    rc = json.load(open(f"{D}/captures/sent/it.run/{r['run_file']}"))
    six = []
    for p in rc["Parents"]:
        six.append(sparks([f["<FactorId>k__BackingField"] for f in (p.get("<FactorDataArray>k__BackingField") or []) if f]))
        for g in ((p.get("<SuccessionCharaList>k__BackingField") or {}).get("_items") or []):
            if g and g.get("_positionId") in (10, 20):
                six.append(sparks([f["<FactorId>k__BackingField"] for f in (g.get("<FactorDataArray>k__BackingField") or []) if f]))
    assert len(six) == 6, len(six)
    # bought skills by group: the best version bought
    best = {}
    for sid, lvl in r["skills"]:
        if sid not in skill: continue
        g, rar, gr = skill[sid]
        if g not in spark_of_group: continue
        ver = "gold" if rar == 2 else "double" if gr == 2 else "normal"
        order = {"normal": 0, "double": 1, "gold": 2}
        if g not in best or order[ver] > order[best[g]]: best[g] = ver
    for roll in r["rolls"]:
        got = sparks(roll["factors"])
        for g, ver in best.items():
            nm = spark_of_group[g]
            k = sum(1 for a in six if nm in a)
            trials.append((ver, k, nm in got, f"{nm} +" in got, nm))
base = {"normal": 0.2, "double": 0.25, "gold": 0.4}
print(len(recs), "runs,", sum(len(r["rolls"]) for r in recs), "rolls,", len(trials), "trials (bought skill with a spark x roll)")
by = collections.defaultdict(lambda: [0, 0, 0.0])
for ver, k, s, plus, nm in trials:
    e = by[(ver, k)]; e[0] += 1; e[1] += s; e[2] += base[ver] * 1.1 ** k
tot = [0, 0, 0.0]
print(f"{'version':7} {'k':>2} {'n':>4} {'sparked':>8} {'expected':>8}")
for (ver, k), (n, s, ex) in sorted(by.items()):
    print(f"{ver:7} {k:>2} {n:>4} {s:>8} {ex:>8.1f}")
    tot[0] += n; tot[1] += s; tot[2] += ex
print(f"{'all':7} {'':>2} {tot[0]:>4} {tot[1]:>8} {tot[2]:>8.1f}")
plus = [(nm, s) for ver, k, s, p, nm in trials if p]
print("'+' replacing a bought skill's plain spark:", len(plus), plus)

print("\n--- per roll: Racing Spirits bought, and which got the '+' ---")
for r in recs:
    rs_bought = sorted({spark_of_group[skill[sid][0]] for sid, _ in r["skills"] if sid in skill and skill[sid][0] in spark_of_group and spark_of_group[skill[sid][0]].startswith("Racing Spirit")})
    for roll in r["rolls"]:
        got = sparks(roll["factors"])
        plus = [n for n in got if n.endswith(" +")]
        print(f"  {len(rs_bought)} RS bought {[x.split(': ')[1] for x in rs_bought]} -> '+' on {plus}")
# Whole box: URA (scenario 1) veterans and their '+' sparks
acct = json.load(open(f"{D}/account.json"))
ura = [v for v in acct["veterans"] if v.get("scenario_id") == 1]
cnt = collections.Counter(sum(1 for n in sparks(v["factors"]) if n.endswith(" +")) for v in ura)
other = collections.Counter(sum(1 for n in sparks(v["factors"]) if n.endswith(" +")) for v in acct["veterans"] if v.get("scenario_id") != 1)
print("\nbox: URA veterans by number of '+' sparks:", dict(sorted(cnt.items())), "of", len(ura))
print("box: other scenarios by number of '+':", dict(sorted(other.items())))
plus_names = collections.Counter(n for v in ura for n in sparks(v["factors"]) if n.endswith(" +"))
print("which '+':", plus_names.most_common())

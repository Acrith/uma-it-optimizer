"""A player's loop as a model: box, rental, trainees, the rules' constants.
The inputs are the player's local files, passed in (cli.py); nothing
personal is kept here."""
from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from affinity import Affinity  # noqa: E402
from loopdata import Data, Uma, scenario_hint, trainee_events, win_chance  # noqa: E402

TARGETS = ["Racing Spirit: Stamina", "Racing Spirit: Power", "Uma Stan", "Nimble Navigator", "Pedal to the Metal"]
RS_TARGETS = {"Racing Spirit: Stamina", "Racing Spirit: Power"}
INSP = {1: 0.03, 2: 0.06, 3: 0.09}
BASE = {"normal": 0.2, "double": 0.25, "gold": 0.4}
WHITE_STARS = (0.417, 0.53, 0.053)          # 1/2/3 stars, the test box's whites
TYPICAL = {"parent": 220, "grandparent": 63}  # the Sparks module's typical affinities

# Set by init(): the game's master data, the affinity model, the skills.
data: Data
aff: Affinity
GROUP: dict[str, int] = {}
_sk: dict = {}  # id -> [name, rarity, icon, group, rate]
own_skills: dict = {}
_files: dict[str, str] = {}

# The looping scenario (1 URA Finale, 2 Unity Cup, 3 Grand Concert): its own
# hints per target, and whether the Racing Spirit "+" applies (URA only).
SCENARIO = 1
SCEN: dict[str, float] = {}
PLUS_TAX = True
# Skill groups whose GOLD a scenario's own events hint in every run (site
# receipts, 1,768 of 1,768 Unity Cup runs): It's On! (Ramp Up) and No
# Stopping Me! (Nimble Navigator). Every trainee gets them there, so a
# trainee's own gold of either adds nothing in that scenario.
SCENARIO_GOLD_GROUPS = {2: {20046, 20049}}
SCEN_GOLD: dict[str, float] = {}


def init(master: str, names: str, account: str, rental: str, loop_data: str) -> None:
    """Load the inputs; before anything else of the simulation runs."""
    global data, aff
    data = Data(master, names)
    aff = Affinity(data)
    _sk.clear()
    _sk.update(json.load(open(names, encoding="utf-8"))["skills"])
    GROUP.clear()
    GROUP.update({t: data.group(t) for t in TARGETS})
    own_skills.clear()
    own_skills.update(json.load(open(loop_data, encoding="utf-8"))["own_skills"])
    _files.update(account=account, rental=rental, names=names)
    event_hint.cache_clear()


def own_of(card: int, potential: int) -> dict[str, str]:
    """Targets the trainee can buy without a hint: 'white' or 'gold'."""
    out = {}
    for sid, rank in own_skills.get(str(card), []):
        if rank > potential:
            continue
        e = _sk.get(str(sid))
        if not e:
            continue
        for t in TARGETS:
            if e[3] == GROUP[t]:
                out[t] = "gold" if e[1] >= 2 else out.get(t, "white")
    return out


@functools.lru_cache(None)
def event_hint(card: int, target: str, apt_key: tuple) -> float:
    """Chance her own events hint the target: all of an event's races won
    (each first in its streak) at her starting aptitudes."""
    apt = dict(apt_key)
    g = GROUP[target]
    best = 0.0
    for e in trainee_events(card):
        if g not in data.skill_groups(s for s, _ in e["skills"]):
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


def set_scenario(sc: int) -> None:
    """Switch the looping scenario: its own hints (and the golds it gives
    every run); the Racing Spirit "+" only in URA."""
    global SCENARIO, PLUS_TAX
    SCENARIO = sc
    SCEN.clear()
    SCEN.update({t: scenario_hint(sc, GROUP[t]) for t in TARGETS})
    SCEN_GOLD.clear()
    SCEN_GOLD.update({t: 1.0 for t in TARGETS if GROUP[t] in SCENARIO_GOLD_GROUPS.get(sc, set())})
    PLUS_TAX = sc == 1


def set_targets(targets: list[str]) -> None:
    """Change the targets (lineage.py tracks a longer list): in place, so
    every module that imported TARGETS sees it; the scenario's hints
    follow. Call set_scenario again after (sim.set_scenario does both)."""
    TARGETS[:] = list(targets)
    GROUP.clear()
    GROUP.update({t: data.group(t) for t in TARGETS})
    event_hint.cache_clear()


def names() -> dict:
    """The names file (labels for the reports)."""
    return json.load(open(_files["names"], encoding="utf-8"))


def load_box():
    """The player's veterans (with their parents) and trainees' potential,
    from the companion's account.json."""
    a = json.load(open(_files["account"], encoding="utf-8"))
    vets = []
    for v in a["veterans"]:
        ps = [Uma(g["card_id"], data.sparks(g["factors"]), g.get("wins") or []) for g in v["lineage"] if g["position"] in (10, 20)]
        u = Uma(v["card_id"], data.sparks(v["factors"]), v.get("wins") or [], ps)
        u.id = v["id"]
        u.rank = v["rank_score"]
        u.sim = False
        vets.append(u)
    trainees = {t["card_id"]: t["potential"] for t in a["trainees"]}
    return vets, trainees


def load_rental():
    """The borrowed parent (rental_one.py's file)."""
    r = json.load(open(_files["rental"], encoding="utf-8"))
    u = data.rental(r)
    u.id = -1
    u.rank = r.get("rank_score", 0)
    u.sim = False
    return u

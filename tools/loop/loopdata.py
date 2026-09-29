"""Shared data and rules for the loop tools (research, not production).

Inputs, all passed as paths (nothing personal lives in this repo):
- master.mdb: the game's master data (copied from the game folder);
- account.json: the companion's `account` read (frida-host `read account`);
- a rental JSON: one borrowed parent as `rental_one.py` reads it;
- names.json: the companion's data/names.json (spark, card and scenario names).

Rules collected so far (sources in README.md):
- white spark generation: 20% (normal) / 25% (double circle) / 40% (gold)
  with none of the 6 ancestors carrying it, up to 35.4 / 44.3 / 70.9% with
  all 6 (loop guide); linear in between is an assumption. The rate follows
  the version the veteran bought, the spark does not: sparks exist only for
  a group's white skill, so a bought gold (It's On!) or ◎ sparks as that
  white (Ramp Up), at its own rate;
- inspiration (twice per run): base by type and stars x (1 + that
  ancestor's affinity / 100); white 3/6/9%, pink 1/3/5%, blue 70/80/90%;
- pinks at the start: total stars of one aptitude over the lineage,
  1 / 4 / 7 / 10 stars -> +1 / +2 / +3 / +4 ranks (owner, 2026-09-28);
- IT race win chance: by the summed rank of surface + distance and by how
  many races in a row (a Japanese IT table; see README).
"""
from __future__ import annotations

import functools
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

GRADES = "GFEDCBAS"  # 1..8 in the game's aptitude columns

# Pink spark name -> aptitude key.
PINKS = {"Turf": "turf", "Dirt": "dirt", "Sprint": "short", "Mile": "mile", "Medium": "medium",
         "Long": "long", "Front Runner": "front", "Pace Chaser": "pace", "Late Surger": "late",
         "End Closer": "end"}
START_PINK_STEPS = (1, 4, 7, 10)  # total stars -> +1..+4 ranks

# White spark generation by the version bought: (none of 6 ancestors, all 6).
RATES = {"normal": (0.20, 0.354), "double": (0.25, 0.443), "gold": (0.40, 0.709)}

# IT win chance (%) by rank steps below A/A (surface + distance summed) and by
# position in a run of consecutive races (1st..6th+). Columns AA..GG of the
# Japanese table: AA=0, AB=1, AC=2, AD=3, AE=4, AF=5, AG=6, BG=7, beyond = 0.
WIN = {
    1: [110, 100, 90, 80, 70, 50, 20, 10],
    2: [110, 100, 90, 80, 70, 50, 20, 10],
    3: [105, 95, 85, 75, 65, 45, 15, 5],
    4: [90, 80, 70, 60, 50, 30, 0, 0],
    5: [80, 70, 60, 50, 40, 20, 0, 0],
    6: [60, 50, 40, 30, 20, 0, 0, 0],
}


def win_chance(surface: str, distance: str, in_a_row: int) -> int:
    """Win chance (%) for aptitude letters (S counts as A)."""
    steps = sum(max(0, 6 - GRADES.index(g)) for g in (surface, distance))  # A (6) and S (7) = 0
    row = WIN[min(max(in_a_row, 1), 6)]
    return row[steps] if steps < len(row) else 0


@dataclass
class Uma:
    """A lineage member: card, sparks by name -> stars, G1 win saddles."""
    card: int
    sparks: dict[str, int]
    wins: list[int] = field(default_factory=list)
    parents: list["Uma"] = field(default_factory=list)

    @property
    def chara(self) -> int:
        return self.card // 100


class Data:
    def __init__(self, master: str, names: str):
        self.db = sqlite3.connect(master)
        n = json.load(open(names, encoding="utf-8"))
        self.factors = n["factors"]
        self.cards = n["uma_cards"]

    def sparks(self, ids) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in ids or []:
            f = self.factors.get(str(i))
            if f:
                out[f[0]] = f[1]
        return out

    def target(self, skill: str) -> tuple[str, str]:
        """A skill the trainee would buy -> (the spark it can generate, the
        rate: normal / double / gold). The spark is the one whose hint is a
        skill of the same group (succession_factor_effect)."""
        row = self.db.execute(
            "select s.rarity, s.group_id, s.group_rate from skill_data s join text_data t"
            " on t.category = 47 and t.\"index\" = s.id where t.text = ? and s.rarity <= 2"
            " order by s.rarity desc limit 1", (skill,)).fetchone()
        if row is None:
            raise KeyError(f"no white or gold skill named {skill!r}")
        rarity, group, rate = row
        fg = self.db.execute(
            "select e.factor_group_id from succession_factor_effect e"
            " join skill_data s on s.id = e.value_1"
            " where s.group_id = ? and e.target_type = 41 limit 1", (group,)).fetchone()
        if fg is None:
            raise KeyError(f"{skill!r} has no spark")
        spark = self.factors[str(fg[0] * 100 + 1)][0]
        return spark, "gold" if rarity == 2 else "double" if rate == 2 else "normal"

    def group(self, skill: str) -> int:
        """A skill's group (a white, its gold and its ◎ share one): hints are
        per group."""
        row = self.db.execute(
            "select s.group_id from skill_data s join text_data t on t.category = 47"
            " and t.\"index\" = s.id where t.text = ? limit 1", (skill,)).fetchone()
        if row is None:
            raise KeyError(f"no skill named {skill!r}")
        return row[0]

    def race(self, race_instance: int) -> tuple[int, int, int, str]:
        """(race id, ground 1 turf / 2 dirt, distance m, name) of a race instance."""
        return self.db.execute(
            "select r.id, cs.ground, cs.distance, coalesce(t.text, '?') from race_instance ri"
            " join race r on r.id = ri.race_id join race_course_set cs on cs.id = r.course_set"
            " left join text_data t on t.category = 28 and t.\"index\" = ri.id where ri.id = ?",
            (race_instance,)).fetchone()

    def skill_groups(self, ids) -> set[int]:
        if not hasattr(self, "_group_of"):
            self._group_of = dict(self.db.execute("select id, group_id from skill_data"))
        return {self._group_of[i] for i in ids if i in self._group_of}

    def name(self, card: int) -> str:
        c = self.cards.get(str(card), {})
        return f"{c.get('name', card)} {c.get('title', '')}".strip()

    def veteran(self, v: dict) -> Uma:
        """An own veteran from the account read, with its two parents."""
        ps = [g for g in v["lineage"] if g["_positionId"] in (10, 20)]
        return Uma(v["_cardId"], self.sparks(v["factors"]), v.get("wins") or [],
                   [Uma(g["<CardId>k__BackingField"], self.sparks(g["factors"]), g.get("wins") or []) for g in ps])

    def rental(self, r: dict) -> Uma:
        """A borrowed parent as rental_one.py reads it."""
        ps = [g for g in r["lineage"] if g["pos"] in (10, 20)]
        return Uma(r["card"], self.sparks(r["factors"]), r.get("wins") or [],
                   [Uma(g["card"], self.sparks(g["factors"]), g.get("wins") or []) for g in ps])

    def base_aptitudes(self, card: int) -> dict[str, str]:
        row = self.db.execute(
            "select proper_ground_turf, proper_ground_dirt, proper_distance_short, proper_distance_mile,"
            " proper_distance_middle, proper_distance_long, proper_running_style_nige,"
            " proper_running_style_senko, proper_running_style_sashi, proper_running_style_oikomi"
            " from card_rarity_data where card_id=? order by rarity desc limit 1", (card,)).fetchone()
        keys = ["turf", "dirt", "short", "mile", "medium", "long", "front", "pace", "late", "end"]
        return {k: GRADES[v - 1] for k, v in zip(keys, row)}

    def start_aptitudes(self, card: int, p1: Uma, p2: Uma) -> dict[str, str]:
        """Base aptitudes raised by the lineage's pinks at the start of a run."""
        apt = self.base_aptitudes(card)
        stars: dict[str, int] = {}
        for m in (p1, p2, *p1.parents, *p2.parents):
            for s, n in m.sparks.items():
                if s in PINKS:
                    stars[PINKS[s]] = stars.get(PINKS[s], 0) + n
        for k, n in stars.items():
            up = sum(1 for step in START_PINK_STEPS if n >= step)
            apt[k] = GRADES[min(GRADES.index(apt[k]) + up, 6)]  # stops at A
        return apt


# Trainee events (uma-it-web's trainee_events.json, from GameTora) and the
# scenario's own event hints (scenario_hints.py, from site receipts).
WEB_DATA = Path(__file__).resolve().parent / "../../../uma-it-web/uma_it_web/enrich/data"
SCENARIO_HINTS = Path(__file__).resolve().parent / "data/scenario_event_hints.json"


@functools.cache
def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trainee_events(card: int, path: Path = WEB_DATA / "trainee_events.json") -> list[dict]:
    """The trainee card's events that hint a skill only when conditions are
    met: {name, skills [[id, levels]], needs [{rule, races [[instance, year]]}],
    other [conditions no plan can aim for]}."""
    return (_json(path)["trainees"].get(str(card)) or {}).get("events", [])


def scenario_hint(scenario: int, group: int, path: Path = SCENARIO_HINTS) -> float:
    """Share of the scenario's runs whose own events hint the skill group."""
    return (_json(path).get(str(scenario)) or {}).get("groups", {}).get(str(group), 0.0)


def own_veterans(acct: dict) -> list[dict]:
    """The player's own veterans: a parent borrowed for the current run sits
    in the same list, marked by its lender (`_ownerViewerId`)."""
    return [v for v in acct["veterans"] if not v.get("_ownerViewerId")]


def load_account(path: str) -> dict:
    return json.load(open(path, encoding="utf-8"))

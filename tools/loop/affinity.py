"""Affinity (compatibility) from master.mdb, rough.

rel(A, B, ...) = sum of relation_point over the relation groups that contain
every one of the characters. The combination follows what community
calculators describe; the race part is 3 points per G1 win saddle shared.
Checked: the symbol thresholds (51 circle, 151 double circle) and the saddle
grades; one published pair (34) came out 39 here, so treat totals as close,
not exact.
"""
from __future__ import annotations

import collections
import functools

from loopdata import Data, Uma


class Affinity:
    def __init__(self, data: Data):
        db = data.db
        self.point = dict(db.execute("select relation_type, relation_point from succession_relation"))
        self.groups: dict[int, set[int]] = collections.defaultdict(set)
        for rt, ch in db.execute("select relation_type, chara_id from succession_relation_member"):
            self.groups[ch].add(rt)
        # Win saddles that are a single G1 race (grade 100).
        self.g1 = {sid for (sid,) in db.execute(
            "select s.id from single_mode_wins_saddle s join race_instance ri on ri.id = s.race_instance_id_1"
            " join race r on r.id = ri.race_id where s.race_instance_id_2 = 0 and r.grade = 100")}
        self.rel = functools.lru_cache(None)(self._rel)

    def _rel(self, *charas: int) -> int:
        common = set.intersection(*(self.groups[c] for c in charas))
        return sum(self.point[t] for t in common)

    def race(self, a: Uma, b: Uma) -> int:
        return 3 * len(set(a.wins) & set(b.wins) & self.g1)

    def evaluate(self, trainee: int, p1: Uma, p2: Uma) -> dict | None:
        """Total and per-member affinity; None when a character repeats."""
        t = trainee // 100
        if len({t, p1.chara, p2.chara}) < 3:
            return None
        rel = self.rel
        side = {}
        for key, p, other in (("p1", p1, p2), ("p2", p2, p1)):
            side[key] = rel(t, p.chara) + sum(rel(t, p.chara, g.chara) for g in p.parents) \
                + sum(self.race(p, g) for g in p.parents) + (self.race(p, other) if key == "p1" else 0)
        total = rel(t, p1.chara) + rel(t, p2.chara) + rel(p1.chara, p2.chara) \
            + sum(rel(t, p1.chara, g.chara) for g in p1.parents) + sum(rel(t, p2.chara, g.chara) for g in p2.parents) \
            + sum(self.race(p1, g) for g in p1.parents) + sum(self.race(p2, g) for g in p2.parents) + self.race(p1, p2)
        members = [(p1, side["p1"], 1.0), (p2, side["p2"], 1.0)]
        for p in (p1, p2):
            for g in p.parents:
                members.append((g, rel(t, p.chara, g.chara) + self.race(p, g), 0.5))
        inbreed = sum(1 for p in (p1, p2) for g in p.parents if g.chara == t)
        return {"total": total, "p1": side["p1"], "p2": side["p2"], "members": members, "inbreed": inbreed}


def symbol(total: int) -> str:
    return "◎" if total > 150 else "○" if total > 50 else "△"

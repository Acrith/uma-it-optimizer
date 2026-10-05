"""Loop simulator: a run's hints, purchases, spark rolls (two, the better
kept) and the veteran it leaves, from the measured rules; strategies pick
trainee, parents, deck and the day's borrows.

Rules (sources: loopdata.py, the companion's rates.ts, and checks
2026-10-01 on the test account's spark records, calib_gen.py):
- hint: inspiration from the 6 ancestors, twice a run, white 3/6/9% by
  stars x (1 + affinity/100) ("+" sparks hint too); the scenario's own events
  (URA: Racing Spirit skills); her events (races won); the deck's cards; her
  own skills (up to her potential) need no hint;
- bought: every hinted target (and its gold when hinted or her own);
- spark roll: base 20% (white) / 25% (◎) / 40% (gold) x 1.1 per carrier of
  the 6 (165 trials: 44 sparked vs 50.3 expected);
- "+": in URA every roll, exactly one "+" on one of the Racing Spirits
  bought (9 of 9 rolls); that skill loses its plain spark in that roll
  (Unity Cup's "+" is an Ignited Spirit's, Grand Concert has none);
- stars of a new white: 1/2/3 at 41.7/53/5.3% (the test box);
- the better roll is kept by the Sparks module's own rating.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

import world
from world import (
    BASE,
    INSP,
    RS_TARGETS,
    SCEN,
    TARGETS,
    TYPICAL,
    WHITE_STARS,
    Uma,
    event_hint,
    own_of,
)

DECOY_RS = 4          # Racing Spirits other than the targets (Speed, Guts, Wit, Mood)
DECOY_HINT = 0.45     # each hinted in URA about this often (scenario_hints: 31-43%)
# Experiments: a fixed number of decoys bought every run (strategies.py --decoys).
DECOYS_FIXED: int | None = None
WIN_KEEP = 0.9        # a parents' G1 on her agenda, won


_SETUP: dict = {}


@dataclass(frozen=True)
class Deck:
    name: str
    hint: tuple   # per target: chance a card hints it
    gold: tuple   # per target: chance a gold hint comes with it


def deck(name, hints: dict, golds: dict | None = None) -> Deck:
    return Deck(name, tuple(hints.get(t, 0.0) for t in TARGETS), tuple((golds or {}).get(t, 0.0) for t in TARGETS))


# The test account's two decks of 2026-10-01: King Halo or Yukino as the friend card
# (Agnes Digital hints Uma Stan 56%; with King Halo 87%; Yukino: Nimble 78%,
# its gold 78% with 3 pals).
# Uma Stan by scenario (card_hints.json): Agnes Digital + King Halo; Agnes alone.
DECKS: tuple = ()
DECK_KH = DECK_YB = None
# A deck given as card ids (lineage.py --deck): its rates per target from
# the companion's card_hints.json (site receipts, per card and scenario).
DECK_CARDS: list[int] = []
CARD_HINTS = ""


def deck_from_cards(name: str, cards: list[int], sc: int) -> Deck:
    """Per target: the chance some card of the deck hints it (and the gold),
    the cards taken as independent, each from its scenario's cell (else all
    scenarios'). The deck's pal count is not adjusted for."""
    by_card = json.load(open(CARD_HINTS, encoding="utf-8"))["cards"]
    hints, golds = {}, {}
    for t in TARGETS:
        g = str(world.GROUP[t])
        miss_h = miss_g = 1.0
        for c in cards:
            by = (by_card.get(str(c)) or {}).get("by", {})
            cell = (by.get(str(sc)) or by.get("0") or {}).get("all") or {}
            miss_h *= 1 - cell.get("hint", {}).get(g, 0.0)
            miss_g *= 1 - cell.get("gold", {}).get(g, 0.0)
        hints[t], golds[t] = 1 - miss_h, 1 - miss_g
    return deck(name, hints, golds)


def set_scenario(sc: int) -> None:
    """Switch scenario: hints, the "+" rule, the deck's rates; drop caches."""
    global DECKS, DECK_KH, DECK_YB
    world.set_scenario(sc)
    kh, ag = {1: 0.868, 2: 0.96, 3: 0.83}[sc], {1: 0.56, 2: 0.87, 3: 0.53}[sc]
    DECK_KH = deck(f"King Halo friend/{sc}", {"Uma Stan": kh})
    DECK_YB = deck(f"Yukino friend/{sc}", {"Uma Stan": ag, "Nimble Navigator": 0.78}, {"Nimble Navigator": 0.78})
    DECKS = (DECK_KH, DECK_YB)
    if DECK_CARDS:
        DECKS = (deck_from_cards(f"deck/{sc}", DECK_CARDS, sc),)
    _SETUP.clear()
    _VALUE_EPOCH[0] += 1


# Target weights for choosing and keeping (lineage.py: the active list 1,
# the candidates not yet looped 0, so their sparks are tracked but don't
# steer). Missing: 1.
WEIGHTS: dict[str, float] = {}


def weight(t: str) -> float:
    return WEIGHTS.get(t, 1.0)


_VALUE_EPOCH = [0]


def apt_key(card, p1, p2):
    return tuple(sorted(world.data.start_aptitudes(card, p1, p2).items()))


def ok_aptitude(card, p1, p2) -> bool:
    apt = dict(apt_key(card, p1, p2))
    return min("GFEDCBAS".index(apt["turf"]), "GFEDCBAS".index(apt["medium"])) >= "GFEDCBAS".index("B")




def setup(card: int, potential: int, p1: Uma, p2: Uma, dk: Deck):
    """Per target: (hint chance, gold chance, carriers). None if not allowed."""
    key = (card, potential, p1.id, p2.id, dk.name)
    if key not in _SETUP:
        _SETUP[key] = _setup(card, potential, p1, p2, dk)
    return _SETUP[key]


def _setup(card: int, potential: int, p1: Uma, p2: Uma, dk: Deck):
    if len({card // 100, p1.chara, p2.chara}) < 3 or not ok_aptitude(card, p1, p2):
        return None
    r = world.aff.evaluate(card, p1, p2)
    if not r:
        return None
    own = own_of(card, potential)
    ak = apt_key(card, p1, p2)
    out = []
    for i, t in enumerate(TARGETS):
        k = sum(1 for m, _, _ in r["members"] if t in m.sparks)
        miss = 1.0
        for m, a, _ in r["members"]:
            for st in (m.sparks.get(t), m.sparks.get(f"{t} +")):
                if st:
                    miss *= (1 - INSP[st] * (1 + a / 100)) ** 2
        other = 1 - (1 - SCEN[t]) * (1 - event_hint(card, t, ak)) * (1 - dk.hint[i])
        # The scenario's every-run golds (Unity Cup: It's On!, No Stopping
        # Me!) come to any trainee: her own gold of those adds nothing.
        sg = max(dk.gold[i], world.SCEN_GOLD.get(t, 0.0))
        if t in own:
            h, g = 1.0, 1.0 if own[t] == "gold" else sg
        else:
            h = 1 - miss * (1 - other)
            g = min(sg, h)
        out.append((h, g, k))
    return tuple(out), r["total"]


def plus_spare(hints) -> list[float]:
    """Per target: chance an RS target, if bought, keeps its plain spark from
    the roll's "+" (one "+" on the Racing Spirits bought, evenly)."""
    out = []
    for i, t in enumerate(TARGETS):
        if t not in RS_TARGETS or not world.PLUS_TAX:
            out.append(1.0)
            continue
        others = [hints[j][0] for j, u in enumerate(TARGETS) if u in RS_TARGETS and u != t]
        e = 0.0
        # other RS target bought or not, decoys ~ Binomial(4, 0.45)
        from math import comb
        for o_bought, po in ((1, others[0]), (0, 1 - others[0])) if others else ((0, 1.0),):
            for d in range(DECOY_RS + 1):
                pd = comb(DECOY_RS, d) * DECOY_HINT ** d * (1 - DECOY_HINT) ** (DECOY_RS - d)
                if DECOYS_FIXED is not None:
                    pd = 1.0 if d == DECOYS_FIXED else 0.0
                n = 1 + o_bought + d
                e += po * pd * (1 - 1 / n)
        out.append(e)
    return out


def expected(card, potential, p1, p2, dk) -> tuple[float, list[float]] | None:
    """Expected target sparks in one roll, and per target."""
    s = setup(card, potential, p1, p2, dk)
    if s is None:
        return None
    hints, _ = s
    spare = plus_spare(hints)
    per = [((h - g) * BASE["normal"] + g * BASE["gold"]) * 1.1 ** k * spare[i] for i, (h, g, k) in enumerate(hints)]
    return sum(weight(t) * p for t, p in zip(TARGETS, per, strict=True)), per


def best_of_two_4plus(per: list[float]) -> float:
    d = [1.0]
    for p in per:
        n = [0.0] * (len(d) + 1)
        for i, q in enumerate(d):
            n[i] += q * (1 - p); n[i + 1] += q * p
        d = n
    cdf = [sum(d[:i + 1]) for i in range(len(d))]
    return sum(cdf[i] ** 2 - (cdf[i - 1] ** 2 if i else 0) for i in range(4, len(d)))


# ── the parent rating (the Sparks module's: Oguri as partner, typical
#    affinities, deck not counted, white roll) ─────────────────────────────

RENTAL: Uma | None = None


def value(v: Uma) -> float:
    """Needed sparks per child as a parent with the rental."""
    cache = getattr(v, "_value", None)
    if cache is not None and cache[0] == _VALUE_EPOCH[0]:
        return cache[1]
    anc = [(v, TYPICAL["parent"])] + [(g, TYPICAL["grandparent"]) for g in v.parents]
    if RENTAL is not None:
        anc += [(RENTAL, TYPICAL["parent"])] + [(g, TYPICAL["grandparent"]) for g in RENTAL.parents]
    tot = 0.0
    for t in TARGETS:
        k = sum(1 for a, _ in anc if t in a.sparks)
        miss = 1 - SCEN[t]
        for a, lvl in anc:
            for st in (a.sparks.get(t), a.sparks.get(f"{t} +")):
                if st:
                    miss *= (1 - INSP[st] * (1 + lvl / 100)) ** 2
        tot += weight(t) * (1 - miss) * BASE["normal"] * 1.1 ** k
    v._value = (_VALUE_EPOCH[0], tot)
    return tot


# ── one run ──────────────────────────────────────────────────────────────

_next_id = [10_000]


def stars(rng) -> int:
    x = rng.random()
    return 1 if x < WHITE_STARS[0] else 2 if x < WHITE_STARS[0] + WHITE_STARS[1] else 3


def run(rng: random.Random, card, potential, p1: Uma, p2: Uma, dk: Deck) -> Uma:
    hints, _ = setup(card, potential, p1, p2, dk)
    bought = {}  # target -> version
    for i, t in enumerate(TARGETS):
        h, g, k = hints[i]
        x = rng.random()
        if x < g:
            bought[t] = "gold"
        elif x < h:
            bought[t] = "normal"
    decoys = DECOYS_FIXED if DECOYS_FIXED is not None else sum(1 for _ in range(DECOY_RS) if rng.random() < DECOY_HINT)
    rs = [t for t in bought if t in RS_TARGETS] + [f"decoy{j}" for j in range(decoys)]
    rolls = []
    for _ in range(2):
        plus = rng.choice(rs) if rs and world.PLUS_TAX else None
        sp = {}
        for i, t in enumerate(TARGETS):
            if t not in bought:
                continue
            if t == plus:
                sp[f"{t} +"] = stars(rng)
                continue
            if rng.random() < BASE[bought[t]] * 1.1 ** hints[i][2]:
                sp[t] = stars(rng)
        rolls.append(sp)
    wins = [w for w in set(p1.wins) | set(p2.wins) if w in world.aff.g1 and rng.random() < WIN_KEEP]
    parents = [Uma(p.card, p.sparks, p.wins) for p in (p1, p2)]
    kids = [Uma(card, sp, wins, parents) for sp in rolls]
    child = max(kids, key=value)
    _next_id[0] += 1
    child.id = _next_id[0]; child.rank = 0; child.sim = True
    return child


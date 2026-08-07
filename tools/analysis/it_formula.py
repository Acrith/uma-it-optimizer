"""IT card-contribution formula: decoder, validator, and lab analyses.

The formula decoded from the Trackblazer ladder (2026-08-05, see
`../../../uma-it-web/docs/it-formula.md` for the full research log):

    base_stat = floor( g_run * (C + 0*FB + 5*Mood + 21*TE) )

where FB / Mood / TE are the card's UNIQUE-INCLUSIVE percentages at its
current level, C ~= 3400 (i.e. C:wMood ~= 680:1), and ``g_run`` is a
per-run scale absorbing unit(races) ~ 0.423*(76-races), scenario and
whatever drives the run-level multiplier. Facility-elevated cells and
the SP column are NOT modelled here (open channels).

When a scenario pal card is in the deck its multiplier applies AFTER
the per-card floor, with its own floor:

    base_stat = floor( M_pal * floor(g_run * (C + axis)) )

Inputs (both recoverable, neither is in the repo):
  * ``master.mdb`` — copy from the game install, e.g.
    /mnt/c/Users/<you>/AppData/LocalLow/Cygames/Umamusume/master/master.mdb
  * run JSONs — from the production volume:
        flyctl ssh console -C "tar czf /tmp/runs.tgz -C /app/instance runs"
        flyctl ssh sftp get /tmp/runs.tgz ./runs.tgz

Usage:
    python it_formula.py validate   --runs runs/ --mdb master.mdb
    python it_formula.py ladder     --runs runs/ --mdb master.mdb
    python it_formula.py conditions --runs runs/ --mdb master.mdb
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Milestone columns of support_card_effect_table (init + limit_lv5..50).
MILESTONES = (1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50)
STAT_FIELDS = ("Speed", "Stamina", "Power", "Guts", "Wiz")

# Effect type ids that matter to the base contribution.
EFF_FRIENDSHIP = 1
EFF_MOOD = 2
EFF_TRAINING = 8
EFF_INIT_STATS = (9, 10, 11, 12, 13)   # initial Spd/Sta/Pow/Guts/Wiz

# Axis weights, from three byte-identical ladder cards (see doc).
# Settled 2026-08-06 by three single-axis isolation runs (Trackblazer,
# 4 races each) that held two of the three bonuses fixed and varied the
# third. Friendship is ZERO: six cards spanning FB 15..35 with Mood and
# TE identical all returned the same base of 32. Mood 0..65 moved base
# 32->35; TE 0..15 moved 31->34, giving TE:Mood ~ 4.2:1, not the 3:1
# previously assumed. The old 2:3:9 set carried a Friendship term that
# only ever fit because FB correlates with rarity and level.
W_FRIENDSHIP, W_MOOD, W_TRAINING = 0, 5, 21

# Effective training-facility level in IT. Read off [Sentimental Flare ♪],
# whose unique grants +5% TE per facility level: its base pins the level to
# 4 (levels are 105 axis units apart, and the deck's controls pin g to +-6).
# Note training_level_info_array reports 1 for these facilities — that field
# does NOT mean what it appears to.
FACILITY_LEVEL = 4
C_DEFAULT = 1450

# Scenario -> pal card ids (the deck-wide multiplier cards).
PAL_BY_SCENARIO = {
    1: {10022, 20021},    # URA — Aoi Kiryuin
    2: {10060, 30036},    # Unity Cup — Riko Kashimoto
    3: {10083, 30052},    # Our Grand Concert — Light Hello
    4: set(),             # Trackblazer — no pal exists
}


@dataclass(frozen=True)
class CardRow:
    """One support card's contribution inside one run."""

    card_id: int
    level: int
    base: int          # min stat after removing the card's initial-stat adders
    axis: int          # 2*FB + 3*Mood + 9*TE, unique-inclusive


class Masters:
    """Read-only view over the parts of master.mdb the formula needs."""

    def __init__(self, mdb_path: Path) -> None:
        db = sqlite3.connect(f"file:{mdb_path}?mode=ro", uri=True)
        cur = db.cursor()

        self.rarity: dict[int, int] = {}
        self.trainer_cards: set[int] = set()
        for cid, rar, sc_type in cur.execute(
            "SELECT id, rarity, support_card_type FROM support_card_data"
        ):
            self.rarity[cid] = rar
            # type 1 = training cards. Friend (2) / group (3) cards follow
            # a different, still-undecoded channel — never mix them in.
            if sc_type == 1:
                self.trainer_cards.add(cid)

        self._levels: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for rar, lv, exp in cur.execute(
            "SELECT rarity, level, total_exp FROM support_card_level "
            "ORDER BY rarity, level"
        ):
            self._levels[rar].append((exp, lv))

        self._caps = {
            row[0]: row[1:]
            for row in cur.execute(
                "SELECT rarity, limit_0, limit_1, limit_2, limit_3, limit_4 "
                "FROM support_card_limit"
            )
        }

        self._effects: dict[tuple[int, int], list[int]] = {}
        for row in cur.execute("SELECT * FROM support_card_effect_table"):
            cid, typ, *values = row
            self._effects[(cid, typ)] = values

        # unique_effect: unlocks at `lv`; two (type, value) slots.
        # type >= 100 means CONDITIONAL — how IT treats those is still open,
        # so they are folded in optimistically and flagged.
        self._uniques: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {}
        # Conditional uniques (type >= 100) use a different column layout:
        # type_0 names the CONDITION and value_0 is its parameter, with the
        # actual effect in value_0_1 (effect type) / value_0_2 (magnitude).
        #   101 -> "bond >= value_0"          e.g. 101/80/8/10  = +10 TE
        #   111 -> "per facility level"       e.g. 111/8/5      = +5 TE per lv
        #   112 -> chance-based, 113 -> during friendship training
        # These were previously skipped as unmodellable. They are not: a deck
        # with two bond-gated +10 TE cards only fits once they are applied
        # (20260807T144029), and applying them moves the 6-trainer population
        # from 78.1% to 89.6%.
        self._cond: dict[int, tuple[int, int, int, int, int]] = {}
        for cid, ulv, t0, v0, v01, v02, t1, v1 in cur.execute(
            "SELECT id, lv, type_0, value_0, value_0_1, value_0_2, type_1, value_1 "
            "FROM support_card_unique_effect"
        ):
            self._uniques[cid] = (ulv, ((t0, v0), (t1, v1)))
            if t0 and t0 >= 100:
                self._cond[cid] = (ulv, t0, v0, v01, v02)

        self.card_name = {
            idx: text
            for idx, text in cur.execute(
                'SELECT "index", text FROM text_data WHERE category = 76'
            )
        }
        self.condition_name = {
            idx: text
            for idx, text in cur.execute(
                'SELECT "index", text FROM text_data WHERE category = 142'
            )
        }
        db.close()

    def level_from_exp(self, card_id: int, exp: int, limit_break: int) -> int | None:
        rarity = self.rarity.get(card_id)
        if rarity is None:
            return None
        steps = self._levels[rarity]
        idx = bisect_right([e for e, _ in steps], exp) - 1
        level = steps[max(idx, 0)][1]
        cap = self._caps[rarity][min(max(limit_break, 0), 4)]
        return min(level, cap)

    def effect_at(self, card_id: int, effect_type: int, level: int) -> int:
        """Effect value at `level`, linearly interpolated between the
        defined milestones (-1 marks an undefined milestone)."""
        values = self._effects.get((card_id, effect_type))
        if not values:
            return 0
        points = [(MILESTONES[i], v) for i, v in enumerate(values) if v != -1]
        if not points:
            return 0
        if level < points[0][0]:
            # -1 milestones mean the effect is NOT YET UNLOCKED, not
            # "same as the first defined value". Confirmed in-game on
            # 30101 [Q≠0]: its Skill Point Bonus first appears at lv45
            # (+1) and becomes +2 at lv50 — below lv45 the tooltip has
            # no such line at all. 1,251 effect rows unlock above lv1,
            # so crediting the first value early inflated every
            # under-levelled card.
            return 0
        if level == points[0][0]:
            return points[0][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if level <= x1:
                return round(y0 + (y1 - y0) * (level - x0) / (x1 - x0))
        return points[-1][1]

    def bonuses(self, card_id: int, level: int) -> tuple[int, int, int, list[int], bool]:
        """(friendship, mood, training, initial_stats[5], has_conditional_unique),
        with the card's unique effect folded in when its level gate is met."""
        friendship = self.effect_at(card_id, EFF_FRIENDSHIP, level)
        mood = self.effect_at(card_id, EFF_MOOD, level)
        training = self.effect_at(card_id, EFF_TRAINING, level)
        initial = [self.effect_at(card_id, t, level) for t in EFF_INIT_STATS]
        conditional = False

        cond = self._cond.get(card_id)
        if cond and level >= cond[0]:
            _, ctype, cparam, ceff, cmag = cond
            if ctype == 101:
                # bond >= cparam. Observed to FIRE in IT — do not skip it.
                if ceff == EFF_TRAINING:
                    training += cmag
                elif ceff == EFF_MOOD:
                    mood += cmag
                elif ceff == EFF_FRIENDSHIP:
                    friendship += cmag
            elif ctype == 111:
                # +cparam-effect per facility level; level 4 fits best globally
                # and matches the single Sentimental Flare probe run.
                if cparam == EFF_TRAINING:
                    training += ceff * FACILITY_LEVEL
                elif cparam == EFF_MOOD:
                    mood += ceff * FACILITY_LEVEL

        unique = self._uniques.get(card_id)
        if unique and level >= unique[0]:
            for effect_type, value in unique[1]:
                if effect_type >= 100:
                    conditional = True
                elif effect_type == EFF_FRIENDSHIP:
                    friendship += value
                elif effect_type == EFF_MOOD:
                    mood += value
                elif effect_type == EFF_TRAINING:
                    training += value
                elif effect_type in EFF_INIT_STATS:
                    initial[EFF_INIT_STATS.index(effect_type)] += value
        return friendship, mood, training, initial, conditional


def axis_of(friendship: int, mood: int, training: int) -> int:
    return W_FRIENDSHIP * friendship + W_MOOD * mood + W_TRAINING * training


def load_run(path: Path, masters: Masters) -> dict | None:
    """Parse one capture into {races, mood, scenario, has_pal, rows, conditions}."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    chara_list = raw.get("SingleModeChara") or []
    if not chara_list:
        return None
    chara = chara_list[0]
    scenario = int(chara.get("scenario_id") or 0)
    pals = PAL_BY_SCENARIO.get(scenario, set())

    deck = {
        int(c.get("support_card_id") or 0): (
            int(c.get("exp") or 0),
            int(c.get("limit_break_count") or 0),
        )
        for c in chara.get("support_card_array") or []
    }

    rows: list[CardRow] = []
    for entry in raw.get("SupportCardGainInfo") or []:
        card_id = entry["<SupportCardId>k__BackingField"]
        if card_id in pals or card_id not in masters.trainer_cards:
            continue
        if card_id not in deck:
            continue
        level = masters.level_from_exp(card_id, *deck[card_id])
        if level is None:
            continue
        gains = entry["<GainInfo>k__BackingField"]
        stats = [gains[f"<{s}>k__BackingField"] for s in STAT_FIELDS]
        friendship, mood, training, initial, _ = masters.bonuses(card_id, level)
        # Read the base off stats the card gives NO initial bonus to.
        # Initial stats land on SPECIFIC stats, so for most cards the
        # minimum is already untouched and subtracting was harmless —
        # but a card with an initial bonus on all five (e.g. 30078,
        # +30 across the board) has a genuinely inflated minimum, and
        # subtracting the master value overshot it by ~9 every time.
        # Ignoring the bonused stats instead took the pal-free fit from
        # 40% to 59% of runs (86.2% -> 90.7% of rows).
        free = [s for s, i in zip(stats, initial) if i == 0]
        base = min(free) if free else min(s - i for s, i in zip(stats, initial))
        if base <= 0:
            continue
        rows.append(
            CardRow(card_id, level, base, axis_of(friendship, mood, training))
        )

    condition_log = raw.get("CharaEffectLog")
    conditions = None
    if condition_log is not None:
        conditions = [
            (
                e.get("<CharaEffectId>k__BackingField"),
                bool(e.get("<IsActive>k__BackingField")),
            )
            for e in condition_log
            if e.get("<CharaEffectId>k__BackingField") is not None
        ]

    return {
        "file": path.name,
        "races": len(raw.get("RaceHistory") or []),
        "mood": int(chara.get("motivation") or 0),
        "scenario": scenario,
        "has_pal": bool(pals & set(deck)),
        "rows": rows,
        "conditions": conditions,
    }


def scale_interval(rows: list[CardRow], const: int) -> tuple[float, float]:
    """Feasible [lo, hi) for g_run such that floor(g*(C+axis)) == base for
    every row. Empty (lo >= hi) means no single scale explains the run."""
    lo, hi = 0.0, float("inf")
    for row in rows:
        weight = const + row.axis
        lo = max(lo, row.base / weight)
        hi = min(hi, (row.base + 1) / weight)
    return lo, hi


def best_partial_scale(rows: list[CardRow], const: int) -> tuple[float, int]:
    """Scale maximising exact row hits when no full fit exists."""
    candidates = []
    for row in rows:
        weight = const + row.axis
        candidates.append(row.base / weight)
        candidates.append((row.base + 1) / weight - 1e-9)
    best_g, best_hits = candidates[0], 0
    for g in candidates:
        hits = sum(1 for r in rows if int(g * (const + r.axis)) == r.base)
        if hits > best_hits:
            best_g, best_hits = g, hits
    return best_g, best_hits


def iter_runs(runs_dir: Path, masters: Masters):
    for path in sorted(glob.glob(str(runs_dir / "**" / "*.json"), recursive=True)):
        run = load_run(Path(path), masters)
        if run and len(run["rows"]) >= 4:
            yield run


def cmd_validate(runs_dir: Path, masters: Masters, consts: list[int]) -> None:
    """Prod-wide within-run test, split by pal presence."""
    runs = list(iter_runs(runs_dir, masters))
    print(f"runs with >=4 trainer rows: {len(runs)}\n")
    for const in consts:
        stats = {True: [0, 0, 0, 0], False: [0, 0, 0, 0]}  # runs, full, rows, hits
        misses: Counter[int] = Counter()
        appearances: Counter[int] = Counter()
        for run in runs:
            bucket = stats[run["has_pal"]]
            bucket[0] += 1
            bucket[2] += len(run["rows"])
            for row in run["rows"]:
                appearances[row.card_id] += 1
            lo, hi = scale_interval(run["rows"], const)
            if lo < hi:
                bucket[1] += 1
                bucket[3] += len(run["rows"])
                continue
            g, hits = best_partial_scale(run["rows"], const)
            bucket[3] += hits
            for row in run["rows"]:
                if int(g * (const + row.axis)) != row.base:
                    misses[row.card_id] += 1
        print(f"C={const}:")
        for has_pal, label in ((False, "pal-free"), (True, "with pal")):
            n, full, total, hits = stats[has_pal]
            if not n:
                continue
            print(
                f"  {label:>9}: runs {n:>3}  full-fit {full:>3} "
                f"({100 * full / n:>2.0f}%)  rows {hits}/{total} "
                f"({100 * hits / max(total, 1):.1f}%)"
            )
        if const == consts[-1]:
            print("  worst cards (misses / appearances):")
            for card_id, count in misses.most_common(8):
                name = masters.card_name.get(card_id, "?")
                print(
                    f"    {card_id} {name}: {count}/{appearances[card_id]} "
                    f"({100 * count / appearances[card_id]:.0f}%)"
                )


def cmd_ladder(runs_dir: Path, masters: Masters, const: int) -> None:
    """Per-card race table for the fixed-deck Trackblazer ladder."""
    ladder = [r for r in iter_runs(runs_dir, masters)
              if r["scenario"] == 4 and not r["has_pal"]]
    by_card: dict[int, dict[int, CardRow]] = defaultdict(dict)
    for run in ladder:
        for row in run["rows"]:
            by_card[row.card_id][run["races"]] = row
    # Only cards present across the whole ladder are informative.
    spans = {cid: pts for cid, pts in by_card.items() if len(pts) >= 8}
    if not spans:
        print("no fixed-deck ladder found in this corpus")
        return
    race_counts = sorted({r for pts in spans.values() for r in pts})
    print(f"scen4 ladder: {len(ladder)} runs, races {race_counts}")
    print("NOTE: this sweeps every pal-free scen4 run, so it can mix runs from\n"
          "different g_run regimes (different parents/dates). A single p per card\n"
          "only holds within ONE controlled ladder — misses here may be regime\n"
          "changes rather than formula failures.\n")
    print("      races: " + " ".join(f"{r:>3}" for r in race_counts))
    for card_id, points in sorted(spans.items(), key=lambda kv: -next(iter(kv[1].values())).axis):
        axis = next(iter(points.values())).axis
        # Feasible product interval p = g*(C+axis) collapsed to a point.
        lo = max(row.base / (76 - races) for races, row in points.items())
        hi = min((row.base + 1) / (76 - races) for races, row in points.items())
        p = (lo + hi) / 2 if lo < hi else lo
        obs = " ".join(
            f"{points[r].base:>3}" if r in points else "  ." for r in race_counts
        )
        pred = " ".join(
            f"{int(p * (76 - r)):>3}" if r in points else "  ." for r in race_counts
        )
        bad = [r for r in points if int(p * (76 - r)) != points[r].base]
        name = masters.card_name.get(card_id, "?")
        print(f"\n  {card_id} axis {axis:>3} p={p:.4f} {name}")
        print(f"        obs: {obs}")
        print(f"       pred: {pred}" + (f"   MISS @{bad}" if bad else "   exact"))


def cmd_conditions(runs_dir: Path, masters: Masters) -> None:
    """Condition census + end-mood, controlling for schedule density."""
    runs = [r for r in iter_runs(runs_dir, masters) if r["conditions"] is not None]
    print(f"runs with a CharaEffectLog: {len(runs)}\n")

    occurred: Counter[int] = Counter()
    survived: Counter[int] = Counter()
    for run in runs:
        for eid, active in run["conditions"]:
            occurred[eid] += 1
            if active:
                survived[eid] += 1
    print(f"{'id':>4} {'condition':<26} {'occurred':>9} {'survived':>9} {'cured':>7}")
    for eid in sorted(occurred):
        name = masters.condition_name.get(eid, "?")
        cured = occurred[eid] - survived[eid]
        print(f"{eid:>4} {name:<26} {occurred[eid]:>9} {survived[eid]:>9} {cured:>7}")

    SKIN = 3
    print("\nSkin Outbreak occurrence by race count:")
    buckets: dict[str, list[int]] = defaultdict(list)
    for run in runs:
        races = run["races"]
        label = ("<=20" if races <= 20 else "21-26" if races <= 26
                 else "27-33" if races <= 33 else "34+")
        buckets[label].append(any(e == SKIN for e, _ in run["conditions"]))
    for label in ("<=20", "21-26", "27-33", "34+"):
        hits = buckets.get(label, [])
        if hits:
            print(f"  {label:>6}: {sum(hits):>3}/{len(hits):<3} "
                  f"({100 * sum(hits) / len(hits):.0f}%)")

    print("\nend-mood, paired on EXACT race count (removes density confound):")
    paired: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: {"skin": [], "clean": []}
    )
    for run in runs:
        key = "skin" if any(e == SKIN for e, _ in run["conditions"]) else "clean"
        paired[run["races"]][key].append(run["mood"])
    deltas = []
    for races in sorted(paired):
        group = paired[races]
        if len(group["skin"]) >= 3 and len(group["clean"]) >= 3:
            a = sum(group["skin"]) / len(group["skin"])
            b = sum(group["clean"]) / len(group["clean"])
            deltas.append(a - b)
            print(f"  races {races:>2}: skin {a:.2f} (n={len(group['skin']):>2})  "
                  f"clean {b:.2f} (n={len(group['clean']):>2})  delta {a - b:+.2f}")
    if deltas:
        print(f"  mean delta: {sum(deltas) / len(deltas):+.2f} mood")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("validate", "ladder", "conditions"))
    parser.add_argument("--runs", type=Path, default=Path("runs"),
                        help="directory of run JSONs (searched recursively)")
    parser.add_argument("--mdb", type=Path, default=Path("master.mdb"))
    parser.add_argument("--const", type=int, default=C_DEFAULT,
                        help=f"formula constant C (default {C_DEFAULT})")
    args = parser.parse_args()

    if not args.mdb.is_file():
        print(f"master.mdb not found at {args.mdb} — see this file's docstring "
              "for where to copy it from")
        return 1
    masters = Masters(args.mdb)

    if args.mode == "validate":
        cmd_validate(args.runs, masters, [1400, 1450, 1490, 1550])
    elif args.mode == "ladder":
        cmd_ladder(args.runs, masters, args.const)
    else:
        cmd_conditions(args.runs, masters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

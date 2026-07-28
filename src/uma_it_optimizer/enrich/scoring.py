"""SS-grade score estimator.

Port of the ``finalScore_rank()`` logic from hzyhhzy/UmaAi (MIT license,
``UmaSimulator/Game/Game.cpp``). The formula is:

    score = Σ FiveStatusFinalScore[min(stat_i, cap_i)]        (5 stats)
          + int(ptScoreRate × unspent_sp + Σ owned_skill_scores)

Where:
- ``FiveStatusFinalScore`` is a 2801-int precomputed diminishing-returns
  curve (see ``data/five_status_score.py``)
- ``ptScoreRate = 2.0`` — the game's default SP-to-score conversion rate
- ``owned_skill_scores`` — sum of ``skill_data.grade_value`` for each skill
  the trainee currently owns (in ``chara.skill_array``)

We report three estimates:
- **floor** = score if the player spends *zero* additional SP (already-owned
  skills only). The realistic minimum.
- **naive ceiling** = score if unspent SP converts at flat 2.0×. Cheap upper
  bound; overestimates for players with mostly-bad hints.
- **smart ceiling** (planned_score) = knapsack-optimal skill purchase within
  the SP budget, using the actual (sp_cost, grade_value) per hint. This is
  the honest upper bound: 'buy the highest-value-per-SP skills first'.

Rank tiers come from ``masters.json.rank_tiers`` (98 tiers, sourced from
the game's ``single_mode_rank`` table).
"""
from __future__ import annotations

from dataclasses import dataclass

from .data.five_status_score import FIVE_STATUS_FINAL_SCORE
from .lookups import load_masters, skill_from_hint


PT_SCORE_RATE_DEFAULT = 2.0
FIVE_STATS = ("speed", "stamina", "power", "guts", "wiz")


@dataclass(frozen=True)
class SkillPurchase:
    """One skill the optimal purchase would buy."""
    skill_id: int
    name: str
    sp_cost: int
    grade_value: int
    value_per_sp: float


@dataclass(frozen=True)
class ScoreEstimate:
    """Score decomposition for one run.

    Three ceilings: (1) naive_ceiling = flat 2.0×SP, (2) planned_score =
    knapsack-optimal purchase from actual hints. planned_score is the
    honest upper bound; naive_ceiling is a quick sanity check.
    """
    stat_score: int              # Σ FiveStatusFinalScore[stat]
    owned_skill_score: int       # Σ grade_value for owned skills
    unspent_sp: int              # SP left to spend
    sp_ceiling_bonus: int        # int(ptScoreRate × unspent_sp) — naive max
    floor: int                   # stat + owned_skill (no more SP spent)
    naive_ceiling: int           # floor + sp_ceiling_bonus
    planned_score: int           # floor + optimal knapsack purchase
    sp_spent_in_plan: int        # SP actually used by knapsack
    plan: tuple[SkillPurchase, ...]  # which skills the optimum buys
    rank_floor: int
    rank_planned: int            # rank tier of planned_score

    # For backwards-compat with earlier detail template using .ceiling
    @property
    def ceiling(self) -> int:
        return self.planned_score

    @property
    def rank_ceiling(self) -> int:
        return self.rank_planned

    def as_dict(self) -> dict:
        return {
            "stat_score": self.stat_score,
            "owned_skill_score": self.owned_skill_score,
            "unspent_sp": self.unspent_sp,
            "sp_ceiling_bonus": self.sp_ceiling_bonus,
            "floor": self.floor,
            "naive_ceiling": self.naive_ceiling,
            "planned_score": self.planned_score,
            "sp_spent_in_plan": self.sp_spent_in_plan,
            "plan": [
                {"skill_id": p.skill_id, "name": p.name,
                 "sp_cost": p.sp_cost, "grade_value": p.grade_value,
                 "value_per_sp": round(p.value_per_sp, 2)}
                for p in self.plan
            ],
            "rank_floor": self.rank_floor,
            "rank_planned": self.rank_planned,
        }


def _clip_stat(stat: int, cap: int) -> int:
    """Match the game: score is looked up at min(stat, cap), clamped to the
    table's index range [0, 2800]."""
    v = min(stat, cap)
    if v < 0:
        return 0
    if v > 2800:
        return 2800
    return v


def _stat_score(stats: dict[str, int], caps: dict[str, int]) -> int:
    """Σ FiveStatusFinalScore[min(stat, cap)] across the 5 stats."""
    total = 0
    for key in FIVE_STATS:
        s = int(stats.get(key, 0) or 0)
        c = int(caps.get(key, 0) or 2800)
        total += FIVE_STATUS_FINAL_SCORE[_clip_stat(s, c)]
    return total


def _owned_skill_score(skill_ids: list[int]) -> int:
    """Σ skill_data.grade_value for each owned skill."""
    m = load_masters()
    skills = m.get("skills", {})
    total = 0
    for sid in skill_ids:
        s = skills.get(str(sid))
        if s:
            total += int(s.get("grade_value", 0) or 0)
    return total


def optimal_purchase(
    available_skill_ids: list[int],
    owned_skill_ids: list[int],
    sp_budget: int,
) -> tuple[list[SkillPurchase], int, int]:
    """Solve 0/1 knapsack: max Σ grade_value subject to Σ sp_cost ≤ budget,
    over hint skills the player can buy (available - already owned).

    Returns (chosen list, total_value_added, sp_used).
    """
    m = load_masters()
    skills = m.get("skills", {})
    owned = set(owned_skill_ids)

    # Dedup + filter to skills with a valid cost that aren't already owned
    items: list[tuple[int, int, int]] = []  # (skill_id, cost, value)
    seen: set[int] = set()
    for sid in available_skill_ids:
        if sid in owned or sid in seen or sid == 0:
            continue
        s = skills.get(str(sid))
        if not s:
            continue
        cost = s.get("sp_cost")
        val = s.get("grade_value")
        if not cost or not val or cost <= 0:
            continue
        seen.add(sid)
        items.append((sid, int(cost), int(val)))

    if not items or sp_budget <= 0:
        return [], 0, 0

    # 0/1 knapsack — SP granularity is fine at 1 (SP costs are integers).
    # Budgets are usually 3-4K, item counts <100, so ~400K cells max.
    n = len(items)
    dp = [[0] * (sp_budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        _, cost, val = items[i - 1]
        row = dp[i]
        prev = dp[i - 1]
        for w in range(sp_budget + 1):
            row[w] = prev[w]
            if cost <= w and prev[w - cost] + val > row[w]:
                row[w] = prev[w - cost] + val

    # Backtrack to recover the chosen items
    chosen_ids: list[int] = []
    w = sp_budget
    total_value = dp[n][w]
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            sid, cost, _ = items[i - 1]
            chosen_ids.append(sid)
            w -= cost
    sp_used = sp_budget - w

    # Enrich to SkillPurchase, sort by best value-per-SP first
    plan: list[SkillPurchase] = []
    for sid in chosen_ids:
        s = skills[str(sid)]
        cost = int(s["sp_cost"])
        val = int(s["grade_value"])
        plan.append(SkillPurchase(
            skill_id=sid,
            name=s.get("name", f"?skill:{sid}"),
            sp_cost=cost,
            grade_value=val,
            value_per_sp=val / cost if cost else 0.0,
        ))
    plan.sort(key=lambda p: (-p.value_per_sp, -p.grade_value))
    return plan, total_value, sp_used


def _rank_for_score(score: int) -> int:
    """Look up numeric rank tier for a score. Returns highest tier if score
    exceeds all thresholds; returns 1 for negative/zero scores."""
    m = load_masters()
    tiers = m.get("rank_tiers", [])
    if not tiers:
        return 0
    if score <= 0:
        return tiers[0]["rank"]
    for tier in tiers:
        if tier["min"] <= score <= tier["max"]:
            return tier["rank"]
    return tiers[-1]["rank"]


def estimate(*,
             stats: dict[str, int],
             caps: dict[str, int],
             owned_skill_ids: list[int],
             available_hint_skill_ids: list[int] | None = None,
             unspent_sp: int,
             pt_score_rate: float = PT_SCORE_RATE_DEFAULT) -> ScoreEstimate:
    """Compute floor + both ceiling estimates for one captured state."""
    stat = _stat_score(stats, caps)
    owned = _owned_skill_score(owned_skill_ids)
    sp_bonus = int(pt_score_rate * unspent_sp)
    floor = stat + owned
    naive_ceiling = floor + sp_bonus

    if available_hint_skill_ids:
        plan, plan_value, sp_used = optimal_purchase(
            available_hint_skill_ids, owned_skill_ids, unspent_sp
        )
    else:
        plan, plan_value, sp_used = [], 0, 0

    planned_score = floor + plan_value
    return ScoreEstimate(
        stat_score=stat,
        owned_skill_score=owned,
        unspent_sp=unspent_sp,
        sp_ceiling_bonus=sp_bonus,
        floor=floor,
        naive_ceiling=naive_ceiling,
        planned_score=planned_score,
        sp_spent_in_plan=sp_used,
        plan=tuple(plan),
        rank_floor=_rank_for_score(floor),
        rank_planned=_rank_for_score(planned_score),
    )


def estimate_from_run_json(raw: dict) -> ScoreEstimate:
    """Build a ScoreEstimate directly from a run's raw JSON. Includes the
    knapsack optimum over all skill hints captured across sources."""
    chara = raw["SingleModeChara"][0]
    stats = {k: int(chara.get(k, 0) or 0) for k in FIVE_STATS}
    caps = {k: int(chara.get(f"max_{k}", 0) or 0) for k in FIVE_STATS}
    owned = [int(s.get("skill_id", 0) or 0) for s in chara.get("skill_array", []) or []]

    # Collect all skill hints across all GainInfo sources — map each
    # (group_id, rarity) to its canonical skill_id.
    unspent_sp = 0
    hint_skill_ids: list[int] = []
    seen: set[tuple[int, int]] = set()
    for gi in raw.get("GainInfo", []) or []:
        unspent_sp += int(gi.get("<SkillPoint>k__BackingField", 0) or 0)
        for t in gi.get("<SkillTipsArray>k__BackingField", []) or []:
            if not isinstance(t, dict):
                continue
            key = (int(t.get("group_id", 0) or 0), int(t.get("rarity", 0) or 0))
            if key in seen or key[0] == 0:
                continue
            seen.add(key)
            sid, _ = skill_from_hint(*key)
            if sid:
                hint_skill_ids.append(sid)

    return estimate(
        stats=stats,
        caps=caps,
        owned_skill_ids=owned,
        available_hint_skill_ids=hint_skill_ids,
        unspent_sp=unspent_sp,
    )

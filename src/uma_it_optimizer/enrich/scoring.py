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

We report **floor** and **ceiling** estimates:
- **floor** = score if the player spends *zero* additional SP (already-owned
  skills only). The realistic minimum.
- **ceiling** = score if the player spends *all* unspent SP at the default
  rate (2.0 × SP). Assumes optimal spending — no accounting for skill costs
  or per-skill grade_value differences. Genuine upper bound of what SP
  can add to score.

The gap between floor and ceiling tells you *how much of the outcome is
still in the player's hands* — a big gap means "your skill picks matter a
lot for this run".

Rank tiers come from ``masters.json.rank_tiers`` (98 tiers, sourced from
the game's ``single_mode_rank`` table). Numeric rank only — letter grades
(SS/S+/etc.) are rendered as UI assets in the game, not text_data.
"""
from __future__ import annotations

from dataclasses import dataclass

from .data.five_status_score import FIVE_STATUS_FINAL_SCORE
from .lookups import load_masters


PT_SCORE_RATE_DEFAULT = 2.0
FIVE_STATS = ("speed", "stamina", "power", "guts", "wiz")


@dataclass(frozen=True)
class ScoreEstimate:
    """Score decomposition for one run."""
    stat_score: int              # Σ FiveStatusFinalScore[stat]
    owned_skill_score: int       # Σ grade_value for skills in chara.skill_array
    unspent_sp: int              # SP the player can still spend
    sp_ceiling_bonus: int        # int(ptScoreRate × unspent_sp) — realistic max
    floor: int                   # stat + owned_skill (no SP spent)
    ceiling: int                 # stat + owned_skill + sp_ceiling
    rank_floor: int              # rank tier corresponding to floor
    rank_ceiling: int            # rank tier corresponding to ceiling

    def as_dict(self) -> dict:
        return {
            "stat_score": self.stat_score,
            "owned_skill_score": self.owned_skill_score,
            "unspent_sp": self.unspent_sp,
            "sp_ceiling_bonus": self.sp_ceiling_bonus,
            "floor": self.floor,
            "ceiling": self.ceiling,
            "rank_floor": self.rank_floor,
            "rank_ceiling": self.rank_ceiling,
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
             unspent_sp: int,
             pt_score_rate: float = PT_SCORE_RATE_DEFAULT) -> ScoreEstimate:
    """Compute floor/ceiling scores for one captured run state."""
    stat = _stat_score(stats, caps)
    owned = _owned_skill_score(owned_skill_ids)
    sp_bonus = int(pt_score_rate * unspent_sp)
    floor = stat + owned
    ceiling = floor + sp_bonus
    return ScoreEstimate(
        stat_score=stat,
        owned_skill_score=owned,
        unspent_sp=unspent_sp,
        sp_ceiling_bonus=sp_bonus,
        floor=floor,
        ceiling=ceiling,
        rank_floor=_rank_for_score(floor),
        rank_ceiling=_rank_for_score(ceiling),
    )


def estimate_from_run_json(raw: dict) -> ScoreEstimate:
    """Convenience: build a ScoreEstimate directly from a run's raw JSON
    (as produced by dump_it_run.py)."""
    chara = raw["SingleModeChara"][0]
    stats = {k: int(chara.get(k, 0) or 0) for k in FIVE_STATS}
    caps = {k: int(chara.get(f"max_{k}", 0) or 0) for k in FIVE_STATS}
    owned = [int(s.get("skill_id", 0) or 0) for s in chara.get("skill_array", []) or []]
    unspent_sp = 0
    for gi in raw.get("GainInfo", []) or []:
        unspent_sp += int(gi.get("<SkillPoint>k__BackingField", 0) or 0)
    return estimate(
        stats=stats,
        caps=caps,
        owned_skill_ids=owned,
        unspent_sp=unspent_sp,
    )

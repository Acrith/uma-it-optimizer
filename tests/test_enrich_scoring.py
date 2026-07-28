from __future__ import annotations

import json
from pathlib import Path

import pytest

from uma_it_optimizer.enrich.scoring import (
    FIVE_STATS,
    PT_SCORE_RATE_DEFAULT,
    _rank_for_score,
    estimate,
    estimate_from_run_json,
)
from uma_it_optimizer.enrich.data.five_status_score import FIVE_STATUS_FINAL_SCORE


REAL_RUN = (
    Path(__file__).parent.parent
    / "IT-references"
    / "allRuns"
    / "20260725T185207_scen2_uma103201.json"
)


def test_score_table_length_and_shape():
    """Sanity: 2801 monotonically-non-decreasing ints from 0."""
    assert len(FIVE_STATUS_FINAL_SCORE) == 2801
    assert FIVE_STATUS_FINAL_SCORE[0] == 0
    for i in range(1, len(FIVE_STATUS_FINAL_SCORE)):
        assert FIVE_STATUS_FINAL_SCORE[i] >= FIVE_STATUS_FINAL_SCORE[i - 1]


def test_estimate_zero_stats_gives_zero_stat_score():
    e = estimate(stats={k: 0 for k in FIVE_STATS},
                 caps={k: 1200 for k in FIVE_STATS},
                 owned_skill_ids=[],
                 unspent_sp=0)
    assert e.stat_score == 0
    assert e.owned_skill_score == 0
    assert e.floor == 0
    assert e.ceiling == 0


def test_estimate_stat_lookup_matches_table():
    # Single-stat scenario: only speed = 1000, cap high enough
    e = estimate(stats={"speed": 1000, "stamina": 0, "power": 0, "guts": 0, "wiz": 0},
                 caps={k: 2000 for k in FIVE_STATS},
                 owned_skill_ids=[],
                 unspent_sp=0)
    assert e.stat_score == FIVE_STATUS_FINAL_SCORE[1000]


def test_estimate_stat_clamped_at_cap():
    # stat exceeds cap → uses cap value
    e = estimate(stats={"speed": 2000, "stamina": 0, "power": 0, "guts": 0, "wiz": 0},
                 caps={"speed": 1200, "stamina": 2000, "power": 2000, "guts": 2000, "wiz": 2000},
                 owned_skill_ids=[],
                 unspent_sp=0)
    assert e.stat_score == FIVE_STATUS_FINAL_SCORE[1200]


def test_estimate_sp_ceiling_bonus():
    # 100 SP at default rate 2.0 → 200 bonus points
    e = estimate(stats={k: 0 for k in FIVE_STATS},
                 caps={k: 1200 for k in FIVE_STATS},
                 owned_skill_ids=[],
                 unspent_sp=100)
    assert e.sp_ceiling_bonus == int(PT_SCORE_RATE_DEFAULT * 100)
    assert e.ceiling - e.floor == e.sp_ceiling_bonus


def test_estimate_owned_skill_included_in_floor():
    # Agnes' unique skill id 100321 has grade_value = 340 (verified against DB)
    e = estimate(stats={k: 0 for k in FIVE_STATS},
                 caps={k: 1200 for k in FIVE_STATS},
                 owned_skill_ids=[100321],
                 unspent_sp=0)
    assert e.owned_skill_score == 340
    assert e.floor == 340


def test_rank_lookup_boundaries():
    # First tier is 0-299 (rank 1); score 0 → rank 1
    assert _rank_for_score(0) == 1
    # A high score should return the highest tier
    assert _rank_for_score(10**8) == 98


@pytest.mark.skipif(not REAL_RUN.exists(), reason="no real run available")
def test_estimate_from_real_unity_cup_run():
    raw = json.loads(REAL_RUN.read_text(encoding="utf-8"))
    e = estimate_from_run_json(raw)

    # Sanity: floor < ceiling (there IS unspent SP)
    assert e.floor < e.ceiling
    # Ranks should be in the valid 1..98 range
    assert 1 <= e.rank_floor <= 98
    assert 1 <= e.rank_ceiling <= 98
    # Ceiling rank ≥ floor rank (higher score → equal or higher tier)
    assert e.rank_ceiling >= e.rank_floor
    # Agnes' unique skill 100321 (grade_value=340) is her only owned skill
    assert e.owned_skill_score == 340

from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.enrich.aggregations import by_deck
from uma_it_optimizer.enrich.run_metrics import summarize_directory


REAL_RUNS_DIR = Path(__file__).parent.parent / "IT-references" / "allRuns"


@pytest.mark.skipif(not REAL_RUNS_DIR.exists(), reason="no real runs dir")
def test_by_deck_aggregates_real_runs():
    runs = [r for r in summarize_directory(REAL_RUNS_DIR)
            if r.run_state == "completed"]
    aggs = by_deck(runs)
    assert aggs, "should produce at least one deck aggregate"

    # The favored deck e0a951 was played 8 times across 3 trainees.
    top = next((a for a in aggs if a.deck_hash == "e0a951"), None)
    assert top is not None, "expected deck e0a951 to be present"
    assert top.runs == 8
    assert set(top.trainees) == {"Agnes Tachyon", "Narita Brian", "Oguri Cap"}
    # All runs of e0a951 were on Our Grand Concert
    assert top.scenarios == ("Our Grand Concert",)
    assert top.best_fans >= top.avg_fans      # best >= avg by definition


@pytest.mark.skipif(not REAL_RUNS_DIR.exists(), reason="no real runs dir")
def test_by_deck_sort_order():
    runs = [r for r in summarize_directory(REAL_RUNS_DIR)
            if r.run_state == "completed"]
    aggs = by_deck(runs)
    # sorted by (best_score desc, runs desc) — highest-ceiling decks first
    for prev, curr in zip(aggs, aggs[1:], strict=False):
        assert (prev.best_score > curr.best_score) or (
            prev.best_score == curr.best_score and prev.runs >= curr.runs
        )


@pytest.mark.skipif(not REAL_RUNS_DIR.exists(), reason="no real runs dir")
def test_deck_type_composition_populated():
    runs = [r for r in summarize_directory(REAL_RUNS_DIR)
            if r.run_state == "completed"]
    aggs = by_deck(runs)
    for a in aggs:
        assert sum(a.type_composition.values()) == 6, (
            f"deck {a.deck_hash}: 6 support cards, got composition "
            f"{a.type_composition}"
        )

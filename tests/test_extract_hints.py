from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract import extract_hints_scroll

FIXTURES = Path(__file__).parent / "fixtures"


def _skill_names(entries: list[dict]) -> set[str]:
    return {e["skill"] for e in entries}


def test_hints_scroll_1_run_1_names_and_sections() -> None:
    """v0.1: skill NAMES + section grouping. Levels are best-effort
    (~50% detection on messy Hint Lvl badges) — checked separately.
    """
    path = FIXTURES / "hints_01_scroll_1.png"
    if not path.exists():
        pytest.skip("fixture missing")
    result = extract_hints_scroll(path)

    # Inspiration section — all 9 skills the character was inspired with
    insp = _skill_names(result["from_inspiration"])
    assert insp == {
        "Triumphant Pulse",
        "Barcarole of Blessings",
        "Pace Chaser Corners",
        "Homestretch Haste",
        "Hydrate",
        "Glittering Star",
        "Hanshin Racecourse",
        "Corner Recovery",
        "Firm Conditions",
    }

    # Support-cards section on this scroll: Nishino Flower's 3 + one row
    # of the next card. Names should include Nishino's teachings.
    cards = _skill_names(result["from_support_cards"])
    # The trailing "0" in some names is OCR reading the "○" variant
    # marker as a zero — v0.1 accepts both spellings.
    assert "Standard Distance" in cards
    assert any("Firm Conditions" in name for name in cards)
    assert any("Hanshin Racecourse" in name for name in cards)

    assert result["from_events"] == []
    assert result["unassigned"] == []


def test_hints_scroll_1_run_1_reads_some_levels() -> None:
    """Weak assertion: at least a handful of hint levels are recovered.
    Exact per-skill accuracy is a v0.2 workstream.
    """
    path = FIXTURES / "hints_01_scroll_1.png"
    if not path.exists():
        pytest.skip("fixture missing")
    result = extract_hints_scroll(path)
    all_entries = result["from_inspiration"] + result["from_support_cards"]
    read_levels = [e for e in all_entries if e["level"] is not None]
    assert len(read_levels) >= 4, f"expected ≥4 levels, got {len(read_levels)}"

    # Spot-check a few we know the extractor gets right today.
    by_name = {e["skill"]: e["level"] for e in result["from_inspiration"]}
    assert by_name.get("Triumphant Pulse") == 2
    assert by_name.get("Pace Chaser Corners") == "max"

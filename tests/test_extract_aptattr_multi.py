from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract import extract_aptattr

FIXTURES = Path(__file__).parent / "fixtures"

# Truth from a real Agnes Tachyon Unity Cup run (Run 1 in the schema examples).
EXPECTED_CARDS = [
    {"level": 45, "is_friend": False,
     "contribs": {"speed": 11, "stamina": 21, "power": 46,
                  "guts": 11, "wit": 11, "skill_pts": 57}},
    {"level": 50, "is_friend": False,
     "contribs": {"speed":  9, "stamina": 43, "power": 48,
                  "guts":  9, "wit":  9, "skill_pts": 54}},
    {"level": 45, "is_friend": False,
     "contribs": {"speed": 19, "stamina": 11, "power": 11,
                  "guts": 11, "wit": 64, "skill_pts": 78}},
    {"level": 45, "is_friend": False,
     "contribs": {"speed": 56, "stamina": 11, "power": 24,
                  "guts": 11, "wit": 11, "skill_pts": 65}},
    {"level": 45, "is_friend": False,
     "contribs": {"speed": 41, "stamina": 12, "power": 30,
                  "guts": 12, "wit": 12, "skill_pts": 75}},
    {"level": None, "is_friend": True,   # friend cards show "Friend:" not "Lvl 50"
     "contribs": {"speed": 46, "stamina": 11, "power": 28,
                  "guts": 11, "wit": 11, "skill_pts": 66}},
]


def test_aptattr_run_1_all_scrolls_merged() -> None:
    scrolls = [FIXTURES / f"aptattr_01_scroll_{i}.png" for i in (1, 2, 3)]
    for p in scrolls:
        if not p.exists():
            pytest.skip(f"{p.name} not present")

    result = extract_aptattr(scrolls)

    # Aptitude before/after — same as scroll-1 test.
    assert result["aptitude_after"]["distance"]["long"] == "A"
    assert result["aptitude_before"]["style"]["front"] == "E"

    # Inspiration bonuses.
    assert result["inspiration_bonuses"]["speed"] == {"total": 38, "delta": 13}
    assert result["inspiration_bonuses"]["stamina"] == {"total": 177, "delta": 64}

    # Event totals — all six stats correct.
    assert result["event_totals"] == {
        "speed":     {"total": 566,  "delta": 0},
        "stamina":   {"total": 303,  "delta": 0},
        "power":     {"total": 333,  "delta": 0},
        "guts":      {"total": 207,  "delta": 0},
        "wit":       {"total": 456,  "delta": 0},
        "skill_pts": {"total": 2999, "delta": 0},
    }

    # All 6 cards, in slot order, deduped across scrolls.
    cards = result["support_card_contribs"]
    assert len(cards) == 6
    for i, card in enumerate(cards):
        assert card["slot"] == i + 1
        assert card["level"] == EXPECTED_CARDS[i]["level"]
        assert card["is_friend"] == EXPECTED_CARDS[i]["is_friend"]
        assert card["contribs"] == EXPECTED_CARDS[i]["contribs"], (
            f"slot {i+1} contribs mismatch"
        )

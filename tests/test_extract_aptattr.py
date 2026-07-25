from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract import extract_aptattr_scroll_1

FIXTURES = Path(__file__).parent / "fixtures"

# Aptitude blocks: base grade letters only (no +/- appears on aptitudes
# in-game). Both runs use the same character so aptitudes are identical.
APTITUDE_BEFORE = {
    "track":    {"turf": "A", "dirt": "G"},
    "distance": {"sprint": "G", "mile": "D", "medium": "A", "long": "B"},
    "style":    {"front": "E", "pace": "A", "late": "B", "end": "F"},
}
APTITUDE_AFTER = {
    "track":    {"turf": "A", "dirt": "G"},
    "distance": {"sprint": "G", "mile": "B", "medium": "A", "long": "A"},
    "style":    {"front": "D", "pace": "A", "late": "B", "end": "F"},
}

CASES = [
    (
        "aptattr_01_scroll_1.png",
        {
            "aptitude_before": APTITUDE_BEFORE,
            "aptitude_after": APTITUDE_AFTER,
            "inspiration_bonuses": {
                "speed":   {"total": 38,  "delta": 13},
                "stamina": {"total": 177, "delta": 64},
                "power":   {"total": 115, "delta": 43},
                "guts":    {"total": 0,   "delta": 0},
                "wit":     {"total": 0,   "delta": 0},
            },
        },
    ),
    (
        "aptattr_02_scroll_1.png",
        {
            "aptitude_before": APTITUDE_BEFORE,
            "aptitude_after": APTITUDE_AFTER,
            "inspiration_bonuses": {
                "speed":   {"total": 42,  "delta": 23},
                "stamina": {"total": 165, "delta": 64},
                "power":   {"total": 115, "delta": 44},
                "guts":    {"total": 0,   "delta": 0},
                "wit":     {"total": 0,   "delta": 1},
            },
        },
    ),
]


@pytest.mark.parametrize("fixture_name,expected", CASES)
def test_extract_aptattr_scroll_1(fixture_name: str, expected: dict) -> None:
    path = FIXTURES / fixture_name
    if not path.exists():
        pytest.skip(f"{fixture_name} not present (see tests/fixtures/README.md)")
    got = extract_aptattr_scroll_1(path)
    assert got == expected

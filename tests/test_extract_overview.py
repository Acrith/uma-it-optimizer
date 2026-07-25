from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract import extract_overview

FIXTURES = Path(__file__).parent / "fixtures"

# (fixture filename, expected outcome fragment). Grades are BASE LETTERS
# only — +/- suffix detection is a v0.2 workstream (see grades.py).
CASES = [
    (
        "overview_01.png",
        {
            "trainee": {"name": "Agnes Tachyon", "title": "tach-nology"},
            "stats": {"speed": 888, "stamina": 684, "power": 730, "guts": 370,
                      "wit": 684, "skill_pts_remaining": 3394},
            "stat_grades": {"speed": "A", "stamina": "B", "power": "B",
                            "guts": "D", "wit": "B"},
            "aptitude_after": {
                "track": {"turf": "A", "dirt": "G"},
                "distance": {"sprint": "G", "mile": "B", "medium": "A", "long": "A"},
                "style": {"front": "D", "pace": "A", "late": "B", "end": "F"},
            },
            "career": {"races": 41, "wins": 41, "fans": 1013200},
        },
    ),
    (
        "overview_02.png",
        {
            "trainee": {"name": "Agnes Tachyon", "title": "tach-nology"},
            "stats": {"speed": 822, "stamina": 582, "power": 806, "guts": 400,
                      "wit": 776, "skill_pts_remaining": 3551},
            "stat_grades": {"speed": "A", "stamina": "C", "power": "A",
                            "guts": "C", "wit": "B"},
            "aptitude_after": {
                "track": {"turf": "A", "dirt": "G"},
                "distance": {"sprint": "G", "mile": "B", "medium": "A", "long": "A"},
                "style": {"front": "D", "pace": "A", "late": "B", "end": "F"},
            },
            "career": {"races": 41, "wins": 41, "fans": 1028252},
        },
    ),
]


@pytest.mark.parametrize("fixture_name,expected", CASES)
def test_extract_overview(fixture_name: str, expected: dict) -> None:
    path = FIXTURES / fixture_name
    if not path.exists():
        pytest.skip(f"{fixture_name} not present (see tests/fixtures/README.md)")
    got = extract_overview(path)
    assert got == expected

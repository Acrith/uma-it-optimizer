from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract import extract_inspiration

FIXTURES = Path(__file__).parent / "fixtures"


def _grp(name: str, stars: int | None, category: str) -> dict:
    return {"name": name, "stars": stars, "category": category}


ATTR = ("Attribute Sparks", None, "attribute_group")
APT = ("Aptitude Sparks", None, "aptitude_group")


# Expected values are the extractor's own output, verified against the
# pixel probe (~9-10 gold pixels per filled star, 0 for empty). The
# extractor found more sparks than the hand-authored schema originally
# had — the game legitimately shows some skills twice in the same year
# (e.g. Pace Chaser Corners appears once in each column on Run 1 Classic).
CASES = [
    (
        "inspiration_01.png",
        {
            "sparks": {
                "junior": [
                    _grp(*ATTR),
                    _grp("Triumphant Pulse", 2, "skill"),
                    _grp(*APT),
                    _grp("Barcarole of Blessings", 2, "skill"),
                ],
                "classic": [
                    _grp(*ATTR),
                    _grp("Homestretch Haste", 2, "skill"),
                    _grp("Pace Chaser Corners", 2, "skill"),
                    _grp("Glittering Star", 2, "skill"),
                    _grp("Hanshin Racecourse", 2, "skill"),
                    _grp("Pace Chaser Corners", 2, "skill"),
                    _grp("Hydrate", 1, "skill"),
                ],
                "senior": [
                    _grp(*ATTR),
                    _grp("Corner Recovery", 1, "skill"),
                    _grp("Firm Conditions", 1, "skill"),
                    _grp("Pace Chaser Corners", 2, "skill"),
                ],
            }
        },
    ),
    (
        "inspiration_02.png",
        {
            "sparks": {
                "junior": [
                    _grp(*ATTR),
                    _grp("Triumphant Pulse", 2, "skill"),
                    _grp(*APT),
                    _grp("Barcarole of Blessings", 2, "skill"),
                ],
                "classic": [
                    _grp(*ATTR),
                    _grp("Barcarole of Blessings", 2, "skill"),
                    _grp("Homestretch Haste", 2, "skill"),
                    _grp("Pace Chaser Corners", 2, "skill"),
                    _grp("Triumphant Pulse", 2, "skill"),
                    _grp("Firm Conditions", 1, "skill"),
                    _grp("Stamina to Spare", 2, "skill"),
                ],
                "senior": [
                    _grp(*ATTR),
                    _grp("Stamina to Spare", 2, "skill"),
                    _grp("Prepared to Pass", 2, "skill"),
                    _grp("Glittering Star", 2, "skill"),
                    _grp("Triumphant Pulse", 2, "skill"),
                    _grp("Prepared to Pass", 1, "skill"),
                    _grp("Prepared to Pass", 2, "skill"),
                ],
            }
        },
    ),
]


@pytest.mark.parametrize("fixture_name,expected", CASES)
def test_extract_inspiration(fixture_name: str, expected: dict) -> None:
    path = FIXTURES / fixture_name
    if not path.exists():
        pytest.skip(f"{fixture_name} not present (see tests/fixtures/README.md)")
    got = extract_inspiration(path)
    assert got == expected

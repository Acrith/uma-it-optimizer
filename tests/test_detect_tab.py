from __future__ import annotations

from pathlib import Path

import pytest

from uma_it_optimizer.extract.tab import TabKind, detect_tab

FIXTURES = Path(__file__).parent / "fixtures"

CASES = [
    ("overview_01.png",      TabKind.OVERVIEW),
    ("overview_02.png",      TabKind.OVERVIEW),
    ("career_01.png",        TabKind.CAREER),
    ("aptattr_01_scroll_1.png", TabKind.APTATTR),
    ("aptattr_01_scroll_2.png", TabKind.APTATTR),
    ("aptattr_02_scroll_1.png", TabKind.APTATTR),
    ("hints_01_scroll_1.png",   TabKind.HINTS),
    ("inspiration_01.png",   TabKind.INSPIRATION),
]


@pytest.mark.parametrize("fixture_name,expected", CASES)
def test_detect_tab(fixture_name: str, expected: TabKind) -> None:
    path = FIXTURES / fixture_name
    if not path.exists():
        pytest.skip(f"{fixture_name} not present")
    assert detect_tab(path) == expected

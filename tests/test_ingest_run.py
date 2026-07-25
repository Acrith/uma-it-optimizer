from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from uma_it_optimizer.extract import TabKind, ingest_run

FIXTURES = Path(__file__).parent / "fixtures"

# Fixtures we assemble a fake run folder from — mixed tabs, ALT+PRTSCR-
# style random names so we prove content-based tab detection routes them.
RUN_FIXTURES = [
    ("overview_01.png",         "Screenshot (1).png"),
    ("career_01.png",           "Screenshot (2).png"),
    ("aptattr_01_scroll_1.png", "Screenshot (3).png"),
    ("aptattr_01_scroll_2.png", "Screenshot (4).png"),
    ("hints_01_scroll_1.png",   "Screenshot (5).png"),
    ("inspiration_01.png",      "Screenshot (6).png"),
]


def _skip_if_any_missing() -> None:
    missing = [src for src, _ in RUN_FIXTURES if not (FIXTURES / src).exists()]
    if missing:
        pytest.skip(f"fixtures missing: {missing}")


def test_ingest_run_groups_and_extracts(tmp_path: Path) -> None:
    _skip_if_any_missing()
    for src, dst in RUN_FIXTURES:
        shutil.copy(FIXTURES / src, tmp_path / dst)

    result = ingest_run(tmp_path)

    grouped = result["grouped"]
    assert set(grouped) == {
        TabKind.OVERVIEW, TabKind.CAREER, TabKind.APTATTR,
        TabKind.HINTS, TabKind.INSPIRATION,
    }
    assert len(grouped[TabKind.APTATTR]) == 2
    assert len(grouped[TabKind.OVERVIEW]) == 1

    extracted = result["extracted"]
    # Overview fields present
    assert extracted["trainee"]["name"] == "Agnes Tachyon"
    assert extracted["stats"]["speed"] == 888
    # Aptattr scroll-1 fields present
    assert extracted["inspiration_bonuses"]["speed"]["total"] == 38
    assert extracted["aptitude_after"]["distance"]["long"] == "A"

    # Inspiration extractor is wired in — verify a couple of fields.
    assert extracted["sparks"]["junior"][1]["name"] == "Triumphant Pulse"
    assert extracted["sparks"]["junior"][1]["stars"] == 2

    # Hints extractor is wired in — verify at least one inspiration skill lands.
    hints_insp = {e["skill"] for e in extracted["skill_hints_earned"]["from_inspiration"]}
    assert "Triumphant Pulse" in hints_insp

    # Aptattr multi-scroll pipeline runs and populates support_card_contribs.
    assert len(extracted["support_card_contribs"]) >= 1
    assert extracted["support_card_contribs"][0]["slot"] == 1

    # Career should still be flagged as intentionally skipped.
    reasons = " | ".join(result["skipped"])
    assert "career" in reasons

"""merge_masters: a fresh game dump merged into the site's masters, never replacing it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "memory_extractor"))
from merge_masters import merge  # noqa: E402


def test_the_game_wins_new_ids_are_added_and_the_sites_extras_stay():
    site = {
        "_meta": {"generated_at": "2026-08-07"},
        "skills": {"1": {"name": "Flash Forward", "grade_value": 100, "note": "site-only field"},
                   "2": {"name": "Ahead of Global"}},
        "rank_tiers": [1, 2],
        "campaigns": {"9": {"title": "site-only table"}},
    }
    fresh = {
        "_meta": {"source_mdb": "master.mdb", "source_mtime": "2026-09-28"},
        "skills": {"1": {"name": "Lightning Surge", "grade_value": 100}, "3": {"name": "New"}},
        "rank_tiers": [1, 2, 3],
    }
    merged, report = merge(site, fresh)
    assert merged["skills"]["1"] == {
        "name": "Lightning Surge", "grade_value": 100, "note": "site-only field"}
    assert merged["skills"]["2"] == {"name": "Ahead of Global"}, "kept: the site had it first"
    assert merged["skills"]["3"] == {"name": "New"}
    assert merged["rank_tiers"] == [1, 2, 3]
    assert merged["campaigns"] == site["campaigns"]
    assert report["skills"] == {"added": 1, "updated": 1, "kept": 1}
    assert merged["_meta"]["generated_at"] == "2026-08-07"
    assert merged["_meta"]["merged_mdb_mtime"] == "2026-09-28"


def test_merging_the_same_dump_twice_changes_nothing_more():
    site = {"skills": {"1": {"name": "A"}}}
    fresh = {"skills": {"1": {"name": "B"}, "2": {"name": "C"}}}
    once, _ = merge(site, fresh)
    twice, report = merge(once, fresh)
    assert twice["skills"] == once["skills"]
    assert report["skills"] == {"added": 0, "updated": 0, "kept": 0}

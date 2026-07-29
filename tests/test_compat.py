"""Verify base pair compat against Special Week reference values.

These are hand-verified numbers from a community source (2026-07):
Special Week's top-10 pair compat should be exactly:
  Narita Brian 37, Nice Nature 37, T.M. Opera O 35, Seiun Sky 34,
  Gold Ship 33, Mejiro McQueen 33, Grass Wonder 31, Winning Ticket 31,
  Super Creek 31, Matikanetannhauser 31.

If this test breaks, either a game update changed the
`succession_relation*` tables or the bundled masters.json is stale.
"""
from __future__ import annotations

import pytest

from uma_it_optimizer.enrich.compat import base_pair_score


SPECIAL_WEEK = 1001


REFERENCE_PAIRS = {
    1016: ("Narita Brian", 37),
    1060: ("Nice Nature", 37),
    1015: ("T.M. Opera O", 35),
    1020: ("Seiun Sky", 34),
    1007: ("Gold Ship", 33),
    1013: ("Mejiro McQueen", 33),
    1011: ("Grass Wonder", 31),
    1035: ("Winning Ticket", 31),
    1045: ("Super Creek", 31),
    1062: ("Matikanetannhauser", 31),
}


@pytest.mark.parametrize("chara_id,expected", [
    (cid, val) for cid, (_, val) in REFERENCE_PAIRS.items()
])
def test_special_week_pair_compat(chara_id: int, expected: int) -> None:
    """Each SW pair matches the hand-verified reference number exactly."""
    assert base_pair_score(SPECIAL_WEEK, chara_id) == expected


def test_pair_compat_symmetric() -> None:
    """base_pair_score(a, b) == base_pair_score(b, a) — set intersection
    should be commutative by construction, guard against future edits."""
    for cid in REFERENCE_PAIRS:
        assert base_pair_score(SPECIAL_WEEK, cid) == base_pair_score(cid, SPECIAL_WEEK)


def test_pair_compat_self_is_zero() -> None:
    """Same chara vs itself should be zero (guarded early exit)."""
    assert base_pair_score(SPECIAL_WEEK, SPECIAL_WEEK) == 0

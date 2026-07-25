from __future__ import annotations

import json
from pathlib import Path

import pytest
from imagehash import hex_to_hash
from PIL import Image

from uma_it_optimizer.extract import extract_aptattr
from uma_it_optimizer.extract.cards import (
    PHASH_MATCH_THRESHOLD,
    CardDB,
    card_phash,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _all_run_1_scrolls_present() -> bool:
    return all((FIXTURES / f"aptattr_01_scroll_{i}.png").exists() for i in (1, 2, 3))


def _all_run_2_scrolls_present() -> bool:
    return all((FIXTURES / f"aptattr_02_scroll_{i}.png").exists() for i in (1, 2, 3))


def test_thumbnails_produce_valid_phashes() -> None:
    """Extracting from a real scroll yields 16-hex-char pHashes per card."""
    if not _all_run_1_scrolls_present():
        pytest.skip("aptattr_01 scrolls missing")
    scrolls = [FIXTURES / f"aptattr_01_scroll_{i}.png" for i in (1, 2, 3)]
    result = extract_aptattr(scrolls)
    cards = result["support_card_contribs"]
    assert len(cards) == 6
    for card in cards:
        assert "thumbnail_phash" in card
        assert len(card["thumbnail_phash"]) == 16   # 64 bits as hex
        int(card["thumbnail_phash"], 16)             # parses as hex
        assert card["character"] is None             # no DB loaded


def test_same_deck_across_runs_matches_via_phash() -> None:
    """Non-friend cards match across two runs of the same deck (dist ≤ threshold)."""
    if not (_all_run_1_scrolls_present() and _all_run_2_scrolls_present()):
        pytest.skip("aptattr scrolls missing")
    r1 = extract_aptattr([FIXTURES / f"aptattr_01_scroll_{i}.png" for i in (1, 2, 3)])
    r2 = extract_aptattr([FIXTURES / f"aptattr_02_scroll_{i}.png" for i in (1, 2, 3)])

    matches = 0
    for c1, c2 in zip(r1["support_card_contribs"], r2["support_card_contribs"], strict=True):
        d = hex_to_hash(c1["thumbnail_phash"]) - hex_to_hash(c2["thumbnail_phash"])
        if d <= PHASH_MATCH_THRESHOLD:
            matches += 1
    # At least the 5 non-friend cards must match under threshold. The
    # friend card sometimes drifts to ~20 bits due to a mild animated
    # overlay — documented as a v0.1 limitation in cards.py.
    assert matches >= 5, f"only {matches}/6 cards matched across runs"


def test_card_db_round_trip(tmp_path: Path) -> None:
    """Loading a DB, matching a known pHash, and getting back its metadata."""
    if not _all_run_1_scrolls_present():
        pytest.skip("aptattr_01 scrolls missing")

    # Grab the pHash for slot 1 (the SR Lvl 45 Nishino Flower card).
    scrolls = [FIXTURES / f"aptattr_01_scroll_{i}.png" for i in (1, 2, 3)]
    scroll1_result = extract_aptattr(scrolls)
    slot_1_phash = scroll1_result["support_card_contribs"][0]["thumbnail_phash"]

    # Write a minimal DB pointing at it.
    db_path = tmp_path / "db.json"
    db_path.write_text(json.dumps([
        {"phash": slot_1_phash, "character": "Nishino Flower",
         "rarity": "SR", "type": "Speed"},
    ]))
    db = CardDB.load(db_path)
    assert len(db) == 1

    # Re-extract with the DB attached and verify slot 1 is now named.
    result = extract_aptattr(scrolls, card_db=db)
    slot_1 = result["support_card_contribs"][0]
    assert slot_1["character"] == "Nishino Flower"
    assert slot_1["rarity"] == "SR"
    assert slot_1["type"] == "Speed"


def test_load_missing_db_returns_empty() -> None:
    """Loading a nonexistent path is safe — returns an empty DB."""
    db = CardDB.load("/nonexistent/path/db.json")
    assert len(db) == 0
    assert db.match("0000000000000000") is None


def test_phash_of_solid_color_is_stable() -> None:
    """Sanity check: same input → same hash."""
    img = Image.new("RGB", (100, 100), (128, 64, 200))
    assert card_phash(img) == card_phash(img)

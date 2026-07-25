"""Card thumbnail extraction, hashing, and DB lookup.

Each support card row on the Aptitudes/Attributes tab has a ~90x80
thumbnail on the left showing the character art (plus rarity/type
overlays). We extract that thumbnail, compute a perceptual hash
(pHash), and — if the pHash matches an entry in a local card DB —
attach the card's identity (character, rarity, type).

**Bootstrap workflow.** No card DB ships with the project. The first
time you run ingest_run on a run folder, every card entry gets a
``thumbnail_phash`` but ``character=None``. You:

1. Look at the 6 thumbnails ingest_run collected.
2. Fill in ``data/cards/db.json`` — one entry per unique card, keyed
   by pHash, with metadata (character, rarity, type).
3. Rerun ingest_run — the same pHashes now resolve to full card
   identity, and future runs using the same cards get named
   automatically.

The DB lives under ``data/`` which is gitignored — cards are personal
until we ship a public corpus.

v0.1 uses pHash (imagehash.phash) with a Hamming-distance threshold
of 8 bits (out of 64). Empirically, the same card across two runs
matches with 0 bits difference; different cards diverge by 20+.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imagehash
from PIL import Image

# Thumbnail crop bounds relative to a card row's header y (in 1920x1080
# desktop captures). Deliberately tight — we exclude the "Lvl 50" /
# "Friends" text overlays and any hover icons on the right, keeping just
# the character portrait area. Static art → stable pHash across runs
# even when the game re-renders the frame at a slightly different pose.
THUMB_X = (300, 370)   # 70 wide, portrait-only
THUMB_DY = (-25, 35)   # 60 tall, above the level label

# Hamming distance threshold in bits (out of 64) for a "same card" pHash
# match. Non-friend support cards match cleanly at 0-4 bits across runs;
# friend cards carry a small animated pink overlay ("Friends" ribbon)
# that pushes them to ~20 bits, which starts to overlap with the
# distance between visually different characters. Threshold at 18 keeps
# non-friend matching robust; friend cards may need multiple DB entries
# (one per observed animation frame) to match reliably.
PHASH_MATCH_THRESHOLD = 18

DEFAULT_DB_PATH = Path("data/cards/db.json")


def extract_card_thumbnail(pil: Image.Image, header_y: float) -> Image.Image:
    """Return the ~90x80 thumbnail crop for the card at ``header_y``."""
    y_top = int(header_y + THUMB_DY[0])
    y_bot = int(header_y + THUMB_DY[1])
    return pil.crop((THUMB_X[0], y_top, THUMB_X[1], y_bot))


def card_phash(thumbnail: Image.Image) -> str:
    """Perceptual hash (16 hex chars = 64 bits) of a card thumbnail."""
    return str(imagehash.phash(thumbnail))


def _hamming(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


@dataclass(frozen=True)
class CardMatch:
    character: str
    rarity: str
    type: str
    phash: str
    distance: int


class CardDB:
    """Local lookup of pHash → card identity, loaded from JSON."""

    def __init__(self, entries: list[dict[str, Any]]):
        self._entries = entries

    @classmethod
    def load(cls, path: str | Path = DEFAULT_DB_PATH) -> CardDB:
        path = Path(path)
        if not path.exists():
            return cls([])
        with path.open() as f:
            return cls(json.load(f))

    def match(self, phash: str) -> CardMatch | None:
        """Return the closest DB entry within the pHash threshold, or None."""
        best: tuple[int, dict[str, Any]] | None = None
        for entry in self._entries:
            d = _hamming(phash, entry["phash"])
            if d > PHASH_MATCH_THRESHOLD:
                continue
            if best is None or d < best[0]:
                best = (d, entry)
        if best is None:
            return None
        d, entry = best
        return CardMatch(
            character=entry["character"],
            rarity=entry["rarity"],
            type=entry["type"],
            phash=entry["phash"],
            distance=d,
        )

    def __len__(self) -> int:
        return len(self._entries)

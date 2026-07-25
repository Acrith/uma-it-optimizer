"""Parse the Inspiration tab: activated sparks per year with star counts.

Layout: three year sections (Junior / Classic / Senior), each with a
2-column grid of spark rows. Each row is a colored pill with an icon +
skill name, and a small 3-star widget centered below it. Filled stars
are gold; empty stars are gray outlines.

**Attribute Sparks / Aptitude Sparks** rows have their star counts
hidden behind an (i) info button (they aggregate underlying stat and
aptitude sparks). Those are emitted with ``stars: null`` and a
distinct category so downstream can either ignore them or click-through
in a later pass.

v0.1: assumes a single-shot capture (no scrolling within the tab).
Very well-inspired parents can push the list past one screen; multi-
scroll support is a follow-up when we see a real example.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from uma_it_optimizer.extract.ocr import get_reader

# Spark rows appear in these x-column bands (game panel is roughly
# x=280..830 for a 1920x1080 desktop capture).
LEFT_COL_X = (280, 545)
RIGHT_COL_X = (545, 830)

# Star widget: 3 stars centered under the row text. Empirically ~20px
# below the text center; each star ~20px apart.
STAR_Y_OFFSET = 20
LEFT_STAR_CENTERS = (395, 415, 435)
RIGHT_STAR_CENTERS = (674, 694, 714)

# Filled-star gold: hue 30-55°, high saturation & value.
STAR_HUE_RANGE = (30, 60)
STAR_MIN_SAT = 0.5
STAR_MIN_VAL = 0.5

# Rows in the same y-cluster get merged (OCR splits multi-word skills
# like "Barcarole of Blessings" into two boxes).
ROW_CLUSTER_TOLERANCE = 12

YEAR_KEYWORDS = {"junior": "junior", "classic": "classic", "senior": "senior"}
GROUP_ROW_NAMES = {
    "Attribute Sparks": "attribute_group",
    "Aptitude Sparks": "aptitude_group",
}


def _box_center(bbox) -> tuple[float, float]:
    return sum(p[0] for p in bbox) / 4, sum(p[1] for p in bbox) / 4


def _is_gold(pixel: np.ndarray) -> bool:
    r, g, b = pixel
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hue = h * 360
    return STAR_HUE_RANGE[0] <= hue <= STAR_HUE_RANGE[1] and s >= STAR_MIN_SAT and v >= STAR_MIN_VAL


def _count_filled_stars(img: np.ndarray, star_y: int, star_centers: tuple[int, ...]) -> int:
    return sum(1 for cx in star_centers if _is_gold(img[star_y, cx, :3]))


def _classify_year(cy: float, year_ys: dict[str, float]) -> str | None:
    # Sparks belong to the most recent year header above them.
    boundaries = sorted(year_ys.items(), key=lambda kv: kv[1])
    year = None
    for name, y in boundaries:
        if cy > y:
            year = name
        else:
            break
    return year


def _cluster_rows_by_y(
    boxes: list[tuple[float, float, str]], column_range: tuple[int, int]
) -> list[tuple[float, str]]:
    """Merge boxes in a column into (row_y, joined_text) rows.

    Adjacent boxes at the same y (within ROW_CLUSTER_TOLERANCE) belong
    to one spark whose name got split across OCR boxes ("Triumphant"
    + "Pulse" → "Triumphant Pulse"). Within each y-cluster the pieces
    are joined left-to-right by x, not by their exact y — otherwise a
    word at y=320 sorts before the same row's other word at y=321 and
    the merged text ends up backwards.
    """
    in_col = [(cx, cy, text) for cx, cy, text in boxes
              if column_range[0] <= cx <= column_range[1]]
    in_col.sort(key=lambda t: t[1])  # by y only
    buckets: list[list[tuple[float, float, str]]] = []
    for entry in in_col:
        _cx, cy, _text = entry
        if buckets and abs(cy - buckets[-1][0][1]) < ROW_CLUSTER_TOLERANCE:
            buckets[-1].append(entry)
        else:
            buckets.append([entry])
    rows: list[tuple[float, str]] = []
    for bucket in buckets:
        bucket.sort(key=lambda t: t[0])  # within a row, left-to-right by x
        row_y = sum(cy for _cx, cy, _t in bucket) / len(bucket)
        row_text = " ".join(text for _cx, _cy, text in bucket).strip()
        rows.append((row_y, row_text))
    return rows


def extract_inspiration(image_path: str | Path) -> dict[str, Any]:
    """Parse the Inspiration tab into ``{"sparks": {year: [...]}}``.

    Each entry: ``{"name": str, "stars": int|None, "category": str}``.
    """
    image_path = Path(image_path)
    pil = Image.open(image_path).convert("RGB")
    arr = np.asarray(pil)
    boxes = get_reader().readtext(str(image_path), detail=1)

    # Locate year header y positions.
    year_ys: dict[str, float] = {}
    for bbox, text, _conf in boxes:
        low = text.lower()
        for name, keyword in YEAR_KEYWORDS.items():
            if keyword in low and name not in year_ys:
                year_ys[name] = _box_center(bbox)[1]

    # All non-header boxes with their centers.
    centered = []
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        low = text.lower()
        if any(keyword in low for keyword in YEAR_KEYWORDS.values()):
            continue
        # Skip UI chrome — "Activated Sparks", "OK", top banner, etc.
        if cy < 250 or cy > 970:
            continue
        centered.append((cx, cy, text))

    sparks: dict[str, list[dict[str, Any]]] = {"junior": [], "classic": [], "senior": []}
    for column_range, star_centers in (
        (LEFT_COL_X, LEFT_STAR_CENTERS),
        (RIGHT_COL_X, RIGHT_STAR_CENTERS),
    ):
        for row_y, name in _cluster_rows_by_y(centered, column_range):
            year = _classify_year(row_y, year_ys)
            if year is None:
                continue
            name = _canonicalize_name(name)
            category = GROUP_ROW_NAMES.get(name, "skill")
            if category == "skill":
                star_y = int(row_y + STAR_Y_OFFSET)
                # Guard against reading outside image bounds.
                if 0 <= star_y < arr.shape[0]:
                    stars: int | None = _count_filled_stars(arr, star_y, star_centers)
                else:
                    stars = None
            else:
                stars = None  # attribute/aptitude group — hidden behind (i)
            sparks[year].append({"name": name, "stars": stars, "category": category})

    return {"sparks": sparks}


def _canonicalize_name(text: str) -> str:
    """Trim OCR noise from a skill name (trailing punctuation, "0T" for "of")."""
    # OCR sometimes reads "of" as "0T" or the ○ variant marker gets dropped.
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" 0T ", " of ")
    return text

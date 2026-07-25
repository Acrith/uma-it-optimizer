"""Parse the Overview tab of the Training Log screen.

Assumptions (v0.1):
- Input image is a 1920×1080 full-desktop capture with the game
  centered in a stable window position (matches the developer's Steam
  setup). Coordinates below are hardcoded to that layout.
- ALT+PRTSCR active-window captures — different dimensions — will need
  a recalibration pass. Landmark detection (find "Training Log" banner
  → derive game rect) is deferred to a follow-up.
- The OCR pipeline runs once against the full image; fields are then
  extracted by filtering OCR boxes against known y-ranges.
- Grade letters are read from pixel colors (see grades.py); every other
  field comes from OCR.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from uma_it_optimizer.extract.grades import classify_grade
from uma_it_optimizer.extract.ocr import get_reader

# Grade-cell centers for a 1920×1080 full-desktop screenshot.
STAT_GRADE_XY = {
    "speed":   (298, 462),
    "stamina": (388, 462),
    "power":   (481, 462),
    "guts":    (574, 462),
    "wit":     (667, 462),
}
APTITUDE_TRACK_XY = {"turf": (477, 546), "dirt": (588, 546)}
APTITUDE_DISTANCE_XY = {
    "sprint": (477, 569), "mile":   (588, 569),
    "medium": (700, 569), "long":   (808, 569),
}
APTITUDE_STYLE_XY = {
    "front": (477, 593), "pace": (588, 593),
    "late":  (700, 593), "end":  (808, 593),
}

# y-ranges (inclusive) used to filter OCR boxes down to specific fields.
STAT_NUMBER_Y = (455, 480)
TRAINEE_TITLE_Y = (275, 300)
TRAINEE_NAME_Y = (305, 335)
CAREER_LABEL_Y = (640, 700)

# x-window per stat, matching where OCR centers the stat's number box.
# Prevents a "7301" read (real "730" + column separator "1") landing under
# the wrong stat, and lets us reject trailing-artifact digits per-stat.
STAT_NUMBER_X = {
    "speed":                (325, 405),
    "stamina":              (418, 498),
    "power":                (496, 576),
    "guts":                 (590, 670),
    "wit":                  (682, 762),
    "skill_pts_remaining":  (755, 835),
}

# Max plausible values used to strip trailing OCR artifacts (column
# separators read as "1"). Stats cap around 1200; skill pts run to five
# digits in late-game runs.
STAT_MAX = {
    "speed": 1200, "stamina": 1200, "power": 1200, "guts": 1200, "wit": 1200,
    "skill_pts_remaining": 99999,
}


def _box_center(bbox: list[list[float]]) -> tuple[float, float]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return sum(xs) / 4, sum(ys) / 4


def _boxes_in_y(boxes, y_lo: int, y_hi: int) -> list[tuple[float, str]]:
    """Return (cx, text) for OCR boxes whose center y is in [y_lo, y_hi]."""
    out = []
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        if y_lo <= cy <= y_hi:
            out.append((cx, text))
    return sorted(out, key=lambda t: t[0])


def _first_int(text: str) -> int | None:
    m = re.search(r"\d[\d,]*", text)
    return int(m.group().replace(",", "")) if m else None


def _strip_trailing_artifact(n: int, max_reasonable: int) -> int:
    """Repeatedly drop the last digit while the value exceeds a plausible max.

    OCR sometimes reads a thin column separator as a trailing '1' — e.g.
    "8221" for the stat 822. Truncating right-to-left while the value is
    over-large removes the artifact without hardcoding the digit count.
    """
    while n > max_reasonable and n > 0:
        n //= 10
    return n


def _extract_stats(boxes) -> dict[str, int]:
    """Read the 6 stat numbers, one per pre-defined x-window on the stats row."""
    y_lo, y_hi = STAT_NUMBER_Y
    result: dict[str, int] = {}
    for stat, (x_lo, x_hi) in STAT_NUMBER_X.items():
        for bbox, text, _conf in boxes:
            cx, cy = _box_center(bbox)
            if not (y_lo <= cy <= y_hi and x_lo <= cx <= x_hi):
                continue
            n = _first_int(text)
            if n is None:
                continue
            result[stat] = _strip_trailing_artifact(n, STAT_MAX[stat])
            break
    missing = set(STAT_NUMBER_X) - set(result)
    if missing:
        raise ValueError(f"missing stat numbers for {sorted(missing)}")
    return result


def _extract_trainee(boxes) -> dict[str, str | None]:
    """Pull [title] and character name from the trainee card region."""
    title = None
    for _, text in _boxes_in_y(boxes, *TRAINEE_TITLE_Y):
        m = re.search(r"\[([^\]]+)\]", text)
        if m:
            title = m.group(1)
            break
    names = [text for _, text in _boxes_in_y(boxes, *TRAINEE_NAME_Y)
             if re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", text) and " " in text]
    return {"name": names[0] if names else None, "title": title}


def _extract_career(boxes) -> dict[str, int | None]:
    """Extract Races / Wins / Fans from the career section."""
    result: dict[str, int | None] = {"races": None, "wins": None, "fans": None}
    for _, text in _boxes_in_y(boxes, *CAREER_LABEL_Y):
        t = text.replace(" ", "")
        if t.startswith("Races:"):
            result["races"] = _first_int(t)
        elif t.startswith("Wins:"):
            result["wins"] = _first_int(t)
        elif "," in text and any(c.isdigit() for c in text):
            n = _first_int(text)
            if n is not None and n > 1000:
                result["fans"] = n
    return result


def extract_overview(image_path: str | Path) -> dict[str, Any]:
    """Parse an Overview screenshot into the schema's outcome fragment.

    Returns a dict shaped like a subset of examples/example_extracted.json:
        {"trainee": {...}, "stats": {...}, "stat_grades": {...},
         "aptitude_after": {...}, "career": {...}}
    """
    image_path = Path(image_path)
    img = np.asarray(Image.open(image_path).convert("RGB"))
    boxes = get_reader().readtext(str(image_path), detail=1)

    def grades_from(xy_map: dict[str, tuple[int, int]]) -> dict[str, str]:
        return {name: classify_grade(img, x, y) for name, (x, y) in xy_map.items()}

    stat_grades = grades_from(STAT_GRADE_XY)
    aptitude_after = {
        "track": grades_from(APTITUDE_TRACK_XY),
        "distance": grades_from(APTITUDE_DISTANCE_XY),
        "style": grades_from(APTITUDE_STYLE_XY),
    }

    return {
        "trainee": _extract_trainee(boxes),
        "stats": _extract_stats(boxes),
        "stat_grades": stat_grades,
        "aptitude_after": aptitude_after,
        "career": _extract_career(boxes),
    }

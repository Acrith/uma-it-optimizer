"""Parse the Skill Hint(s) tab.

Layout: three sections stacked top-to-bottom (Inspiration → Support
Cards → Event), each a 2-column grid of skill rows. Each row is a
pill with a small "Hint Lvl N" (or "Hint Lvl Max") badge above the
skill name.

**v0.1 scope: single scroll.** Extracts every skill visible on one
screenshot, tags it with a section if the section's header is visible
on this scroll; otherwise leaves ``section=None`` for a multi-scroll
merger to resolve. Skills earned from support cards don't yet carry
a ``card_slot`` — thumbnail-based card identification is a separate
workstream (see the deck field in the schema).

**Hint level detection uses a per-badge re-OCR fallback.** The
full-image OCR reads "Hint Lvl 2" cleanly maybe half the time; the
other half it drops the number ("HHint Lvl", "Hmt Lu"). A tight crop
around each badge, upscaled, digit-allowed, recovers most of the
misses. Truly unreadable badges default to ``level=None``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from uma_it_optimizer.extract.ocr import get_reader

# Game panel spans ~x=280..830 in 1920x1080 desktop captures.
LEFT_COL_X = (350, 545)
RIGHT_COL_X = (600, 830)

# Section header keywords (headers appear at x~300 in the left margin).
SECTION_KEYWORDS: dict[str, str] = {
    "inspiration": "from_inspiration",
    "support cards": "from_support_cards",
    "event": "from_events",
}

# Hint Lvl badge is above the skill name at roughly (skill_y - 24).
BADGE_Y_OFFSET = -24
BADGE_HALF_HEIGHT = 12
BADGE_LEFT_X = (440, 545)     # matches LEFT column skill row badge x-range
BADGE_RIGHT_X = (720, 810)    # matches RIGHT column skill row badge x-range

# Multi-word skill names split into multiple OCR boxes. Same-y cluster
# tolerance matches inspiration.py.
ROW_CLUSTER_TOLERANCE = 12

# Rows to filter out of the "skills" scan: not skills, but adjacent chrome.
NON_SKILL_TEXT_PATTERNS = [
    re.compile(r"lvl", re.IGNORECASE),         # anything with "lvl" — badges + card labels
    re.compile(r"^h+.{0,4}\s*l[uv]", re.I),    # OCR-noisy "HHint Lu", "Hmt Lvl"
    re.compile(r"^h+im.?l", re.IGNORECASE),    # "himLul3", "HHimt L"
    re.compile(r"^friend[s:]?$", re.IGNORECASE),
    re.compile(r"^filend", re.IGNORECASE),     # OCR misread of "Friend:"
    re.compile(r"^\d+$"),                      # bare numbers
    re.compile(r"^training$", re.IGNORECASE),
    re.compile(r"^log$", re.IGNORECASE),
    re.compile(r"^independent training", re.I),
    re.compile(r"^skill hint", re.IGNORECASE),
]

# Ignore anything above this y — window banner, "Training Log" title.
BANNER_Y_CUTOFF = 200


def _box_center(bbox) -> tuple[float, float]:
    return sum(p[0] for p in bbox) / 4, sum(p[1] for p in bbox) / 4


def _find_section_ys(boxes) -> dict[str, float]:
    ys: dict[str, float] = {}
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        if cx > 400:  # section headers sit at the left margin
            continue
        low = text.lower().strip()
        for keyword, section in SECTION_KEYWORDS.items():
            if keyword in low and section not in ys:
                ys[section] = cy
    return ys


def _looks_like_skill(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 2:
        return False
    return not any(pat.search(stripped) for pat in NON_SKILL_TEXT_PATTERNS)


def _cluster_column(boxes, column_range: tuple[int, int]) -> list[tuple[float, str]]:
    """Return (row_y, joined_text) for skill rows in one column."""
    in_col = []
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        if cy < BANNER_Y_CUTOFF:
            continue
        if not (column_range[0] <= cx <= column_range[1]):
            continue
        if not _looks_like_skill(text):
            continue
        in_col.append((cx, cy, text))
    in_col.sort(key=lambda t: t[1])
    buckets: list[list[tuple[float, float, str]]] = []
    for entry in in_col:
        _cx, cy, _text = entry
        if buckets and abs(cy - buckets[-1][0][1]) < ROW_CLUSTER_TOLERANCE:
            buckets[-1].append(entry)
        else:
            buckets.append([entry])
    rows = []
    for bucket in buckets:
        bucket.sort(key=lambda t: t[0])
        row_y = sum(cy for _cx, cy, _t in bucket) / len(bucket)
        row_text = " ".join(text for _cx, _cy, text in bucket).strip()
        rows.append((row_y, row_text))
    return rows


def _classify_section(cy: float, section_ys: dict[str, float]) -> str | None:
    boundaries = sorted(section_ys.items(), key=lambda kv: kv[1])
    section = None
    for name, y in boundaries:
        if cy > y:
            section = name
        else:
            break
    return section


_LEVEL_RE = re.compile(r"lvl?\s*(\d+|max)", re.IGNORECASE)


def _parse_level(text: str) -> int | str | None:
    m = _LEVEL_RE.search(text)
    if not m:
        return None
    raw = m.group(1)
    return "max" if raw.lower() == "max" else int(raw)


def _read_badge_level(
    pil_image: Image.Image, badge_cx: float, badge_cy: float
) -> int | str | None:
    """Fallback: crop tightly around a Hint Lvl badge and re-OCR."""
    x_lo = int(badge_cx - 50)
    x_hi = int(badge_cx + 50)
    y_lo = int(badge_cy - BADGE_HALF_HEIGHT)
    y_hi = int(badge_cy + BADGE_HALF_HEIGHT)
    crop = pil_image.crop((x_lo, y_lo, x_hi, y_hi))
    crop = crop.resize((crop.size[0] * 3, crop.size[1] * 3), Image.LANCZOS)
    recog = get_reader().readtext(np.asarray(crop), detail=1)
    for _bbox, text, _conf in recog:
        lvl = _parse_level(text)
        if lvl is not None:
            return lvl
    return None


def _level_for_row(
    row_y: float,
    row_x_range: tuple[int, int],
    boxes,
    pil_image: Image.Image,
) -> int | str | None:
    """Read the "Hint Lvl N" badge that sits above this skill row."""
    target_y = row_y + BADGE_Y_OFFSET
    best_text = None
    best_dy = 999.0
    best_center = None
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        if not (row_x_range[0] <= cx <= row_x_range[1]):
            continue
        if "lvl" not in text.lower() and "lv" not in text.lower():
            continue
        dy = abs(cy - target_y)
        if dy < BADGE_HALF_HEIGHT and dy < best_dy:
            best_text = text
            best_dy = dy
            best_center = (cx, cy)
    if best_text is not None:
        lvl = _parse_level(best_text)
        if lvl is not None:
            return lvl
    # Fallback: crop and re-OCR at the expected badge position.
    if best_center is not None:
        return _read_badge_level(pil_image, best_center[0], best_center[1])
    # Nothing found via OCR — try the geometric center of the badge slot.
    fallback_cx = (row_x_range[0] + row_x_range[1]) / 2
    return _read_badge_level(pil_image, fallback_cx, target_y)


def extract_hints_scroll(image_path: str | Path) -> dict[str, Any]:
    """Extract skill hints visible on one Skill Hint(s) scroll.

    Returns::

        {
            "from_inspiration": [{skill, level}, ...],
            "from_support_cards": [{skill, level, card_slot: None}, ...],
            "from_events": [{skill, level}, ...],
            "unassigned": [{skill, level}, ...],  # section header off-screen
        }
    """
    image_path = Path(image_path)
    pil = Image.open(image_path).convert("RGB")
    boxes = get_reader().readtext(str(image_path), detail=1)

    section_ys = _find_section_ys(boxes)

    result: dict[str, list[dict[str, Any]]] = {
        "from_inspiration": [],
        "from_support_cards": [],
        "from_events": [],
        "unassigned": [],
    }

    for column_range, badge_range in (
        (LEFT_COL_X, BADGE_LEFT_X),
        (RIGHT_COL_X, BADGE_RIGHT_X),
    ):
        for row_y, name in _cluster_column(boxes, column_range):
            section = _classify_section(row_y, section_ys)
            level = _level_for_row(row_y, badge_range, boxes, pil)
            entry: dict[str, Any] = {"skill": name, "level": level}
            if section == "from_support_cards":
                entry["card_slot"] = None  # slot detection TBD
            target = result[section] if section else result["unassigned"]
            target.append(entry)

    return result

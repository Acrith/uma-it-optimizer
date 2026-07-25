"""Parse the Aptitudes / Attributes tab across all scrolls.

Fields extractable across the three scrolls:
- ``aptitude_before`` / ``aptitude_after`` — visible only on scroll 1
- ``inspiration_bonuses`` — visible only on scroll 1
- ``support_card_contribs`` — spread across all three scrolls, deduped
- ``event_totals`` — visible only on the last scroll

For a single scroll, :func:`_extract_all_from_scroll` returns whatever
subset is visible. :func:`extract_aptattr` walks a list of scroll paths,
runs each, and merges: aptitude/inspiration/events are single-source
truths, cards are deduped by their contribution tuple.

v0.1 notes:
- 1920x1080 desktop-capture assumption still holds.
- Card rarity + character identity are NOT extracted; thumbnail
  matching against a card image DB is a separate workstream. Level
  comes from the "Lvl NN" OCR label; ``limit_break = 4 - (max - level)
  / 5`` derived downstream (needs rarity to know max).
- Yellow-highlight aptitude upgrade detection still deferred.
- ``extract_aptattr_scroll_1`` kept as a subset wrapper for the earlier
  test suite; new code should call :func:`extract_aptattr` instead.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from uma_it_optimizer.extract.cards import CardDB, card_phash, extract_card_thumbnail
from uma_it_optimizer.extract.grades import classify_grade
from uma_it_optimizer.extract.ocr import get_reader

# --------------------------------------------------------------- constants

# Aptitude grade cell centers per section, for both blocks (scroll 1 only).
APT_BEFORE_XY: dict[str, dict[str, tuple[int, int]]] = {
    "track":    {"turf": (479, 266), "dirt": (588, 266)},
    "distance": {"sprint": (479, 289), "mile": (588, 289),
                 "medium": (700, 289), "long": (808, 289)},
    "style":    {"front": (479, 313), "pace": (588, 313),
                 "late":  (700, 313), "end":  (808, 313)},
}
APT_AFTER_XY: dict[str, dict[str, tuple[int, int]]] = {
    "track":    {"turf": (479, 382), "dirt": (588, 382)},
    "distance": {"sprint": (479, 406), "mile": (588, 406),
                 "medium": (700, 406), "long": (808, 406)},
    "style":    {"front": (479, 431), "pace": (588, 431),
                 "late":  (700, 431), "end":  (808, 431)},
}

# Per-stat x centers used both for the inspiration row (scroll 1) and
# for support-card contribution rows (all scrolls) and events (scroll 3).
INSP_STAT_X = {"speed": 346, "stamina": 457, "power": 567, "guts": 678, "wit": 789}
CARD_STAT_X = {"speed": 419, "stamina": 493, "power": 570, "guts": 644, "wit": 722,
               "skill_pts": 794}
EVENT_STAT_X = {"speed": 338, "stamina": 429, "power": 513, "guts": 619, "wit": 712,
                "skill_pts": 800}

INSP_TOTAL_Y = (548, 570)
INSP_DELTA_Y = (570, 585)
INSP_TOTAL_MAX = 999
INSP_DELTA_MAX = 99
INSP_COL_HALF_WIDTH = 42
INSP_COL_Y_BAND = (548, 588)
INSP_UPSCALES = (2, 3)

# Card row anatomy (in pixels, relative to the header row's y):
#   header row     y+0    ("Speed | Stamina | Power | Guts | Wit | Skill Pts")
#   values row     y+27   ("+11    21        +46      11     11     57")
#   level label    y+55   ("Lvl 45" / "Lv 50" / "Friend:" for the friend card)
CARD_VALUES_DY = 27
CARD_LABEL_DY = 55
CARD_STAT_MAX = 199   # per-card per-stat contribs cap around ~150 IRL
CARD_SP_MAX = 999
CARD_LEVEL_MIN = 20   # unlocked cards start at level 20
CARD_LEVEL_MAX = 50   # MLB SSR

# Events row anatomy (only present on the last scroll):
#   "Events" title       y+0    (small header at left margin)
#   Stat labels row      y+33   ("Speed | Stamina | Power | Guts | Wit | Skill Pts")
#   Number values row    y+66   ("+566   303       +333    207    456   2999")
EVENT_VALUES_DY = 66
EVENT_TOTAL_MAX = 9999   # events can push totals into the thousands
EVENT_DELTA_MAX = 999    # unused in v0.1 delta detection deferred


# --------------------------------------------------------- shared helpers

def _box_center(bbox) -> tuple[float, float]:
    return sum(p[0] for p in bbox) / 4, sum(p[1] for p in bbox) / 4


def _strip_trailing(n: int, max_reasonable: int) -> int:
    while n > max_reasonable and n > 0:
        n //= 10
    return n


def _grades_for(img: np.ndarray, xy_nested) -> dict[str, dict[str, str]]:
    return {
        section: {name: classify_grade(img, x, y) for name, (x, y) in cells.items()}
        for section, cells in xy_nested.items()
    }


def _pick_best(candidates: list[tuple[int, float, int]], max_val: int) -> int:
    if not candidates:
        return 0
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return _strip_trailing(candidates[0][2], max_val)


# ----------------------------------------------------- aptitude / bonuses

def _extract_inspiration_bonuses(pil_image: Image.Image) -> dict[str, dict[str, int]]:
    """Per-column crop + multi-scale re-OCR on the inspiration bonuses row.

    See inline notes on why multi-scale merge is needed here.
    """
    reader = get_reader()
    y_lo, y_hi = INSP_COL_Y_BAND
    result: dict[str, dict[str, int]] = {}
    for stat, cx in INSP_STAT_X.items():
        base_crop = pil_image.crop((cx - INSP_COL_HALF_WIDTH, y_lo,
                                    cx + INSP_COL_HALF_WIDTH, y_hi))
        top_candidates: list[tuple[int, float, int]] = []
        bot_candidates: list[tuple[int, float, int]] = []
        for scale in INSP_UPSCALES:
            up = base_crop.resize((base_crop.size[0] * scale,
                                   base_crop.size[1] * scale), Image.LANCZOS)
            mid_y = up.size[1] / 2
            for bbox, text, conf in reader.readtext(np.asarray(up), detail=1):
                digit_runs = re.findall(r"\d+", text)
                if not digit_runs:
                    continue
                longest = max(digit_runs, key=len)
                target = top_candidates if sum(p[1] for p in bbox) / 4 < mid_y else bot_candidates
                target.append((len(longest), float(conf), int(longest)))
        result[stat] = {
            "total": _pick_best(top_candidates, INSP_TOTAL_MAX),
            "delta": _pick_best(bot_candidates, INSP_DELTA_MAX),
        }
    return result


# ---------------------------------------------------------------- cards

def _card_header_ys(boxes) -> list[float]:
    """Every card row starts with a "Speed" header in the leftmost column."""
    ys = []
    for bbox, text, _conf in boxes:
        cx, cy = _box_center(bbox)
        # "Speed" (or its noisy variant "Speel") in the leftmost card column
        if 400 <= cx <= 440 and text.strip().lower().startswith("spee"):
            ys.append(cy)
    ys.sort()
    # Dedup any header y that duplicates within 10px (rare OCR jitter).
    return [y for i, y in enumerate(ys) if i == 0 or y - ys[i-1] > 10]


def _extract_row_numbers(
    pil: Image.Image, values_y: float, stat_x_centers: dict[str, int], max_val: int,
    col_half_width: int = 30, half_height: int = 10,
) -> dict[str, int]:
    """Read one row of stat numbers via per-column crop + multi-scale OCR.

    ``half_height`` deliberately tight — a wider window catches any delta
    line drawn below the value, and the digits merge (e.g. "+333" + "(+130)"
    → "1130" from the concatenated OCR read).
    """
    reader = get_reader()
    y_lo = int(values_y - half_height)
    y_hi = int(values_y + half_height)
    result: dict[str, int] = {}
    for stat, cx in stat_x_centers.items():
        base_crop = pil.crop((cx - col_half_width, y_lo, cx + col_half_width, y_hi))
        candidates: list[tuple[int, float, int]] = []
        for scale in (2, 3):
            up = base_crop.resize((base_crop.size[0] * scale,
                                   base_crop.size[1] * scale), Image.LANCZOS)
            for _bbox, text, conf in reader.readtext(np.asarray(up), detail=1):
                digit_runs = re.findall(r"\d+", text)
                if not digit_runs:
                    continue
                longest = max(digit_runs, key=len)
                candidates.append((len(longest), float(conf), int(longest)))
        cap = CARD_SP_MAX if stat == "skill_pts" else max_val
        result[stat] = _pick_best(candidates, cap)
    return result


def _extract_card_level(
    pil: Image.Image, header_y: float, boxes,
) -> tuple[int | None, bool]:
    """Read the "Lvl NN" (or "Friend:") label under a card thumbnail.

    Returns ``(level, is_friend)``. Level is None if OCR failed hard.
    """
    label_y = header_y + CARD_LABEL_DY
    is_friend = False
    # Check the full-image OCR first — the label region is at x=310..380.
    for _bbox, text, _conf in boxes:
        cx, cy = _box_center(_bbox)
        if not (300 <= cx <= 390 and abs(cy - label_y) < 20):
            continue
        low = text.lower()
        if "friend" in low or "filend" in low or "riend" in low:
            is_friend = True
    # Level: crop the label area, upscale, re-OCR for digits.
    reader = get_reader()
    crop = pil.crop((295, int(label_y - 15), 400, int(label_y + 15)))
    crop = crop.resize((crop.size[0] * 3, crop.size[1] * 3), Image.LANCZOS)
    best: tuple[int, float] | None = None  # (level, conf)
    for _b, text, conf in reader.readtext(np.asarray(crop), detail=1):
        for digits in re.findall(r"\d+", text):
            n = int(digits)
            if CARD_LEVEL_MIN <= n <= CARD_LEVEL_MAX:
                if best is None or conf > best[1]:
                    best = (n, float(conf))
    return (best[0] if best else None), is_friend


def _extract_visible_cards(
    pil: Image.Image, boxes, card_db: CardDB | None = None,
) -> list[dict[str, Any]]:
    """Return every card visible on this scroll as {level, is_friend,
    contribs, thumbnail_phash, character, rarity, type}.

    ``character``/``rarity``/``type`` are populated when the thumbnail's
    pHash matches an entry in ``card_db``; otherwise they remain None
    (bootstrap case — user fills in DB metadata later).
    """
    header_ys = _card_header_ys(boxes)
    cards: list[dict[str, Any]] = []
    for hy in header_ys:
        values_y = hy + CARD_VALUES_DY
        contribs = _extract_row_numbers(pil, values_y, CARD_STAT_X, CARD_STAT_MAX)
        level, is_friend = _extract_card_level(pil, hy, boxes)
        thumbnail = extract_card_thumbnail(pil, hy)
        phash = card_phash(thumbnail)
        card = {
            "level": level,
            "is_friend": is_friend,
            "contribs": contribs,
            "thumbnail_phash": phash,
            "character": None,
            "rarity": None,
            "type": None,
        }
        if card_db is not None:
            match = card_db.match(phash)
            if match is not None:
                card["character"] = match.character
                card["rarity"] = match.rarity
                card["type"] = match.type
        cards.append(card)
    return cards


# ---------------------------------------------------------------- events

def _find_events_header_y(boxes) -> float | None:
    for _bbox, text, _conf in boxes:
        cx, cy = _box_center(_bbox)
        if cx < 400 and "event" in text.strip().lower():
            return cy
    return None


def _extract_event_totals(pil: Image.Image, boxes) -> dict[str, dict[str, int]] | None:
    """If the events row is on this scroll, extract per-stat {total, delta}.

    Uses full-image OCR filtered by (x-window, y-band) per stat — the
    numbers here are large and high-contrast, so full-image OCR reads
    them cleanly. Per-column re-OCR was less reliable (adjacent delta
    line kept bleeding in and inflating totals).
    """
    header_y = _find_events_header_y(boxes)
    if header_y is None:
        return None
    values_y = header_y + EVENT_VALUES_DY
    y_lo, y_hi = int(values_y - 12), int(values_y + 12)
    totals: dict[str, int] = {}
    for stat, cx in EVENT_STAT_X.items():
        best_val = 0
        best_len = 0
        best_conf = 0.0
        for bbox, text, conf in boxes:
            bcx, bcy = _box_center(bbox)
            if not (y_lo <= bcy <= y_hi and abs(bcx - cx) < 45):
                continue
            for digits in re.findall(r"\d+", text):
                n = _strip_trailing(int(digits), EVENT_TOTAL_MAX)
                # Longer digit run wins first, then confidence.
                if len(digits) > best_len or (len(digits) == best_len and conf > best_conf):
                    best_val = n
                    best_len = len(digits)
                    best_conf = float(conf)
        totals[stat] = best_val
    # Delta detection deferred — small parenthetical numbers below the
    # totals row are often missed by full-image OCR.
    return {stat: {"total": totals[stat], "delta": 0} for stat in totals}


# ---------------------------------------------------- per-scroll dispatch

def _has_aptitude_section(boxes) -> bool:
    for _bbox, text, _conf in boxes:
        if text.strip().lower() == "aptitude":
            return True
    return False


def _has_inspiration_section(boxes) -> bool:
    for _bbox, text, _conf in boxes:
        if "inspiration" in text.strip().lower():
            return True
    return False


def _extract_all_from_scroll(
    image_path: str | Path, card_db: CardDB | None = None,
) -> dict[str, Any]:
    """Extract every field currently visible on one aptattr scroll."""
    image_path = Path(image_path)
    pil = Image.open(image_path).convert("RGB")
    arr = np.asarray(pil)
    boxes = get_reader().readtext(str(image_path), detail=1)

    out: dict[str, Any] = {}
    if _has_aptitude_section(boxes):
        out["aptitude_before"] = _grades_for(arr, APT_BEFORE_XY)
        out["aptitude_after"] = _grades_for(arr, APT_AFTER_XY)
    if _has_inspiration_section(boxes):
        out["inspiration_bonuses"] = _extract_inspiration_bonuses(pil)
    cards = _extract_visible_cards(pil, boxes, card_db=card_db)
    if cards:
        out["cards_visible"] = cards
    events = _extract_event_totals(pil, boxes)
    if events is not None:
        out["event_totals"] = events
    return out


# ------------------------------------------------------ multi-scroll merge

def _card_key(card: dict) -> tuple:
    """Cards with identical contribs are the same card across scrolls."""
    c = card["contribs"]
    return (c.get("speed", 0), c.get("stamina", 0), c.get("power", 0),
            c.get("guts", 0), c.get("wit", 0), c.get("skill_pts", 0))


def _dedup_cards(all_cards: list[dict]) -> list[dict]:
    """Preserve first-seen order; skip a card if its contribs match one
    we already added. Cards seen on multiple scrolls collapse to one entry.
    """
    seen: set[tuple] = set()
    result: list[dict] = []
    for card in all_cards:
        key = _card_key(card)
        if key in seen:
            continue
        seen.add(key)
        result.append(card)
    return result


def extract_aptattr(
    image_paths: list[str | Path], card_db: CardDB | None = None,
) -> dict[str, Any]:
    """Merge extract results across a run's aptattr scrolls.

    ``image_paths`` should be in scroll order (top → bottom). Aptitude,
    inspiration bonuses, and event totals are single-source truths and
    take the first non-empty value across scrolls. Support-card contribs
    concatenate and dedup by (contribs) tuple.

    Pass a ``card_db`` to attach character/rarity/type to each card row
    via pHash matching. Without a DB, cards get their ``thumbnail_phash``
    filled in but identity fields stay None.
    """
    per_scroll = [_extract_all_from_scroll(p, card_db=card_db) for p in image_paths]

    merged: dict[str, Any] = {}
    for key in ("aptitude_before", "aptitude_after", "inspiration_bonuses",
                "event_totals"):
        for scroll in per_scroll:
            if key in scroll:
                merged[key] = scroll[key]
                break

    all_cards = [card for scroll in per_scroll for card in scroll.get("cards_visible", [])]
    deduped = _dedup_cards(all_cards)
    merged["support_card_contribs"] = [
        {"slot": i + 1, **card} for i, card in enumerate(deduped)
    ]
    return merged


# --------------------------------------------------------- legacy wrapper

def extract_aptattr_scroll_1(image_path: str | Path) -> dict[str, Any]:
    """Legacy: single-scroll aptitude + inspiration only.

    Kept so the earlier test suite still passes. New callers should use
    :func:`extract_aptattr` with the full list of scroll paths.
    """
    fields = _extract_all_from_scroll(image_path)
    return {k: v for k, v in fields.items()
            if k in ("aptitude_before", "aptitude_after", "inspiration_bonuses")}

"""Detect which Training Log tab a screenshot shows, without renaming.

Each Training Log tab renders its name in a fixed banner near the top
of the game panel (Overview / Career / Aptitudes / Attributes / Skill
Hint(s) / Inspiration). The detector OCRs just that title region and
matches loosely against each tab's distinguishing keywords, so users
can dump raw ALT+PRTSCR shots into a folder without renaming and the
ingester still routes each one correctly.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image

from uma_it_optimizer.extract.ocr import get_reader


class TabKind(Enum):
    OVERVIEW = "overview"
    CAREER = "career"
    APTATTR = "aptattr"
    HINTS = "hints"
    INSPIRATION = "inspiration"
    UNKNOWN = "unknown"


# Title text lives near the top of the game panel. Crop is generous to
# tolerate window-position drift across capture setups.
TITLE_CROP = (380, 100, 750, 155)  # (x1, y1, x2, y2) in a 1920x1080 shot

# Substring → tab mapping, checked in priority order (specific first).
# OCR occasionally splits the title into multiple boxes ("Aptitudes"
# and "Attributes" separately); matching on any is enough.
KEYWORDS: list[tuple[str, TabKind]] = [
    ("aptitude",   TabKind.APTATTR),
    ("attribute",  TabKind.APTATTR),
    ("hint",       TabKind.HINTS),
    ("inspir",     TabKind.INSPIRATION),
    ("overview",   TabKind.OVERVIEW),
    ("career",     TabKind.CAREER),
]


def detect_tab(image_path: str | Path) -> TabKind:
    """Read the title banner and return the tab kind, or UNKNOWN."""
    img = Image.open(image_path).convert("RGB")
    crop = img.crop(TITLE_CROP)
    boxes = get_reader().readtext(np.asarray(crop), detail=1)
    joined = " ".join(text for _bbox, text, _conf in boxes).lower()
    for keyword, kind in KEYWORDS:
        if keyword in joined:
            return kind
    return TabKind.UNKNOWN

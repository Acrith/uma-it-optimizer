"""Letter-grade classification by pixel color.

The Overview screen renders each grade in a colored pill. Every grade
tier has a distinctive hue that's stable across cells and screens, so
color classification is more reliable than OCR on the ~25×25 px pills.

Hues sampled from real screenshots:

    A  = 24°   (orange)          C = 106°  (light green)
    B  = 340°  (pink)            D = 202°  (light blue)
    E  = 287°  (magenta)         F = 244°  (purple)
    G  = any (near-zero saturation → gray)

S grade has not been sampled yet — add its hue when observed.

**v0.1 limitation: +/- suffix is NOT detected.** The suffix is a small
inline glyph that's tiny at native resolution, blends with the pill
color, and neither pixel-color probing nor OCR-with-allowlist could
detect it reliably on the current fixtures. Downstream consumers
should treat the returned grade as the base letter only and expect
occasional post-edits for +/- runs until v0.2 lands a real detector
(candidate approaches: template matching a "+" glyph across all grade
colors, or a small CNN on cropped pills).
"""
from __future__ import annotations

import colorsys

import numpy as np

# (grade_letter, hue_deg). All near-full-value pills.
GRADE_HUES = {
    "A": 24,
    "B": 340,
    "C": 106,
    "D": 202,
    "E": 287,
    "F": 244,
}

GRAY_MAX_SATURATION = 0.05  # anything under this hits the "G" branch

# Sample a 5-point horizontal strip across the pill and take the majority
# classification. Robustness for cases like the yellow "upgraded" overlay
# that sits on the aptitude_after pill's center: a center-only average
# blends yellow into the pill's blue and misclassifies.
SAMPLE_DXS = (-8, -4, 0, 4, 8)


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _sample_patch(img: np.ndarray, x: int, y: int, half: int = 1) -> tuple[float, float, float]:
    patch = img[y - half : y + half + 1, x - half : x + half + 1, :3]
    r, g, b = (float(c) for c in patch.reshape(-1, 3).mean(axis=0))
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)


def _classify_point(h_frac: float, s_frac: float, v_frac: float) -> str | None:
    """Classify one HSV sample; None if too dim (letter interior) or off-pill."""
    if v_frac < 0.4:
        return None  # dark letter pixel or shadow
    if s_frac < GRAY_MAX_SATURATION:
        # Only count as G if the pixel is a mid-value gray (~pill body).
        # Off-pill whitespace (near-white, sat 0) is skipped.
        return "G" if 0.4 <= v_frac <= 0.8 else None
    hue_deg = h_frac * 360
    return min(GRADE_HUES, key=lambda g: _hue_distance(hue_deg, GRADE_HUES[g]))


def classify_grade(img: np.ndarray, x: int, y: int) -> str:
    """Return the base letter grade (A/B/C/D/F/G/…) at the given pill center.

    Samples a horizontal strip through the pill and returns the majority
    grade, so a small overlay (upgrade marker, letter interior) can't tip
    the classification.
    """
    votes: dict[str, int] = {}
    for dx in SAMPLE_DXS:
        h, s, v = _sample_patch(img, x + dx, y)
        grade = _classify_point(h, s, v)
        if grade is not None:
            votes[grade] = votes.get(grade, 0) + 1
    if not votes:
        return "?"
    return max(votes, key=lambda g: votes[g])

"""Load the bundled masters.json snapshot and resolve numeric IDs to
human-readable names. All lookups fall back to ``?<kind>:<id>``-style
placeholders when a row is missing, so callers never have to handle
``None`` — the returned string is always displayable.

Overriding the bundled snapshot:
- Programmatic: ``load_masters(path)`` with an explicit path
- Env var:     ``UMA_MASTERS_PATH=/some/masters.json``
"""
from __future__ import annotations
import json
import os
from functools import lru_cache
from pathlib import Path


BUNDLED_PATH = Path(__file__).parent / "data" / "masters.json"

RARITY_PREFIX_SUPPORT = {1: "R", 2: "SR", 3: "SSR"}


@lru_cache(maxsize=4)
def _load_from(path_str: str) -> dict:
    p = Path(path_str)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_masters(path: Path | None = None) -> dict:
    """Return the loaded masters dict. Priority: explicit arg → env var
    UMA_MASTERS_PATH → bundled snapshot. Cached across calls; safe to
    call repeatedly."""
    if path is not None:
        return _load_from(str(path))
    env = os.environ.get("UMA_MASTERS_PATH")
    if env:
        return _load_from(env)
    return _load_from(str(BUNDLED_PATH))


def uma_card_name(card_id: int) -> str:
    """Resolve a trainee card_id (e.g. 103201) → 'Agnes Tachyon'."""
    m = load_masters()
    card = m.get("uma_cards", {}).get(str(card_id))
    if not card:
        return f"?uma:{card_id}"
    return card.get("chara_name") or f"?uma:{card_id}"


def scenario_name(scenario_id: int) -> str:
    """Resolve scenario_id (1..4) → 'URA Finale' / 'Unity Cup' / etc."""
    m = load_masters()
    s = m.get("scenarios", {}).get(str(scenario_id))
    if not s:
        return f"?scen:{scenario_id}"
    return s.get("name") or f"?scen:{scenario_id}"


def support_card_name(card_id: int, *, with_rarity: bool = True) -> str:
    """Resolve support card id (e.g. 30028) → 'SSR Kitasan Black'."""
    m = load_masters()
    c = m.get("support_cards", {}).get(str(card_id))
    if not c:
        return f"?sup:{card_id}"
    name = c.get("chara_name") or f"?sup:{card_id}"
    if not with_rarity:
        return name
    prefix = RARITY_PREFIX_SUPPORT.get(c.get("rarity", 0), "")
    return f"{prefix} {name}".strip()


def skill_name(skill_id: int) -> str:
    """Resolve skill id (e.g. 100321) → 'U=ma2'."""
    m = load_masters()
    s = m.get("skills", {}).get(str(skill_id))
    if not s:
        return f"?skill:{skill_id}"
    return s.get("name") or f"?skill:{skill_id}"


def race_name(program_id: int) -> str:
    """Resolve single-mode program_id (e.g. 2225) → 'URA Finale Finals'."""
    m = load_masters()
    p = m.get("programs", {}).get(str(program_id))
    if not p:
        return f"?race:{program_id}"
    return p.get("name") or f"?race:{program_id}"


def deck_summary(card_ids: tuple[int, ...] | list[int]) -> str:
    """Compact one-line deck description for the dashboard tooltip.
    Example: 'SSR Kitasan / SSR Fine / SR Nishino / SR Windy / ...'."""
    parts = [support_card_name(c) for c in card_ids]
    return " / ".join(parts)

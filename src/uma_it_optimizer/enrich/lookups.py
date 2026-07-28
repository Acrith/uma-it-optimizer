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

# support_card_data.command_id → training-focus type. Empirically verified
# against ~15 known Global cards (Fine Motion=106=Wit, Marvelous Sunday=102
# =Speed, Nice Nature/Winning Ticket/Mejiro Palmer=103=Stamina, etc.).
# command_id=104 is unused in current Global build.
SUPPORT_TYPE_BY_CMD = {
    0: "Friend",
    101: "Power",
    102: "Speed",
    103: "Stamina",
    105: "Guts",
    106: "Wit",
}


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


def support_card_type(card_id: int) -> str:
    """Resolve support card id → training-focus type (Speed/Stamina/...)."""
    m = load_masters()
    c = m.get("support_cards", {}).get(str(card_id))
    if not c:
        return "?"
    return SUPPORT_TYPE_BY_CMD.get(c.get("command_id"), "?")


def support_card_name(card_id: int, *, with_rarity: bool = True,
                      with_type: bool = False) -> str:
    """Resolve support card id (e.g. 30028) → 'SSR Kitasan Black'.
    With ``with_type=True`` produces 'SSR Kitasan Black (Power)'."""
    m = load_masters()
    c = m.get("support_cards", {}).get(str(card_id))
    if not c:
        return f"?sup:{card_id}"
    name = c.get("chara_name") or f"?sup:{card_id}"
    if with_rarity:
        prefix = RARITY_PREFIX_SUPPORT.get(c.get("rarity", 0), "")
        name = f"{prefix} {name}".strip()
    if with_type:
        t = SUPPORT_TYPE_BY_CMD.get(c.get("command_id"), "?")
        name = f"{name} ({t})"
    return name


def skill_name(skill_id: int) -> str:
    """Resolve skill id (e.g. 100321) → 'U=ma2'."""
    m = load_masters()
    s = m.get("skills", {}).get(str(skill_id))
    if not s:
        return f"?skill:{skill_id}"
    return s.get("name") or f"?skill:{skill_id}"


@lru_cache(maxsize=1)
def _hint_group_index() -> dict[tuple[int, int], int]:
    """Build (group_id, rarity) → canonical skill_id lookup by scanning
    masters.json. Preference order for tie-breaking: rate=1 (○ variant,
    the gold single-circle name most players recognize), then rate=2 (◎),
    then any other."""
    m = load_masters()
    index: dict[tuple[int, int], int] = {}
    best_rate: dict[tuple[int, int], int] = {}
    for sid_str, s in m.get("skills", {}).items():
        key = (s.get("group_id", 0), s.get("rarity", 0))
        rate = s.get("group_rate", 0)
        priority = {1: 3, 2: 2, -1: 0}.get(rate, 1)  # ○ wins, then ◎, then rest
        if key not in index or priority > best_rate.get(key, -1):
            index[key] = int(sid_str)
            best_rate[key] = priority
    return index


def skill_from_hint(group_id: int, rarity: int) -> tuple[int, str]:
    """Skill hints in captures store (group_id, rarity) — a hint group
    that maps to several variants (◎/○/×). We pick the ○ variant as the
    canonical display name (what shows on the hint bubble in-game).
    Returns (canonical_skill_id, display_name)."""
    idx = _hint_group_index()
    sid = idx.get((group_id, rarity))
    if sid is None:
        return 0, f"?hint:{group_id}/{rarity}"
    return sid, skill_name(sid)


# Skill rarity → readable tier badge. 1=white(common), 2=gold(rare),
# 4/5=unique. Verified against actual run data where rarity 1 hints
# resolve to '○'-suffixed names (gold indicator).
SKILL_RARITY_LABEL = {
    1: "white",   # common
    2: "gold",    # rare
    3: "gold",    # rare (some scenario-locked variants)
    4: "unique",
    5: "unique",
}


def skill_rarity_label(rarity: int) -> str:
    return SKILL_RARITY_LABEL.get(rarity, f"r{rarity}")


def race_name(program_id: int) -> str:
    """Resolve single-mode program_id (e.g. 2225) → 'URA Finale Finals'."""
    m = load_masters()
    p = m.get("programs", {}).get(str(program_id))
    if not p:
        return f"?race:{program_id}"
    return p.get("name") or f"?race:{program_id}"


def deck_summary(card_ids: tuple[int, ...] | list[int]) -> str:
    """Compact one-line deck description for the dashboard tooltip.
    Example: 'SSR Kitasan Black (Power) / SSR Fine Motion (Wit) / ...'."""
    parts = [support_card_name(c, with_type=True) for c in card_ids]
    return " / ".join(parts)


def deck_type_composition(card_ids: tuple[int, ...] | list[int]) -> dict[str, int]:
    """Return {type: count} for a deck. E.g. {'Speed': 2, 'Power': 2, 'Wit': 1, 'Friend': 1}."""
    out: dict[str, int] = {}
    for cid in card_ids:
        t = support_card_type(cid)
        out[t] = out.get(t, 0) + 1
    return out

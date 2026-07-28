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


# Numeric rank → letter grade. Heuristic mapping calibrated against
# typical Umamusume Global progression: G/F/E/D/C/B/A/S/SS with ± variants.
# The game uses 98 rank tiers internally, but the visible letter grades
# top out well before that — anything past SS+ is very rare in practice.
# Community references vary on exact boundaries; this covers the observed
# range (Global captures typically land in ranks 11-17, i.e. B to SS+).
LETTER_GRADE_BY_RANK = {
    1: "G",   2: "G+",
    3: "F",   4: "F+",
    5: "E",   6: "E+",
    7: "D",   8: "D+",
    9: "C",   10: "C+",
    11: "B",  12: "B+",
    13: "A",  14: "A+",
    15: "S",  16: "S+",
    17: "SS", 18: "SS+",
}


def letter_grade(rank: int) -> str:
    """Numeric rank (1..98) → letter grade string. Above rank 18 uses
    'EX+N' (extreme end of the distribution)."""
    if rank <= 0:
        return "?"
    if rank in LETTER_GRADE_BY_RANK:
        return LETTER_GRADE_BY_RANK[rank]
    return f"EX+{rank - 18}"


def letter_grade_range(rank_lo: int, rank_hi: int) -> str:
    """Compact display for a floor-ceiling rank range.
    Same letter → 'S'. Different → 'B–SS+'."""
    lo = letter_grade(rank_lo)
    hi = letter_grade(rank_hi)
    if lo == hi:
        return lo
    return f"{lo}–{hi}"


# ── Factor name composition ──────────────────────────────────────────
# Factors are (factor_type, factor_group_id, rarity) triples where:
# - type 1: stat (group 1=Speed .. 5=Wit)
# - type 2: aptitude (10 predefined groups — see FACTOR_APTITUDE_NAMES)
# - type 3: unique-skill inheritance (group=card_id, e.g. 100101 = Special Week variant 01)
# - type 4: skill inheritance (group=skill group_id, lookup via existing skill helpers)
# - type 5/6/7: scenario/green/rare factors — labeled generically for now
# ★ count comes from rarity: 1=★, 2=★★, 3=★★★.

FACTOR_STAT_NAMES = {
    1: "Speed", 2: "Stamina", 3: "Power", 4: "Guts", 5: "Wit",
}

FACTOR_APTITUDE_NAMES = {
    11: "Turf",   12: "Dirt",
    21: "Sprint", 22: "Mile", 23: "Medium", 24: "Long",
    31: "Front",  32: "Pace", 33: "Late",   34: "End",
}


def _stars(rarity: int) -> str:
    return "★" * max(1, min(rarity, 3))


def factor_name(factor_id: int) -> str:
    """Compose a display name for a factor_id by looking up its type/group
    in masters and formatting per-type. Returns a string like
    'Speed ★★', 'Turf ★', 'Corner Recovery ○ ★★', 'Unique: Kitasan Black ★'.
    Falls back to '?factor:<id>' if not resolvable."""
    m = load_masters()
    f = m.get("factors", {}).get(str(factor_id))
    if not f:
        return f"?factor:{factor_id}"
    ftype = f.get("factor_type", 0)
    group = f.get("group_id", 0)          # written as "group_id" in dump
    rarity = f.get("rarity", 1)
    stars = _stars(rarity)

    if ftype == 1:
        name = FACTOR_STAT_NAMES.get(group, f"?stat:{group}")
        return f"{name} {stars}"
    if ftype == 2:
        name = FACTOR_APTITUDE_NAMES.get(group, f"?apt:{group}")
        return f"{name} {stars}"
    if ftype == 3:
        # Unique-skill factor — group_id is a card_id (chara_id × 100 + variant)
        cards = m.get("uma_cards", {})
        card = cards.get(str(group))
        who = card.get("chara_name") if card else f"?card:{group}"
        return f"Unique: {who} {stars}"
    if ftype == 4:
        # Skill factor — group_id is a skill's group_id; find the ○ variant name
        sid, name = skill_from_hint(group, 1)
        # If lookup fails, try rarity 2 as fallback
        if not sid:
            sid, name = skill_from_hint(group, 2)
        return f"{name} {stars}"
    if ftype == 5:
        return f"Green ({group}) {stars}"
    if ftype == 6:
        return f"White ({group}) {stars}"
    return f"Factor:{group}/{ftype} {stars}"


def race_name(program_id: int) -> str:
    """Resolve single-mode program_id (e.g. 2225) → 'URA Finale Finals'."""
    m = load_masters()
    p = m.get("programs", {}).get(str(program_id))
    if not p:
        return f"?race:{program_id}"
    return p.get("name") or f"?race:{program_id}"


def race_program_info(program_id: int) -> dict | None:
    """Return the full program dict (name, race_id, grade, entry_num,
    month, half) for a program_id, or None if not in masters."""
    m = load_masters()
    return m.get("programs", {}).get(str(program_id))


# Race.grade → coarse grade label. Values from the game's `race` table.
RACE_GRADE_LABEL = {
    100: "G1", 200: "G2", 300: "G3",
    400: "OP", 800: "Pre-OP", 900: "Debut/Maiden",
}


def race_grade_label(grade: int) -> str:
    return RACE_GRADE_LABEL.get(grade, str(grade))


def race_result_ordinal(rank: int) -> str:
    """1 → '1st', 2 → '2nd', 12 → '12th' — for result_rank display."""
    if rank <= 0:
        return "—"
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


GAMETORA_CDN = "https://gametora.com/images/umamusume"


def support_card_image_url(card_id: int, *, size: str = "small") -> str:
    """Gametora CDN URL for a support card thumbnail.
    size='small' (~30 KB) or 'full' (~200 KB, high-res render)."""
    if size == "full":
        return f"{GAMETORA_CDN}/supports/tex_support_card_{card_id}.png"
    return f"{GAMETORA_CDN}/supports/support_card_s_{card_id}.png"


def uma_card_image_url(uma_card_id: int, *, size: str = "thumb") -> str | None:
    """Gametora CDN URL for a trainee card art. Requires resolving the
    chara_id from masters (uma_card_id = chara_id × 100 + variant).
    Returns None if the card isn't in our masters snapshot."""
    m = load_masters()
    card = m.get("uma_cards", {}).get(str(uma_card_id))
    if not card:
        return None
    chara_id = card.get("chara_id")
    if not chara_id:
        return None
    base = f"chara_stand_{chara_id}_{uma_card_id}.png"
    if size == "full":
        return f"{GAMETORA_CDN}/characters/{base}"
    return f"{GAMETORA_CDN}/characters/thumb/{base}"


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

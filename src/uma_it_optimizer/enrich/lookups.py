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

# support_card_data.command_id → training-focus type. Verified against
# known Global cards: Fine Motion (cmd 106) = Wit, Super Creek + Manhattan
# Cafe + Mayano Top Gun (all cmd 105) = Stamina, Special Week SSR (cmd 103)
# = Guts, Tazuna/Light Hello (cmd 0) = Friend. Speed/Power mapping (101/102)
# also empirically verified on the dashboard — cards visually match icons
# only with 101=Speed and 102=Power (initially had the reverse). command_id
# =104 unused on Global.
SUPPORT_TYPE_BY_CMD = {
    0: "Friend",
    101: "Speed",
    102: "Power",
    103: "Guts",
    105: "Stamina",
    106: "Wit",
}

# Same command_id → gametora's utx_ico_obtain_XX index. Game icons:
# 0=boot(Speed), 1=heart(Stamina), 2=bicep(Power), 3=flame(Guts),
# 4=grad-cap(Wit), 5=smiley(Friend), 6=multi-smiley(Group).
SUPPORT_TYPE_ICON_INDEX = {
    0: 5,       # Friend (yellow smiley)
    101: 0,     # Speed (boot)
    102: 2,     # Power (bicep)
    103: 3,     # Guts (flame)
    105: 1,     # Stamina (heart)
    106: 4,     # Wit (graduation cap)
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


# group_rate → variant label: 2=◎ (double circle, always-active version),
# 1=○ (single circle, situational), -1=× (harmful, never buy), 3=alt gold.
GROUP_RATE_LABEL = {2: "◎", 1: "○", -1: "×", 3: "alt"}
GROUP_RATE_RANK = {2: 0, 1: 1, 3: 2, -1: 3}   # display order: ◎ before ○ before alt before ×


# ── skill classification (running style / distance) ─────────────────
# Parses skill_data.condition_1 (SQL-ish predicate blob) to distinguish
# TRAINEE-affinity skills from opponent-triggered or universal ones.
#
# Predicate legend (from decompilation of game logic):
#   running_style==N        → TRAINEE'S own style (1=Front, 2=Pace, 3=Late, 4=End)
#   distance_type==N        → TRAINEE'S target distance (1=Sprint, 2=Mile, 3=Medium, 4=Long)
#   running_style_count_*_otherself>=N
#   running_style_temptation_opponent_count_*  → OPPONENT setup — universal for trainee
#
# Name matching alone is unreliable — 'Hesitant Pace Chasers' triggers
# off opponents' Pace count, not the trainee's own style. Only the
# self-style/self-distance predicates should tag a skill.
import re as _re

_RS_MAP = {1: "Front", 2: "Pace", 3: "Late", 4: "End"}
_DT_MAP = {1: "Sprint", 2: "Mile", 3: "Medium", 4: "Long"}
_RE_STYLE = _re.compile(r"(?<![_a-zA-Z])running_style==(\d)")
_RE_DIST = _re.compile(r"distance_type==(\d)")


def classify_skill(name: str = "", condition_1: str = "",
                   condition_2: str = "") -> dict:
    """Return {'styles': [...], 'distances': [...], 'is_universal': bool}
    for a skill, parsed from its activation conditions."""
    conds = (condition_1 or "") + " " + (condition_2 or "")
    styles = sorted({_RS_MAP[int(m)] for m in _RE_STYLE.findall(conds)
                     if int(m) in _RS_MAP})
    distances = sorted({_DT_MAP[int(m)] for m in _RE_DIST.findall(conds)
                        if int(m) in _DT_MAP})
    return {
        "styles": styles,
        "distances": distances,
        "is_universal": not styles and not distances,
    }


HINT_DISCOUNT_PER_LEVEL = 0.10  # 10% off per hint level, capped at level 5


def hint_level_cap(level: int) -> int:
    """Hint levels above 5 don't stack further. Match in-game behavior."""
    if level < 0:
        return 0
    return min(level, 5)


def discounted_sp(base_sp: int, hint_level: int) -> int:
    """Apply hint-level SP discount.

    Formula (community-known, matches in-game "hint bonus" tooltip):
        effective_sp = floor(base_sp × (1 − 0.10 × min(level, 5)))

    - Level 0: no change
    - Level 5+: 50% off (max discount)
    - Never returns 0 for a positive base (min effective cost = 1 SP)
    """
    if base_sp <= 0 or hint_level <= 0:
        return int(base_sp)
    level = hint_level_cap(hint_level)
    reduced = base_sp * (10 - level) / 10.0
    return max(1, int(reduced))


def hint_group_variants(group_id: int, rarity: int | None = None,
                        hint_level_by_skill: dict[int, int] | None = None) -> list[dict]:
    """Return skill variants in a hint group as {skill_id, name, rate,
    rate_label, sp_cost, grade_value, value_per_sp}. Sorted best-first
    (◎ then ○ then alt then ×). Skills without an sp_cost are omitted.

    If ``rarity`` is given, only variants of that skill_data.rarity are
    returned — a hint at (group, rarity) unlocks only skills of that
    same rarity (e.g. rarity=1 hint on group 20035 gives you
    'Corner Recovery ○' and '×' — not the rarity=2 gold rare
    'Swinging Maestro' in the same group)."""
    m = load_masters()
    skills = m.get("skills", {})
    variants: list[dict] = []
    for sid_str, s in skills.items():
        if s.get("group_id") != group_id:
            continue
        if rarity is not None and s.get("rarity") != rarity:
            continue
        cost = s.get("sp_cost")
        val = s.get("grade_value")
        if not cost or not val:
            continue
        rate = s.get("group_rate", 0)
        cls = classify_skill(
            name=s.get("name", ""),
            condition_1=s.get("condition_1", ""),
            condition_2=s.get("condition_2", ""),
        )
        sid_int = int(sid_str)
        icon_id = s.get("icon_id")
        base_cost = int(cost)
        # Hint level → discount. Hint level is a per-skill accumulator
        # (multiple hint events for the same skill stack); passing the
        # map lets the planner and knapsack score with the actual
        # purchase cost the player faces in-game.
        hint_lv = hint_level_cap((hint_level_by_skill or {}).get(sid_int, 0))
        eff_cost = discounted_sp(base_cost, hint_lv)
        variants.append({
            "skill_id": sid_int,
            "name": s.get("name", f"?skill:{sid_str}"),
            "rate": rate,
            "rate_label": GROUP_RATE_LABEL.get(rate, "?"),
            "rarity": int(s.get("rarity", 0) or 0),
            "sp_cost": eff_cost,          # discounted — used by planner/knapsack
            "base_sp_cost": base_cost,    # pre-discount — for UI "was X, now Y"
            "hint_level": hint_lv,        # 0..5 (capped)
            "grade_value": int(val),
            "value_per_sp": round(val / eff_cost, 2) if eff_cost else 0.0,
            "styles": cls["styles"],
            "distances": cls["distances"],
            "is_universal": cls["is_universal"],
            "icon_url": (f"{GAMETORA_CDN}/skill_icons/utx_ico_skill_{icon_id}.png"
                         if icon_id else None),
        })
    variants.sort(key=lambda v: (GROUP_RATE_RANK.get(v["rate"], 9), -v["grade_value"]))
    return variants


def innate_skills_for_card(card_id: int) -> list[dict]:
    """Skills always accessible to a trainee's card in the SP buy panel.
    Each entry is ``{skill_id, need_rank}``; need_rank=0 = usable from
    turn 1, higher values unlock as the trainee's career rank climbs.

    Sourced from the `available_skill_set` master table via
    `card_data.available_skill_set_id`. Returns [] if the card or its
    skill set isn't in masters."""
    m = load_masters()
    card = (m.get("uma_cards") or {}).get(str(card_id)) or {}
    ssid = card.get("available_skill_set_id")
    if not ssid:
        return []
    return (m.get("innate_skills") or {}).get(str(ssid)) or []


def hint_levels_from_raw(raw: dict) -> dict[int, int]:
    """Build ``{skill_id: total_hint_level}`` from a run's GainInfo blob.

    A SkillTip entry carries ``(group_id, rarity, level)``; the pair
    (group_id, rarity) identifies a single purchasable skill, and
    ``level`` is the amount ADDED by that hint event. Multiple events
    for the same skill stack (capped at 5 by ``hint_level_cap``).
    """
    from collections import defaultdict
    lvl_by_grouprar: dict[tuple[int, int], int] = defaultdict(int)
    for gi in raw.get("GainInfo", []) or []:
        for t in gi.get("<SkillTipsArray>k__BackingField", []) or []:
            if not isinstance(t, dict):
                continue
            gid = int(t.get("group_id", 0) or 0)
            rar = int(t.get("rarity", 0) or 0)
            lv = int(t.get("level", 0) or 0)
            if gid and lv > 0:
                lvl_by_grouprar[(gid, rar)] += lv

    # Resolve (group_id, rarity) -> skill_id via the skills master.
    out: dict[int, int] = {}
    if not lvl_by_grouprar:
        return out
    m = load_masters()
    for sid_str, s in m.get("skills", {}).items():
        key = (int(s.get("group_id", 0) or 0), int(s.get("rarity", 0) or 0))
        if key in lvl_by_grouprar:
            out[int(sid_str)] = hint_level_cap(lvl_by_grouprar[key])
    return out


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
    # EX tier — Ug (rank 19-28), Uf (29-38), Ue (39-48). Very rare
    # in practice; only whales / perfect-play runs hit these.
    19: "Ug",  20: "Ug¹", 21: "Ug²", 22: "Ug³", 23: "Ug⁴",
    24: "Ug⁵", 25: "Ug⁶", 26: "Ug⁷", 27: "Ug⁸", 28: "Ug⁹",
    29: "Uf",  30: "Uf¹", 31: "Uf²", 32: "Uf³", 33: "Uf⁴",
    34: "Uf⁵", 35: "Uf⁶", 36: "Uf⁷", 37: "Uf⁸", 38: "Uf⁹",
    39: "Ue",  40: "Ue¹", 41: "Ue²", 42: "Ue³", 43: "Ue⁴",
    44: "Ue⁵", 45: "Ue⁶", 46: "Ue⁷", 47: "Ue⁸", 48: "Ue⁹",
}

# Rank-badge icon URLs (64×64 PNGs of the actual game asset). Sourced
# from the community rating-calculator spreadsheet
# https://docs.google.com/spreadsheets/d/1CtLcA7wn_bFC0C7nsSpUhFJGi5ahkMqCx6fIXSwTQQM
# (ranks tab, IMAGE() formulas). Hosted on ucarecdn.com.
# Ranks 19+ (Ug/Uf/Ue tier) exist but omitted for now — no capture ever
# lands there in normal play. Add later if needed.
GRADE_ICON_URL = {
    "G":   "https://ucarecdn.com/5ebd9b54-6861-451f-81e4-d927c0f93871/G.png",
    "G+":  "https://ucarecdn.com/5a33b751-4fde-4d02-af73-08c6b7c2eb16/G.png",
    "F":   "https://ucarecdn.com/d5314f9d-5258-4541-afcd-9a73180d26a8/F.png",
    "F+":  "https://ucarecdn.com/7172c064-5696-4331-ab0c-d91fda76fff6/F.png",
    "E":   "https://ucarecdn.com/ff2aad3a-1a0e-4ee3-a139-df3bca013bb4/E.png",
    "E+":  "https://ucarecdn.com/2d98094f-0980-4c86-84f7-12feff970e11/E.png",
    "D":   "https://ucarecdn.com/510464a1-4bbe-449f-9ef3-353df9fa9287/D.png",
    "D+":  "https://ucarecdn.com/20806fc3-a266-4a24-85fc-83f2e72e3e6f/D.png",
    "C":   "https://ucarecdn.com/c24c1d96-c814-475e-b96c-e269b26dd4a3/C.png",
    "C+":  "https://ucarecdn.com/ca5724b8-0274-431e-a0ea-72a809cc9051/C.png",
    "B":   "https://ucarecdn.com/77340b52-f3e0-4bbf-991e-cb6c093a47fe/B.png",
    "B+":  "https://ucarecdn.com/74ae2bd7-df98-4c4b-9c0c-9a95e2a068a7/B.png",
    "A":   "https://ucarecdn.com/bc198b34-d0d5-4526-9f12-e4e20d2fd06c/A.png",
    "A+":  "https://ucarecdn.com/d6e22ea0-5e90-4f9e-8e7f-0446b1cd8b35/A.png",
    "S":   "https://ucarecdn.com/fe47a6cf-39fd-4f43-bd65-8de0bcdd5125/S.png",
    "S+":  "https://ucarecdn.com/1d62b8ec-99f0-46ee-ae08-0ea3e9d07fdd/S.png",
    "SS":  "https://ucarecdn.com/902b5f72-f9e3-4727-b8a3-6a859e3c395c/SS.png",
    "SS+": "https://ucarecdn.com/350624dc-889b-41d1-8dd5-ea23b66113a0/SS.png",
    # EX tier — 30 sub-ranks across Ug, Uf, Ue prefixes.
    "Ug":  "https://ucarecdn.com/6cf688d0-d852-418d-bb2d-5e695dd5a36e/UG.png",
    "Ug¹": "https://ucarecdn.com/d60b208e-c6b8-4d0f-b6e6-9dc110ca4e0c/UG1.png",
    "Ug²": "https://ucarecdn.com/25ca9dc6-fa97-4440-842e-0715b066be42/UG2.png",
    "Ug³": "https://ucarecdn.com/ada20e59-4fd7-4468-a583-0985b3277629/UG3.png",
    "Ug⁴": "https://ucarecdn.com/c10300ca-84d4-4340-814e-89ad0feae078/UG4.png",
    "Ug⁵": "https://ucarecdn.com/d0970ada-c050-49a5-bbd4-80e62f825675/UG5.png",
    "Ug⁶": "https://ucarecdn.com/532c5060-0a96-4652-ab4e-cb9d445d4d8f/UG6.png",
    "Ug⁷": "https://ucarecdn.com/78821047-54db-43a4-ae37-92b63ff34d25/UG7.png",
    "Ug⁸": "https://ucarecdn.com/009c0153-2d39-4364-94aa-4f9cf09b5f03/UG8.png",
    "Ug⁹": "https://ucarecdn.com/29534564-4db3-4d45-ae34-57e2d17da050/UG9.png",
    "Uf":  "https://ucarecdn.com/6c5c1914-c6e3-46b8-8ba6-a51c6304fb51/UF.png",
    "Uf¹": "https://ucarecdn.com/26df385f-980d-40f1-98bc-d28fe52724dc/UF1.png",
    "Uf²": "https://ucarecdn.com/bea6c2bb-10d4-45bb-8baa-c9952eccf1aa/UF2.png",
    "Uf³": "https://ucarecdn.com/8c67cb62-0022-44b3-a912-f8cfba812ed2/UF3.png",
    "Uf⁴": "https://ucarecdn.com/eab1ebad-c3ec-4182-9918-cdb475e0bf2b/UF4.png",
    "Uf⁵": "https://ucarecdn.com/0f1e362b-818e-49a4-964d-321b138be737/UF5.png",
    "Uf⁶": "https://ucarecdn.com/f8c4e5a3-415a-41ad-bbbf-c63213da69ce/UF6.png",
    "Uf⁷": "https://ucarecdn.com/415af962-3bac-450b-bbc6-c505336105bc/UF7.png",
    "Uf⁸": "https://ucarecdn.com/d9afe783-88bb-4c5c-b8d1-91b9ad9d68f8/UF8.png",
    "Uf⁹": "https://ucarecdn.com/745b5e69-9a6c-444d-aa70-b2297b734d2b/UF9.png",
    "Ue":  "https://ucarecdn.com/af1b3ff8-0006-4972-90db-470d88b44c3a/UE.png",
    "Ue¹": "https://ucarecdn.com/3d0ed51f-566a-4335-8b2c-0d18a85ee966/UE1.png",
    "Ue²": "https://ucarecdn.com/678e7603-334e-4df9-8213-296cf9e50b2c/UE2.png",
    "Ue³": "https://ucarecdn.com/4f1db15c-937e-44bc-b5fb-bd538d8e2ffd/UE3.png",
    "Ue⁴": "https://ucarecdn.com/ce266b9a-9498-4dbd-ad44-e61622bfe7e1/UE4.png",
    "Ue⁵": "https://ucarecdn.com/e6856fd6-1ade-446c-94b9-c862fd9bafec/UE5.png",
    "Ue⁶": "https://ucarecdn.com/2e17fefe-5537-4a8e-8416-ad274501f80d/UE6.png",
    "Ue⁷": "https://ucarecdn.com/3a5225f2-1b5a-41b4-84f1-d68beeb2cf56/UE7.png",
    "Ue⁸": "https://ucarecdn.com/cbd608d6-f5a8-41c0-9047-e509a3228da3/UE8.png",
    "Ue⁹": "https://ucarecdn.com/95727d57-3cd1-40cc-8a41-4db4209f725a/UE9.png",
}


def grade_icon_url(letter: str) -> str | None:
    """Icon URL for a grade letter (G/F/E/D/C/B/A/S/SS with ± variants).
    Ranks 19+ (EX tier) return None — caller should fall back to text."""
    return GRADE_ICON_URL.get(letter)


def infer_preset(*, speed: int, stamina: int, power: int,
                 wiz: int, guts: int) -> tuple[str, str]:
    """Heuristic guess at which IT preset the run used (Balanced /
    Stamina / Sprint / etc.), based on final stats. The preset itself
    isn't persisted anywhere in the completed-run state, so this is
    inference-only. Returns (label, confidence).

    Rule: Stamina preset pushes stamina notably higher than the other
    presets. Empirically on this account: Stamina run ended at 989 vs
    every other run 519-763 — a 226-point gap. Anything above ~850
    is confidently 'Stamina'. Everything else defaults to 'Balanced',
    but could also be Sprint or another non-stamina preset the game
    ships. Sprint isn't reliably distinguishable from Balanced by
    stats alone — both cap stamina around 600, they differ only in
    the speed/power emphasis which is highly deck-dependent."""
    if stamina >= 850:
        return "Stamina", "high"
    return "Balanced?", "low"


def letter_grade(rank: int) -> str:
    """Numeric rank (1..98) → letter grade string. Ranks 1-48 are named
    (G through Ue⁹ per the community rating tiers). Above rank 48 the
    game's single_mode_rank table keeps going up to 98 but no player
    ever hits those — return generic 'EX+N' as a safe fallback."""
    if rank <= 0:
        return "?"
    if rank in LETTER_GRADE_BY_RANK:
        return LETTER_GRADE_BY_RANK[rank]
    return f"EX+{rank - 48}"


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
    """Display name for a factor_id — uses the game's own text_data
    category 147 (loaded into masters as ``factors.display_name``).

    Preserves ★ counts from rarity. If the display name is absent
    (factor missing from masters), falls back to the older composed
    logic (kept for backwards-compat with older masters.json dumps
    that didn't include display_name)."""
    m = load_masters()
    f = m.get("factors", {}).get(str(factor_id))
    if not f:
        return f"?factor:{factor_id}"
    rarity = f.get("rarity", 1)
    stars = _stars(rarity)
    name = f.get("display_name") or ""
    if name:
        # Green factors (type 5/6/7) get the granted-stat pair appended
        # inline — the game name alone (e.g. 'Tenno Sho (Spring)') tells
        # you the RACE but not what stat spark you get from it, and
        # that's the number the player actually optimizes around.
        # Skip type-4 skill factors — their names already carry the +stat
        # suffix when relevant (e.g. 'Ignited Spirit: Speed +').
        if f.get("factor_type") in (5, 6, 7):
            stats = f.get("granted_stats") or []
            if stats and not any(s in name for s in stats):
                name = f"{name} +{'/'.join(stats)}"
        return f"{name} {stars}"
    return _compose_factor_name_legacy(f, factor_id, stars)


def _compose_factor_name_legacy(f: dict, factor_id: int, stars: str) -> str:
    """Fallback name composition — used only when a factor's
    ``display_name`` is missing (older masters.json dumps predating the
    category-147 pull). The composed aptitude labels here were
    known-wrong (distance/style mixed up) and this path exists mainly
    so old runs don't crash; regenerate masters.json to pick up the
    game's real names."""
    m = load_masters()
    ftype = f.get("factor_type", 0)
    group = f.get("group_id", 0)
    if ftype == 1:
        return f"{FACTOR_STAT_NAMES.get(group, f'?stat:{group}')} {stars}"
    if ftype == 2:
        return f"{FACTOR_APTITUDE_NAMES.get(group, f'?apt:{group}')} {stars}"
    if ftype == 3:
        cards = m.get("uma_cards", {})
        card = cards.get(str(group))
        who = card.get("chara_name") if card else f"?card:{group}"
        return f"Unique: {who} {stars}"
    if ftype == 4:
        sid, name = skill_from_hint(group, 1)
        if not sid:
            sid, name = skill_from_hint(group, 2)
        return f"{name} {stars}"
    if ftype in (5, 6, 7):
        skills = f.get("granted_skill_names") or []
        stats = f.get("granted_stats") or []
        if skills and stats:
            return f"{skills[0]} +{'/'.join(stats)} {stars}"
        if skills:
            return f"{skills[0]} {stars}"
        if stats:
            return f"{'+'.join(stats)} {stars}"
        return f"Green ({group}) {stars}"
    return f"?factor:{factor_id} {stars}"


def factor_type_label(factor_id: int) -> str:
    """Category label for color-coding a factor chip in the UI."""
    m = load_masters()
    f = m.get("factors", {}).get(str(factor_id))
    if not f:
        return "unknown"
    return {1: "stat", 2: "aptitude", 3: "unique",
            4: "skill", 5: "green", 6: "green", 7: "special"}.get(
                f.get("factor_type", 0), "unknown"
            )


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


def skill_icon_url(skill_id: int) -> str | None:
    """Gametora CDN URL for a skill's icon PNG (~1-2 KB). Returns None
    if the skill isn't in our masters snapshot or has no icon_id."""
    m = load_masters()
    s = m.get("skills", {}).get(str(skill_id))
    if not s:
        return None
    icon_id = s.get("icon_id")
    if not icon_id:
        return None
    return f"{GAMETORA_CDN}/skill_icons/utx_ico_skill_{icon_id}.png"


def support_card_image_url(card_id: int, *, size: str = "small") -> str:
    """Gametora CDN URL for a support card thumbnail.
    size='small' (~30 KB) or 'full' (~200 KB, high-res render)."""
    if size == "full":
        return f"{GAMETORA_CDN}/supports/tex_support_card_{card_id}.png"
    return f"{GAMETORA_CDN}/supports/support_card_s_{card_id}.png"


def support_card_rarity_icon_url(card_id: int) -> str:
    """Gametora URL for the pill-shaped rarity ribbon (R/SR/SSR).
    Derived from card_id prefix: 1xxxx=R, 2xxxx=SR, 3xxxx=SSR."""
    prefix = card_id // 10000
    idx = prefix if prefix in (1, 2, 3) else 1
    return f"{GAMETORA_CDN}/icons/utx_txt_rarity_0{idx}.png"


def support_card_type_icon_url(card_id: int) -> str | None:
    """Gametora URL for the type icon (boot/heart/bicep/flame/grad/smiley).
    Uses command_id from masters to pick the utx_ico_obtain index."""
    m = load_masters()
    c = m.get("support_cards", {}).get(str(card_id))
    if not c:
        return None
    cmd = c.get("command_id")
    idx = SUPPORT_TYPE_ICON_INDEX.get(cmd)
    if idx is None:
        return None
    return f"{GAMETORA_CDN}/icons/utx_ico_obtain_0{idx}.png"


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

"""Build a rich per-run detail from the extractor JSON.

The captures contain far more than the aggregate dashboard shows:
- SupportCardGainInfo — each card's actual stat + SP contribution
- GainInfo[0] and [1] — Events (~40% of stats) and Inspiration bonuses
- skill_tips_array — every hint the run picked up (group_id + rarity + level)
- SuccessionFactorGainInfo — factors gained per year (year 1/2/3)

This module turns one run JSON into a display-ready dict that the
dashboard renders as an HTML detail page (one page per capture).
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .lookups import (
    factor_name,
    race_grade_label,
    race_program_info,
    race_result_ordinal,
    scenario_name,
    skill_from_hint,
    skill_rarity_label,
    support_card_image_url,
    support_card_name,
    support_card_type,
    uma_card_image_url,
    uma_card_name,
)
from .scoring import estimate_from_run_json


STAT_KEYS = ("Speed", "Stamina", "Power", "Wiz", "Guts")


def _gain_fields(gi: dict) -> dict[str, int]:
    """Read the (Obscured-decoded) numeric stat fields from a GainInfo /
    SupportCardGainInfo.GainInfo blob."""
    out = {}
    for k in STAT_KEYS:
        out[k.lower()] = int(gi.get(f"<{k}>k__BackingField", 0) or 0)
    out["skill_pts"] = int(gi.get("<SkillPoint>k__BackingField", 0) or 0)
    return out


def _hints(gi: dict) -> list[dict]:
    tips = gi.get("<SkillTipsArray>k__BackingField", []) or []
    out = []
    for t in tips:
        if not isinstance(t, dict):
            continue
        out.append({
            "group_id": int(t.get("group_id", 0)),
            "rarity": int(t.get("rarity", 0)),
            "level": int(t.get("level", 0)),
        })
    return out


@dataclass
class RunDetail:
    filename: str
    timestamp: str
    trainee_card_id: int
    trainee_name: str
    trainee_portrait_url: str | None
    scenario_id: int
    scenario_name: str
    final_stats: dict[str, int]
    caps: dict[str, int]
    fans: int
    unspent_sp: int
    motivation: int
    vital: int
    races_run: int

    # Per-source stat contributions — Events / Inspiration / 6 support cards
    contributions: list[dict] = field(default_factory=list)

    # Skill hints, aggregated across all sources into a single row per
    # unique skill (with total levels + which sources gave it)
    hints: list[dict] = field(default_factory=list)

    # Factors gained per year
    factors_by_year: list[dict] = field(default_factory=list)

    # Race history — one row per race actually run, oldest→newest
    races: list[dict] = field(default_factory=list)

    # Optimal skill-purchase plan given available hints + unspent SP.
    # Empty when no hints/SP or run is pre-training.
    score_summary: dict = field(default_factory=dict)
    plan: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "timestamp": self.timestamp,
            "trainee_card_id": self.trainee_card_id,
            "trainee_name": self.trainee_name,
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "final_stats": self.final_stats,
            "caps": self.caps,
            "fans": self.fans,
            "unspent_sp": self.unspent_sp,
            "motivation": self.motivation,
            "vital": self.vital,
            "races_run": self.races_run,
            "contributions": self.contributions,
            "hints": self.hints,
            "factors_by_year": self.factors_by_year,
            "races": self.races,
            "score_summary": self.score_summary,
            "plan": self.plan,
        }


def build(path: Path) -> RunDetail:
    raw = json.loads(path.read_text(encoding="utf-8"))
    chara = raw["SingleModeChara"][0]
    gain_infos = raw.get("GainInfo", []) or []
    sup_cards = raw.get("SupportCardGainInfo", []) or []

    # ── Per-source contributions ─────────────────────────────────────
    # GainInfo[0] = Events, GainInfo[1] = Inspiration, GainInfo[2..7] =
    # 6 support cards (in reverse deck order — we don't rely on this,
    # SupportCardGainInfo has the card_id inline).
    contributions: list[dict] = []
    if len(gain_infos) >= 1:
        gain = _gain_fields(gain_infos[0])
        contributions.append({
            "source": "Events",
            "card_id": None,
            "card_name": "Events",
            "card_type": "",
            "image_url": None,
            "limit_break": None,
            "gains": gain,
            "hint_count": len(_hints(gain_infos[0])),
        })
    if len(gain_infos) >= 2:
        gain = _gain_fields(gain_infos[1])
        contributions.append({
            "source": "Inspiration",
            "card_id": None,
            "card_name": "Inspiration",
            "card_type": "",
            "image_url": None,
            "limit_break": None,
            "gains": gain,
            "hint_count": len(_hints(gain_infos[1])),
        })
    # Per-card LB level lives on SingleModeChara.support_card_array
    # ({position, support_card_id, limit_break_count, exp, ...}). Build a
    # lookup so we can show LB crystals per card.
    lb_by_card_id = {
        int(entry.get("support_card_id", 0) or 0): int(entry.get("limit_break_count", 0) or 0)
        for entry in (chara.get("support_card_array") or [])
    }

    for i, sc in enumerate(sup_cards):
        cid = int(sc.get("<SupportCardId>k__BackingField", 0) or 0)
        gi = sc.get("<GainInfo>k__BackingField", {}) or {}
        gain = _gain_fields(gi)
        # SupportCardGainInfo[i] hints live in GainInfo[7-i] (reverse-mapped
        # relative to the Events[0] / Inspiration[1] / Cards[2..7] layout).
        # SupportCardGainInfo's own SkillTipsArray only contains untraversed
        # placeholder strings, so we route to GainInfo[7-i] instead.
        card_hints_idx = len(gain_infos) - 1 - i
        card_hints = 0
        if 0 <= card_hints_idx < len(gain_infos):
            card_hints = len(_hints(gain_infos[card_hints_idx]))
        contributions.append({
            "source": "Support",
            "card_id": cid,
            "card_name": support_card_name(cid),
            "card_type": support_card_type(cid),
            "image_url": support_card_image_url(cid),
            "limit_break": lb_by_card_id.get(cid, 0),
            "gains": gain,
            "hint_count": card_hints,
        })

    # ── Skill hints across all sources ───────────────────────────────
    # Aggregate: sum levels per (skill_id) across all GainInfo sources.
    # Track which sources contributed each hint (best-effort — GainInfo
    # source order maps to Events/Inspiration/reverse-deck-cards).
    hint_agg: dict[int, dict] = {}
    for gi_idx, gi in enumerate(gain_infos):
        source_label = _label_for_gain_source(gi_idx, sup_cards)
        for h in _hints(gi):
            sid, name = skill_from_hint(h["group_id"], h["rarity"])
            key = sid or (h["group_id"] * 1000 + h["rarity"])
            entry = hint_agg.setdefault(key, {
                "skill_id": sid,
                "name": name,
                "group_id": h["group_id"],
                "rarity": h["rarity"],
                "rarity_label": skill_rarity_label(h["rarity"]),
                "total_level": 0,
                "sources": [],
            })
            entry["total_level"] += h["level"]
            entry["sources"].append({"source": source_label, "level": h["level"]})
    hints = sorted(
        hint_agg.values(),
        key=lambda h: (-h["total_level"], h["name"]),
    )

    # ── Factors per year ─────────────────────────────────────────────
    factors_by_year: list[dict] = []
    for year_entry in raw.get("SuccessionFactorGainInfo", []) or []:
        year = int(year_entry.get("<Year>k__BackingField", 0) or 0)
        factor_rows: list[dict] = []
        for f in year_entry.get("<GainFactorInfoArray>k__BackingField", []) or []:
            fid = int(f.get("<FactorId>k__BackingField", 0) or 0)
            factor_rows.append({
                "factor_id": fid,
                "name": factor_name(fid),
                "level": int(f.get("<Level>k__BackingField", 0) or 0),
            })
        factors_by_year.append({"year": year, "factors": factor_rows})

    # ── Race history ─────────────────────────────────────────────────
    # RaceHistory entries are program-scoped races with turn / result rank.
    # Sort by turn ascending so the list reads oldest → newest.
    RUN_STYLE_LABEL = {
        1: "Nige (Front)", 2: "Senko (Pace)", 3: "Sashi (Late)", 4: "Oikomi (End)",
    }
    races: list[dict] = []
    for rh in sorted(raw.get("RaceHistory", []) or [], key=lambda r: int(r.get("turn", 0) or 0)):
        pid = int(rh.get("program_id", 0) or 0)
        if pid == 0:
            continue
        info = race_program_info(pid) or {}
        rank = int(rh.get("result_rank", 0) or 0)
        races.append({
            "turn": int(rh.get("turn", 0) or 0),
            "program_id": pid,
            "race_name": info.get("name", f"?race:{pid}"),
            "grade": info.get("grade", 0),
            "grade_label": race_grade_label(info.get("grade", 0)),
            "result_rank": rank,
            "result_ordinal": race_result_ordinal(rank),
            "won": rank == 1,
            "running_style": RUN_STYLE_LABEL.get(int(rh.get("running_style", 0) or 0), "?"),
        })

    # ── Header stats ─────────────────────────────────────────────────
    final_stats = {k.lower(): int(chara.get(k.lower(), 0) or 0) for k in STAT_KEYS}
    caps = {k.lower(): int(chara.get(f"max_{k.lower()}", 0) or 0) for k in STAT_KEYS}
    trainee_id = int(chara.get("card_id", 0) or 0)
    scen_id = int(chara.get("scenario_id", 0) or 0)

    # timestamp from filename, robust fallback to file mtime string
    ts = path.stem.split("_")[0] if "_" in path.stem else path.stem

    return RunDetail(
        filename=path.name,
        timestamp=ts,
        trainee_card_id=trainee_id,
        trainee_name=uma_card_name(trainee_id),
        trainee_portrait_url=uma_card_image_url(trainee_id),
        scenario_id=scen_id,
        scenario_name=scenario_name(scen_id),
        final_stats=final_stats,
        caps=caps,
        fans=int(chara.get("fans", 0) or 0),
        unspent_sp=sum(_gain_fields(g)["skill_pts"] for g in gain_infos),
        motivation=int(chara.get("motivation", 0) or 0),
        vital=int(chara.get("vital", 0) or 0),
        races_run=len(raw.get("RaceHistory", []) or []),
        contributions=contributions,
        hints=hints,
        factors_by_year=factors_by_year,
        races=races,
        score_summary=_score_summary(raw),
        plan=_plan_rows(raw),
    )


def _score_summary(raw: dict) -> dict:
    """Compact score decomposition for the detail header."""
    try:
        est = estimate_from_run_json(raw)
    except (KeyError, IndexError, ValueError):
        return {}
    return {
        "stat_score": est.stat_score,
        "owned_skill_score": est.owned_skill_score,
        "floor": est.floor,
        "naive_ceiling": est.naive_ceiling,
        "planned_score": est.planned_score,
        "unspent_sp": est.unspent_sp,
        "sp_spent_in_plan": est.sp_spent_in_plan,
        "rank_floor": est.rank_floor,
        "rank_planned": est.rank_planned,
    }


def _plan_rows(raw: dict) -> list[dict]:
    """List of {skill_id, name, sp_cost, grade_value, value_per_sp}
    for the knapsack's chosen skills, best-value first."""
    try:
        est = estimate_from_run_json(raw)
    except (KeyError, IndexError, ValueError):
        return []
    return [
        {
            "skill_id": p.skill_id,
            "name": p.name,
            "sp_cost": p.sp_cost,
            "grade_value": p.grade_value,
            "value_per_sp": round(p.value_per_sp, 2),
        }
        for p in est.plan
    ]


def _label_for_gain_source(gi_idx: int, sup_cards: list[dict]) -> str:
    """Best-effort mapping of GainInfo index → source label. GainInfo[0]=
    Events, [1]=Inspiration, [2..7]=cards in reverse deck order."""
    if gi_idx == 0:
        return "Events"
    if gi_idx == 1:
        return "Inspiration"
    card_idx = len(sup_cards) - 1 - (gi_idx - 2)
    if 0 <= card_idx < len(sup_cards):
        cid = sup_cards[card_idx].get("<SupportCardId>k__BackingField", 0)
        return support_card_name(int(cid), with_rarity=False, with_type=False)
    return f"src#{gi_idx}"

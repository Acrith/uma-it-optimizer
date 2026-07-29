"""SS-grade score estimator.

Port of the ``finalScore_rank()`` logic from hzyhhzy/UmaAi (MIT license,
``UmaSimulator/Game/Game.cpp``). The formula is:

    score = Σ FiveStatusFinalScore[min(stat_i, cap_i)]        (5 stats)
          + int(ptScoreRate × unspent_sp + Σ owned_skill_scores)

Where:
- ``FiveStatusFinalScore`` is a 2801-int precomputed diminishing-returns
  curve (see ``data/five_status_score.py``)
- ``ptScoreRate = 2.0`` — the game's default SP-to-score conversion rate
- ``owned_skill_scores`` — sum of ``skill_data.grade_value`` for each skill
  the trainee currently owns (in ``chara.skill_array``)

We report three estimates:
- **floor** = score if the player spends *zero* additional SP (already-owned
  skills only). The realistic minimum.
- **naive ceiling** = score if unspent SP converts at flat 2.0×. Cheap upper
  bound; overestimates for players with mostly-bad hints.
- **smart ceiling** (planned_score) = knapsack-optimal skill purchase within
  the SP budget, using the actual (sp_cost, grade_value) per hint. This is
  the honest upper bound: 'buy the highest-value-per-SP skills first'.

Rank tiers come from ``masters.json.rank_tiers`` (98 tiers, sourced from
the game's ``single_mode_rank`` table).
"""
from __future__ import annotations

from dataclasses import dataclass

from collections import defaultdict

from .data.five_status_score import FIVE_STATUS_FINAL_SCORE
from .lookups import (
    discounted_sp,
    hint_group_variants,
    hint_levels_from_raw,
    innate_skills_for_card,
    load_masters,
    skill_from_hint,
)


PT_SCORE_RATE_DEFAULT = 2.0
FIVE_STATS = ("speed", "stamina", "power", "guts", "wiz")


@dataclass(frozen=True)
class SkillPurchase:
    """One skill the optimal purchase would buy."""
    skill_id: int
    name: str
    sp_cost: int
    grade_value: int
    value_per_sp: float
    group_id: int = 0    # hint group — used to keep white+gold pairs adjacent
    rarity: int = 1      # 1 = white / 2 = gold — used for sort order within group


@dataclass(frozen=True)
class ScoreEstimate:
    """Score decomposition for one run.

    Three ceilings: (1) naive_ceiling = flat 2.0×SP, (2) planned_score =
    knapsack-optimal purchase from actual hints. planned_score is the
    honest upper bound; naive_ceiling is a quick sanity check.
    """
    stat_score: int              # Σ FiveStatusFinalScore[stat]
    owned_skill_score: int       # Σ grade_value for owned skills
    unspent_sp: int              # SP left to spend
    sp_ceiling_bonus: int        # int(ptScoreRate × unspent_sp) — naive max
    floor: int                   # stat + owned_skill (no more SP spent)
    naive_ceiling: int           # floor + sp_ceiling_bonus
    planned_score: int           # floor + optimal knapsack purchase
    sp_spent_in_plan: int        # SP actually used by knapsack
    plan: tuple[SkillPurchase, ...]  # which skills the optimum buys
    rank_floor: int
    rank_planned: int            # rank tier of planned_score

    # For backwards-compat with earlier detail template using .ceiling
    @property
    def ceiling(self) -> int:
        return self.planned_score

    @property
    def rank_ceiling(self) -> int:
        return self.rank_planned

    def as_dict(self) -> dict:
        return {
            "stat_score": self.stat_score,
            "owned_skill_score": self.owned_skill_score,
            "unspent_sp": self.unspent_sp,
            "sp_ceiling_bonus": self.sp_ceiling_bonus,
            "floor": self.floor,
            "naive_ceiling": self.naive_ceiling,
            "planned_score": self.planned_score,
            "sp_spent_in_plan": self.sp_spent_in_plan,
            "plan": [
                {"skill_id": p.skill_id, "name": p.name,
                 "sp_cost": p.sp_cost, "grade_value": p.grade_value,
                 "value_per_sp": round(p.value_per_sp, 2)}
                for p in self.plan
            ],
            "rank_floor": self.rank_floor,
            "rank_planned": self.rank_planned,
        }


def _clip_stat(stat: int, cap: int) -> int:
    """Match the game: score is looked up at min(stat, cap), clamped to the
    table's index range [0, 2800]."""
    v = min(stat, cap)
    if v < 0:
        return 0
    if v > 2800:
        return 2800
    return v


def _stat_score(stats: dict[str, int], caps: dict[str, int]) -> int:
    """Σ FiveStatusFinalScore[min(stat, cap)] across the 5 stats."""
    total = 0
    for key in FIVE_STATS:
        s = int(stats.get(key, 0) or 0)
        c = int(caps.get(key, 0) or 2800)
        total += FIVE_STATUS_FINAL_SCORE[_clip_stat(s, c)]
    return total


def _owned_skill_score(skill_ids: list[int]) -> int:
    """Σ skill_data.grade_value for each owned skill (base only, no
    aptitude bucketing). Kept for backwards-compat; prefer
    ``_owned_skill_score_scoped`` which is aptitude-aware."""
    m = load_masters()
    skills = m.get("skills", {})
    total = 0
    for sid in skill_ids:
        s = skills.get(str(sid))
        if s:
            total += int(s.get("grade_value", 0) or 0)
    return total


# ── Rating formula ────────────────────────────────────────────────────
# The community rating formula (verified against UmaTools.calculator on
# 2026-07 which returned exactly 13,664 for a real capture):
#
#   rating = stat_score + skill_score + unique_bonus
#
# where:
#   stat_score  = Σ curve(stat) over 5 stats  (already implemented)
#   skill_score = Σ effective_value(skill)
#   unique_bonus = (170 if talent_level >= 3 else 120) × unique_skill_level
#
# effective_value applies two rules that base grade_value alone misses:
#   1) Aptitude bucket. Skills whose condition_1 mentions
#      running_style==N or distance_type==N get scaled by the trainee's
#      aptitude for that role: S/A → ×1.10, B/C → ×0.90, D/E/F → ×0.80,
#      G → ×0.70. Other skills use base grade_value.
#   2) White subsumes / gold owns. When both a ○ (rar 1) and ◎ (rar 2)
#      of the same group are owned, only the ◎'s value counts — the ○
#      is a prerequisite but its own grade_value is not added.

_APT_BUCKET_MULT = {
    # proper_running_style_* / proper_distance_* / proper_ground_* are
    # game ints 1..8 for G / F / E / D / C / B / A / S.
    1: 0.70, 2: 0.70,          # G, F  → terrible
    3: 0.80, 4: 0.80,          # E, D  → bad
    5: 0.90, 6: 0.90,          # C, B  → average
    7: 1.10, 8: 1.10,          # A, S  → good
}
_STYLE_MAP = {1: "nige", 2: "senko", 3: "sashi", 4: "oikomi"}
_DIST_MAP = {1: "short", 2: "mile", 3: "middle", 4: "long"}


def _apt_multiplier(condition_1: str, chara: dict) -> float:
    """Return the aptitude multiplier for a skill's activation condition.
    Non-aptitude skills return 1.0 (base value)."""
    if not condition_1:
        return 1.0
    import re
    m = re.search(r"running_style==(\d)", condition_1)
    if m:
        key = _STYLE_MAP.get(int(m.group(1)))
        if key:
            apt = int(chara.get(f"proper_running_style_{key}", 0) or 0)
            return _APT_BUCKET_MULT.get(apt, 1.0)
    m = re.search(r"distance_type==(\d)", condition_1)
    if m:
        key = _DIST_MAP.get(int(m.group(1)))
        if key:
            apt = int(chara.get(f"proper_distance_{key}", 0) or 0)
            return _APT_BUCKET_MULT.get(apt, 1.0)
    return 1.0


def _effective_skill_value(skill_id: int, chara: dict, skills_master: dict) -> int:
    """Base grade_value × aptitude bucket multiplier, rounded."""
    s = skills_master.get(str(skill_id))
    if not s:
        return 0
    base = int(s.get("grade_value", 0) or 0)
    mult = _apt_multiplier(s.get("condition_1") or "", chara)
    return round(base * mult)


def _dedupe_gold_subsumes_white(skill_ids: list[int], skills_master: dict) -> list[int]:
    """When both variants of the same skill group are present, drop the
    lower one. Discriminator is ``group_rate`` (not ``rarity``): rate 1
    is the ○ variant, rate 2 is the ◎ upgrade — for both auto-evolving
    green/blue pairs (both rar=1, e.g. Pace Chaser Corners ○/◎) and
    hint-bought gold upgrades (rar 1→2, e.g. Ramp Up → It's On!)."""
    info = {}
    for sid in skill_ids:
        s = skills_master.get(str(sid))
        if not s:
            continue
        info[sid] = (
            int(s.get("group_id", 0) or 0),
            int(s.get("group_rate", 1) or 1),
        )
    groups_with_gold = {g for (g, gr) in info.values() if gr == 2}
    return [sid for sid in skill_ids
            if not (info.get(sid, (0, 0))[0] in groups_with_gold
                    and info.get(sid, (0, 0))[1] == 1)]


def _owned_skill_score_scoped(chara: dict) -> int:
    """Aptitude-aware owned-skill sum from the trainee's skill_array.

    Excludes the unique skill (skill_array entries where level > 0)
    since the unique's rating contribution is delivered separately by
    ``_unique_bonus_from_chara`` — counting its base grade_value here
    too would double-count."""
    m = load_masters()
    skills = m.get("skills", {})
    sids = [
        int(entry.get("skill_id", 0) or 0)
        for entry in chara.get("skill_array", []) or []
        if int(entry.get("level", 0) or 0) == 0  # skip uniques
    ]
    kept = _dedupe_gold_subsumes_white(sids, skills)
    return sum(_effective_skill_value(sid, chara, skills) for sid in kept)


def _unique_bonus_from_chara(chara: dict) -> int:
    """Rating bonus contributed by the trainee's unique skill.

    Formula (community-verified): the trainee's unique-skill level from
    ``skill_array`` (typically 1..5), multiplied by 170 when their
    talent_level is 3+ or 120 otherwise. Level 0 = no bonus."""
    talent_level = int(chara.get("talent_level", 0) or 0)
    unique_level = 0
    for entry in chara.get("skill_array", []) or []:
        lv = int(entry.get("level", 0) or 0)
        if lv > unique_level:
            unique_level = lv
    if unique_level <= 0:
        return 0
    per_lvl = 170 if talent_level >= 3 else 120
    return per_lvl * unique_level


def optimal_purchase(
    available_skill_ids: list[int],
    owned_skill_ids: list[int],
    sp_budget: int,
) -> tuple[list[SkillPurchase], int, int]:
    """Solve 0/1 knapsack: max Σ grade_value subject to Σ sp_cost ≤ budget,
    over hint skills the player can buy (available - already owned).

    Returns (chosen list, total_value_added, sp_used).
    """
    m = load_masters()
    skills = m.get("skills", {})
    owned = set(owned_skill_ids)

    # Dedup + filter to skills with a valid cost that aren't already owned
    items: list[tuple[int, int, int]] = []  # (skill_id, cost, value)
    seen: set[int] = set()
    for sid in available_skill_ids:
        if sid in owned or sid in seen or sid == 0:
            continue
        s = skills.get(str(sid))
        if not s:
            continue
        cost = s.get("sp_cost")
        val = s.get("grade_value")
        if not cost or not val or cost <= 0:
            continue
        seen.add(sid)
        items.append((sid, int(cost), int(val)))

    if not items or sp_budget <= 0:
        return [], 0, 0

    # 0/1 knapsack — SP granularity is fine at 1 (SP costs are integers).
    # Budgets are usually 3-4K, item counts <100, so ~400K cells max.
    n = len(items)
    dp = [[0] * (sp_budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        _, cost, val = items[i - 1]
        row = dp[i]
        prev = dp[i - 1]
        for w in range(sp_budget + 1):
            row[w] = prev[w]
            if cost <= w and prev[w - cost] + val > row[w]:
                row[w] = prev[w - cost] + val

    # Backtrack to recover the chosen items
    chosen_ids: list[int] = []
    w = sp_budget
    total_value = dp[n][w]
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            sid, cost, _ = items[i - 1]
            chosen_ids.append(sid)
            w -= cost
    sp_used = sp_budget - w

    # Enrich to SkillPurchase, sort by best value-per-SP first
    plan: list[SkillPurchase] = []
    for sid in chosen_ids:
        s = skills[str(sid)]
        cost = int(s["sp_cost"])
        val = int(s["grade_value"])
        plan.append(SkillPurchase(
            skill_id=sid,
            name=s.get("name", f"?skill:{sid}"),
            sp_cost=cost,
            grade_value=val,
            value_per_sp=val / cost if cost else 0.0,
        ))
    plan.sort(key=lambda p: (-p.value_per_sp, -p.grade_value))
    return plan, total_value, sp_used


def _build_hint_group_options(raw: dict, owned_skill_ids: list[int]) -> list[dict]:
    """Per-group option packages for multi-choice knapsack.

    Each hint group contributes 0..N mutually-exclusive packages:
      - do nothing (implicit — knapsack always considers it)
      - buy just white variant W₁ (cost W₁.sp, value W₁.val)
      - buy white W₁ + gold G₁ (cost W₁.sp + G₁.sp, value W₁.val + G₁.val)
      - ...one entry per (white, [gold?]) combination.

    Enforces game rules:
      - Gold requires a white in the same group as prerequisite (both cost).
      - Only variants with the player's captured hint rarities count
        (with rarity=2 → rarity=1 auto-unlock, per game convention).
      - Skips × variants (negative value — knapsack would never pick).
      - Skips owned skills.
    """
    rarities_per_group: dict[int, set[int]] = defaultdict(set)
    for gi in raw.get("GainInfo", []) or []:
        for t in gi.get("<SkillTipsArray>k__BackingField", []) or []:
            if not isinstance(t, dict):
                continue
            gid = int(t.get("group_id", 0) or 0)
            rar = int(t.get("rarity", 0) or 0)
            if gid == 0:
                continue
            rarities_per_group[gid].add(rar)
    for _gid, rars in rarities_per_group.items():
        if 2 in rars:
            rars.add(1)  # gold-tier hint implicitly unlocks white

    # The trainee's INNATE skills (available_skill_set entries with
    # need_rank <= trainee_grade) also live in the skill panel from
    # turn 1 — they can be bought at full base SP even without a hint.
    # Merge them into the rarities-per-group map so the knapsack knows
    # they exist. If a hint DID proc for one of them, it stays in
    # rarities_per_group and gets the hint-level discount as usual.
    skills_master = load_masters().get("skills", {})
    try:
        chara = raw.get("SingleModeChara", [{}])[0]
        trainee_card_id = int(chara.get("card_id") or 0)
        trainee_grade = int(chara.get("chara_grade") or 0)
    except (KeyError, IndexError, ValueError):
        trainee_card_id, trainee_grade = 0, 0
    for entry in innate_skills_for_card(trainee_card_id):
        if int(entry.get("need_rank") or 0) > trainee_grade:
            continue
        sid = int(entry.get("skill_id") or 0)
        skill_row = skills_master.get(str(sid))
        if not skill_row:
            continue
        gid = int(skill_row.get("group_id") or 0)
        rar = int(skill_row.get("rarity") or 0)
        if gid == 0:
            continue
        rarities_per_group[gid].add(rar)
        # Golds implicitly unlock whites in the same group.
        if rar == 2:
            rarities_per_group[gid].add(1)

    hint_lvls = hint_levels_from_raw(raw)
    owned = set(owned_skill_ids)
    chara = (raw.get("SingleModeChara") or [{}])[0]
    skills_master = load_masters().get("skills", {})
    groups: list[dict] = []
    for gid, avail_rarities in rarities_per_group.items():
        raw_variants = hint_group_variants(gid, hint_level_by_skill=hint_lvls)
        # Filter × 'buy' options — those can't be purchased from hints.
        # Owned × are exposed via separate removal packages below.
        variants = [v for v in raw_variants
                    if v["rarity"] in avail_rarities
                    and v["skill_id"] not in owned
                    and v["grade_value"] > 0]
        whites = [v for v in variants if v["rarity"] == 1]
        golds = [v for v in variants if v["rarity"] == 2]

        # Owned × in this group → each becomes a standalone "removal" package
        # (pay sp_cost, gain |grade_value| since the -N penalty is lifted).
        removals: list[dict] = []
        for v in raw_variants:
            if v["skill_id"] in owned and v["grade_value"] < 0:
                removals.append({
                    "cost": v["sp_cost"],
                    "value": -v["grade_value"],
                    "skill_ids": (v["skill_id"],),
                })

        if not whites and not golds and not removals:
            continue

        # Package values reflect the community-verified rating formula:
        # aptitude buckets applied, and ◎ SUBSUMES ○ when both are bought
        # (only the ◎'s effective value is counted, ○ is a prerequisite).
        def _eff(v):
            return _effective_skill_value(v["skill_id"], chara, skills_master)

        packages: list[dict] = [{"cost": 0, "value": 0, "skill_ids": ()}]
        for w in whites:
            packages.append({
                "cost": w["sp_cost"], "value": _eff(w),
                "skill_ids": (w["skill_id"],),
            })
            for g in golds:
                packages.append({
                    "cost": w["sp_cost"] + g["sp_cost"],
                    # ◎ subsumes ○ — value = only the gold's effective
                    # value (matches game / UmaTools calc).
                    "value": _eff(g),
                    "skill_ids": (w["skill_id"], g["skill_id"]),
                })
        # Each × removal is independent of buy decisions — but our multi-
        # choice knapsack picks ONE package per group. So we bundle: a
        # removal can be added on top of every buy package.
        if removals:
            base_packages = list(packages)
            for r in removals:
                for base in base_packages:
                    packages.append({
                        "cost": base["cost"] + r["cost"],
                        "value": base["value"] + r["value"],
                        "skill_ids": base["skill_ids"] + r["skill_ids"],
                    })

        groups.append({"group_id": gid, "packages": packages})
    return groups


def optimal_purchase_grouped(
    hint_group_options: list[dict],
    sp_budget: int,
    hint_level_by_skill: dict[int, int] | None = None,
    chara: dict | None = None,
) -> tuple[list["SkillPurchase"], int, int]:
    """Multi-choice knapsack: pick at most one package per hint group,
    maximize Σ value subject to Σ cost ≤ budget.

    Each package is (cost, value, skill_ids_bought). One package per
    group represents 'do nothing / buy white / buy white+gold'.
    """
    if not hint_group_options or sp_budget <= 0:
        return [], 0, 0

    n = len(hint_group_options)
    # dp[i][w] = best value using first i groups within budget w
    # choice[i][w] = which package index of group i-1 was picked
    dp = [[0] * (sp_budget + 1) for _ in range(n + 1)]
    choice = [[0] * (sp_budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        packages = hint_group_options[i - 1]["packages"]
        for w in range(sp_budget + 1):
            best_v = dp[i - 1][w]
            best_pkg = 0
            for pkg_idx, pkg in enumerate(packages):
                c = pkg["cost"]
                if c <= w:
                    v = dp[i - 1][w - c] + pkg["value"]
                    if v > best_v:
                        best_v = v
                        best_pkg = pkg_idx
            dp[i][w] = best_v
            choice[i][w] = best_pkg

    total_value = dp[n][sp_budget]
    chosen_sids: list[int] = []
    w = sp_budget
    for i in range(n, 0, -1):
        pkg_idx = choice[i][w]
        pkg = hint_group_options[i - 1]["packages"][pkg_idx]
        chosen_sids.extend(pkg["skill_ids"])
        w -= pkg["cost"]
    sp_used = sp_budget - w

    skills = load_masters().get("skills", {})
    # For per-row display we still show each picked skill (both ○ and
    # ◎ if the knapsack chose the paired package), but the value shown
    # is the RATING contribution: base × aptitude bucket for the gold
    # (which subsumes the white), and 0 for the white when its group's
    # gold is also picked. The knapsack's total_value already reflects
    # this rule; we mirror it here so per-row values sum to the same.
    chara = chara or {}
    picked_group_rates: dict[int, set[int]] = {}
    for sid in chosen_sids:
        s = skills.get(str(sid))
        if not s:
            continue
        gid = int(s.get("group_id", 0) or 0)
        gr = int(s.get("group_rate", 1) or 1)
        picked_group_rates.setdefault(gid, set()).add(gr)

    plan: list[SkillPurchase] = []
    for sid in chosen_sids:
        s = skills.get(str(sid))
        if not s:
            continue
        base_cost = int(s.get("sp_cost") or 0)
        lv = (hint_level_by_skill or {}).get(sid, 0)
        cost = discounted_sp(base_cost, lv) if base_cost else 0
        gid = int(s.get("group_id", 0) or 0)
        gr = int(s.get("group_rate", 1) or 1)
        # Rating contribution: 0 for a ○ (group_rate=1) whose upgrade
        # ◎ (group_rate=2) is also in the plan (subsumed); otherwise
        # effective_skill_value with the aptitude bucket applied.
        upgrade_present = 2 in picked_group_rates.get(gid, set())
        val = 0 if (gr == 1 and upgrade_present) else _effective_skill_value(sid, chara, skills)
        plan.append(SkillPurchase(
            skill_id=sid,
            name=s.get("name", f"?skill:{sid}"),
            sp_cost=cost,
            grade_value=val,
            value_per_sp=val / cost if cost else 0.0,
            group_id=gid,
            rarity=int(s.get("rarity", 1) or 1),
        ))
    # Sort so paired picks are adjacent: whites before their golds within
    # a group. Groups ordered by the best value/SP any pick in them
    # achieved (so highest-impact groups sit at the top). Precompute the
    # per-group best to keep the sort key trivial.
    best_vps: dict[int, float] = {}
    for p in plan:
        cur = best_vps.get(p.group_id)
        if cur is None or p.value_per_sp > cur:
            best_vps[p.group_id] = p.value_per_sp
    plan.sort(key=lambda p: (-best_vps.get(p.group_id, 0.0), p.group_id, p.rarity))
    return plan, total_value, sp_used


def _rank_for_score(score: int) -> int:
    """Look up numeric rank tier for a score. Returns highest tier if score
    exceeds all thresholds; returns 1 for negative/zero scores."""
    m = load_masters()
    tiers = m.get("rank_tiers", [])
    if not tiers:
        return 0
    if score <= 0:
        return tiers[0]["rank"]
    for tier in tiers:
        if tier["min"] <= score <= tier["max"]:
            return tier["rank"]
    return tiers[-1]["rank"]


def estimate(*,
             stats: dict[str, int],
             caps: dict[str, int],
             owned_skill_ids: list[int],
             available_hint_skill_ids: list[int] | None = None,
             unspent_sp: int,
             pt_score_rate: float = PT_SCORE_RATE_DEFAULT) -> ScoreEstimate:
    """Compute floor + both ceiling estimates for one captured state."""
    stat = _stat_score(stats, caps)
    owned = _owned_skill_score(owned_skill_ids)
    sp_bonus = int(pt_score_rate * unspent_sp)
    floor = stat + owned
    naive_ceiling = floor + sp_bonus

    if available_hint_skill_ids:
        plan, plan_value, sp_used = optimal_purchase(
            available_hint_skill_ids, owned_skill_ids, unspent_sp
        )
    else:
        plan, plan_value, sp_used = [], 0, 0

    planned_score = floor + plan_value
    return ScoreEstimate(
        stat_score=stat,
        owned_skill_score=owned,
        unspent_sp=unspent_sp,
        sp_ceiling_bonus=sp_bonus,
        floor=floor,
        naive_ceiling=naive_ceiling,
        planned_score=planned_score,
        sp_spent_in_plan=sp_used,
        plan=tuple(plan),
        rank_floor=_rank_for_score(floor),
        rank_planned=_rank_for_score(planned_score),
    )


def estimate_from_run_json(raw: dict) -> ScoreEstimate:
    """Build a ScoreEstimate from a run's raw JSON. Uses the multi-choice
    knapsack over per-group option packages so gold picks always come
    bundled with their required white prerequisite (both costs paid)."""
    chara = raw["SingleModeChara"][0]
    stats = {k: int(chara.get(k, 0) or 0) for k in FIVE_STATS}
    caps = {k: int(chara.get(f"max_{k}", 0) or 0) for k in FIVE_STATS}
    owned = [int(s.get("skill_id", 0) or 0)
             for s in chara.get("skill_array", []) or []]

    unspent_sp = sum(
        int(gi.get("<SkillPoint>k__BackingField", 0) or 0)
        for gi in raw.get("GainInfo", []) or []
    )

    stat = _stat_score(stats, caps)
    # Aptitude-aware owned-skill sum + unique-skill bonus (170/120 per
    # unique-level based on talent_level). These two together with
    # stat_score reproduce UmaTools' rating exactly for this account
    # (verified 2026-07: 7902 + 5082 + 680 = 13,664 A+).
    owned_val = _owned_skill_score_scoped(chara)
    unique_bonus = _unique_bonus_from_chara(chara)
    sp_bonus = int(PT_SCORE_RATE_DEFAULT * unspent_sp)
    floor = stat + owned_val + unique_bonus
    naive_ceiling = floor + sp_bonus

    hint_groups_opts = _build_hint_group_options(raw, owned)
    hint_lvls = hint_levels_from_raw(raw)
    plan, plan_value, sp_used = optimal_purchase_grouped(
        hint_groups_opts, unspent_sp,
        hint_level_by_skill=hint_lvls, chara=chara,
    )
    planned_score = floor + plan_value

    return ScoreEstimate(
        stat_score=stat,
        owned_skill_score=owned_val + unique_bonus,
        unspent_sp=unspent_sp,
        sp_ceiling_bonus=sp_bonus,
        floor=floor,
        naive_ceiling=naive_ceiling,
        planned_score=planned_score,
        sp_spent_in_plan=sp_used,
        plan=tuple(plan),
        rank_floor=_rank_for_score(floor),
        rank_planned=_rank_for_score(planned_score),
    )

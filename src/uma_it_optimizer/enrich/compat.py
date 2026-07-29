"""Parent compatibility scoring for Umamusume Independent Training runs.

Base pair compat (verified against Special Week reference numbers on
2026-07-29) is a pure set intersection: shared `succession_relation_member`
groups between two chara_ids, weighted by that group's `relation_point`.

Overall compat (◎/○/△ shown at run start) is documented by community
guides as the sum of ALL lineage pair scores plus overlapping G1-race
bonuses, thresholded through `succession_relation_rank` (≤50/△,
51–150/○, 151+/◎). The exact pair weighting for grandparent race
overlap isn't fully documented; this module implements the
straightforward reading and exposes the full breakdown so any
discrepancy against the in-game symbol is visible.

Global has used the post-2026-06-24 formula game-wide:
- Only G1 races contribute race overlap (grade=100).
- +3 per shared unique G1 race (no bonus for running the same race twice).
- Parent-to-parent race overlap now counts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .lookups import load_masters, uma_card_name


G1_GRADE = 100
G1_BONUS_PER_RACE = 3


@dataclass(frozen=True)
class PairScore:
    """Score for a single lineage pair (e.g. trainee × parent1)."""
    label: str
    a_name: str
    b_name: str
    base_points: int         # shared-relation-group sum
    g1_overlap_count: int    # unique overlapping G1 races
    g1_bonus: int            # g1_overlap_count * 3
    total: int               # base + g1_bonus


@dataclass(frozen=True)
class OverallCompat:
    total_points: int
    rank: int                # 1=△ 2=○ 3=◎ (per succession_relation_rank)
    symbol: str              # '△' | '○' | '◎'
    pairs: tuple[PairScore, ...] = field(default_factory=tuple)


_SYMBOL_BY_RANK = {1: "△", 2: "○", 3: "◎"}


def _relations_for(chara_id: int) -> set[int]:
    m = load_masters()
    return set(m.get("chara_relations", {}).get(str(chara_id)) or [])


def _points_for_type(rt: int) -> int:
    m = load_masters()
    return int((m.get("relation_points") or {}).get(str(rt), 0))


def base_pair_score(chara_a: int, chara_b: int) -> int:
    """Sum of `relation_point` over shared relation groups.

    Verified against Special Week reference (all top-10 pairs matched
    exactly: Narita Brian=37, Nice Nature=37, T.M. Opera O=35, etc.).
    """
    if not chara_a or not chara_b or chara_a == chara_b:
        return 0
    shared = _relations_for(chara_a) & _relations_for(chara_b)
    return sum(_points_for_type(rt) for rt in shared)


def _race_id_of_program(program_id: int) -> int | None:
    m = load_masters()
    p = (m.get("programs") or {}).get(str(program_id))
    return int(p["race_id"]) if p else None


def _race_id_of_instance(race_instance_id: int) -> int | None:
    m = load_masters()
    rid = (m.get("race_instances") or {}).get(str(race_instance_id))
    return int(rid) if rid is not None else None


def _is_g1(race_id: int | None) -> bool:
    if race_id is None:
        return False
    m = load_masters()
    r = (m.get("races") or {}).get(str(race_id))
    return bool(r and int(r.get("grade") or 0) == G1_GRADE)


def g1_race_ids_from_programs(program_ids: Iterable[int]) -> set[int]:
    """Deduped set of G1 race_ids from a list of single-mode program_ids
    (used for direct parents with full `<SingleModeRaceResultArray>`)."""
    out: set[int] = set()
    for pid in program_ids:
        if not pid:
            continue
        rid = _race_id_of_program(int(pid))
        if _is_g1(rid) and rid is not None:
            out.add(rid)
    return out


def g1_race_ids_from_saddles(saddle_ids: Iterable[int]) -> set[int]:
    """Deduped set of G1 race_ids from a list of win-saddle ids.

    Grandparents (`SuccessionCharaData`) only carry `_winSaddleIdArray`;
    each saddle stands for up to 8 race_instance_ids (Triple-Crown
    titles). Expand all, keep the G1s, dedupe."""
    m = load_masters()
    saddles = m.get("win_saddles") or {}
    out: set[int] = set()
    for sid in saddle_ids:
        if not sid:
            continue
        s = saddles.get(str(sid))
        if not s:
            continue
        for rinst in s.get("race_instance_ids") or []:
            rid = _race_id_of_instance(int(rinst))
            if _is_g1(rid) and rid is not None:
                out.add(rid)
    return out


def _threshold_rank(total: int) -> int:
    m = load_masters()
    for t in m.get("compat_thresholds") or []:
        lo, hi = int(t["min"]), int(t["max"])
        if lo <= total <= hi:
            return int(t["rank"])
    return 1


@dataclass
class LineageMember:
    """Any node in the compat graph — trainee, parent, or grandparent.

    ``g1_race_ids`` is pre-computed by the caller (via
    ``g1_race_ids_from_programs`` for the trainee and direct parents, or
    ``g1_race_ids_from_saddles`` for grandparents)."""
    chara_id: int
    name: str
    g1_race_ids: set[int] = field(default_factory=set)


def compute_overall(
    trainee: LineageMember,
    p1: LineageMember,
    p2: LineageMember,
    gp1a: LineageMember | None = None,
    gp1b: LineageMember | None = None,
    gp2a: LineageMember | None = None,
    gp2b: LineageMember | None = None,
) -> OverallCompat:
    """Compute overall compat score + symbol.

    Pair structure (per community/domain-expert consensus): grandparent
    compat feeds through its parent — the trainee never pairs directly
    with a grandparent. Six pairs total, plus a seventh for the
    post-2026-06-24 parent↔parent race-overlap rule.

    - trainee ↔ parent 1                (base only — see race-overlap note)
    - trainee ↔ parent 2                (base only)
    - parent 1 ↔ grandparent 1a         (base + G1 overlap)
    - parent 1 ↔ grandparent 1b         (base + G1 overlap)
    - parent 2 ↔ grandparent 2a         (base + G1 overlap)
    - parent 2 ↔ grandparent 2b         (base + G1 overlap)
    - parent 1 ↔ parent 2               (base + G1 overlap)

    **Race-overlap only applies to non-trainee pairs.** The compat
    symbol that drives spark chance is what the game computes at run
    START — when the trainee has zero races. Base compat still counts
    for trainee↔parent pairs (chara-group intersection is a static
    property of the two umas, independent of race history), but G1
    overlap doesn't. Post-run captures include the trainee's race
    history, but adding it here would compute a hypothetical post-hoc
    number that never affected the run.
    """
    pairs: list[PairScore] = []

    def add_pair(label: str, a: LineageMember, b: LineageMember, *, count_overlap: bool):
        base = base_pair_score(a.chara_id, b.chara_id)
        if count_overlap:
            overlap = a.g1_race_ids & b.g1_race_ids
            n_overlap = len(overlap)
            bonus = n_overlap * G1_BONUS_PER_RACE
        else:
            n_overlap = 0
            bonus = 0
        pairs.append(PairScore(
            label=label, a_name=a.name, b_name=b.name,
            base_points=base, g1_overlap_count=n_overlap,
            g1_bonus=bonus, total=base + bonus,
        ))

    # Trainee pairs: base only. The compat symbol the game shows at run
    # start is computed BEFORE the trainee has raced, so their G1 race
    # set is empty by definition at that moment.
    add_pair("trainee × parent 1", trainee, p1, count_overlap=False)
    add_pair("trainee × parent 2", trainee, p2, count_overlap=False)
    # Non-trainee pairs: base + G1 overlap
    for parent, gp, lbl in (
        (p1, gp1a, "parent 1 × grandparent 1a"),
        (p1, gp1b, "parent 1 × grandparent 1b"),
        (p2, gp2a, "parent 2 × grandparent 2a"),
        (p2, gp2b, "parent 2 × grandparent 2b"),
    ):
        if gp is not None:
            add_pair(lbl, parent, gp, count_overlap=True)
    add_pair("parent 1 × parent 2", p1, p2, count_overlap=True)

    total = sum(p.total for p in pairs)
    rank = _threshold_rank(total)
    return OverallCompat(
        total_points=total,
        rank=rank,
        symbol=_SYMBOL_BY_RANK.get(rank, "?"),
        pairs=tuple(pairs),
    )


# ── raw-JSON → lineage helpers ─────────────────────────────────────────
# The extractor dumps two direct parents (matched by
# succession_trained_chara_id_1/_2 from SingleModeChara) into
# ``raw["Parents"]``. Each entry contains _cardId, _cacheCharaId,
# _winSaddleIdArray, <SingleModeRaceResultArray>, and a
# <SuccessionCharaList> holding up to 6 SuccessionCharaData items
# (2 direct grandparents at positions 10/20, plus 4 great-grandparents at
# 11/12/21/22 which don't count per the community algorithm).

_DIRECT_GRANDPARENT_POSITIONS = {10, 20}


def _card_id_to_chara_id(card_id: int | None) -> int | None:
    if not card_id:
        return None
    m = load_masters()
    c = (m.get("uma_cards") or {}).get(str(card_id))
    return int(c["chara_id"]) if c else None


@dataclass(frozen=True)
class ParentSummary:
    """UI-friendly view of one direct parent + its two grandparents."""
    card_id: int
    chara_id: int
    name: str
    rank: int
    speed: int
    stamina: int
    power: int
    guts: int
    wiz: int
    fans: int
    factor_ids: tuple[int, ...]
    saddle_ids: tuple[int, ...]
    grandparents: tuple[tuple[int, int, str, int], ...]  # (card_id, chara_id, name, rank)


@dataclass(frozen=True)
class LineageBundle:
    trainee: LineageMember
    p1: LineageMember | None
    p2: LineageMember | None
    gp1a: LineageMember | None
    gp1b: LineageMember | None
    gp2a: LineageMember | None
    gp2b: LineageMember | None
    p1_summary: ParentSummary | None
    p2_summary: ParentSummary | None


def _parent_program_ids(parent: dict[str, Any]) -> set[int]:
    """Program IDs the direct parent RAN (not just won). Used for the
    G1 overlap bonus on trainee↔parent pairs."""
    arr = parent.get("<SingleModeRaceResultArray>k__BackingField") or []
    out: set[int] = set()
    for entry in arr:
        if isinstance(entry, dict):
            pid = entry.get("_programId")
            if isinstance(pid, int) and pid > 0:
                out.add(pid)
    return out


def _grandparent_saddle_ids(gp: dict[str, Any]) -> tuple[int, ...]:
    saddles = gp.get("_winSaddleIdArray") or []
    if not isinstance(saddles, list):
        return ()
    return tuple(int(s) for s in saddles if isinstance(s, int) and s > 0)


def _summarize_parent(parent: dict[str, Any]) -> ParentSummary:
    card_id = int(parent.get("_cardId") or 0)
    chara_id = int(parent.get("_cacheCharaId") or _card_id_to_chara_id(card_id) or 0)
    factors = parent.get("<FactorDataArray>k__BackingField") or []
    factor_ids = tuple(
        int(f.get("<FactorId>k__BackingField") or 0)
        for f in factors if isinstance(f, dict)
    )
    saddles = parent.get("_winSaddleIdArray") or []
    saddle_ids = tuple(int(s) for s in saddles if isinstance(s, int) and s > 0)

    gps: list[tuple[int, int, str, int]] = []
    scl = (parent.get("<SuccessionCharaList>k__BackingField") or {}).get("_items") or []
    for entry in scl:
        if not isinstance(entry, dict):
            continue
        if int(entry.get("_positionId") or 0) not in _DIRECT_GRANDPARENT_POSITIONS:
            continue
        gp_card = int(entry.get("<CardId>k__BackingField") or 0)
        gp_chara = _card_id_to_chara_id(gp_card) or 0
        gps.append((
            gp_card, gp_chara, uma_card_name(gp_card),
            int(entry.get("_rank") or 0),
        ))

    return ParentSummary(
        card_id=card_id,
        chara_id=chara_id,
        name=uma_card_name(card_id),
        rank=int(parent.get("_rank") or 0),
        speed=int(parent.get("_speed") or 0),
        stamina=int(parent.get("_stamina") or 0),
        power=int(parent.get("_power") or 0),
        guts=int(parent.get("_guts") or 0),
        wiz=int(parent.get("_wiz") or 0),
        fans=int(parent.get("_fans") or 0),
        factor_ids=factor_ids,
        saddle_ids=saddle_ids,
        grandparents=tuple(gps),
    )


def _grandparent_member(parent: dict[str, Any], position_id: int) -> LineageMember | None:
    scl = (parent.get("<SuccessionCharaList>k__BackingField") or {}).get("_items") or []
    for entry in scl:
        if not isinstance(entry, dict):
            continue
        if int(entry.get("_positionId") or 0) != position_id:
            continue
        card = int(entry.get("<CardId>k__BackingField") or 0)
        chara = _card_id_to_chara_id(card) or 0
        return LineageMember(
            chara_id=chara,
            name=uma_card_name(card) if card else f"?gp:{position_id}",
            g1_race_ids=g1_race_ids_from_saddles(_grandparent_saddle_ids(entry)),
        )
    return None


def parse_lineage(raw_run: dict[str, Any]) -> LineageBundle | None:
    """Extract a ``LineageBundle`` from a run JSON dumped by the parent-aware
    extractor. Returns None if the run pre-dates the parent-capture feature
    (v0.1.5) or lacks the expected keys."""
    parents = raw_run.get("Parents") or []
    if not parents or not isinstance(parents, list):
        return None
    smc_arr = raw_run.get("SingleModeChara") or []
    smc = smc_arr[0] if smc_arr else {}

    trainee_card = int(smc.get("card_id") or 0)
    trainee_chara = _card_id_to_chara_id(trainee_card) or 0
    trainee_races: set[int] = set()
    for r in raw_run.get("RaceHistory", []) or []:
        pid = r.get("program_id") if isinstance(r, dict) else None
        if isinstance(pid, int) and pid > 0:
            trainee_races.add(pid)
    trainee = LineageMember(
        chara_id=trainee_chara,
        name=uma_card_name(trainee_card) if trainee_card else "?trainee",
        g1_race_ids=g1_race_ids_from_programs(trainee_races),
    )

    def _parent_member(parent: dict[str, Any] | None) -> LineageMember | None:
        if not parent:
            return None
        card = int(parent.get("_cardId") or 0)
        chara = int(parent.get("_cacheCharaId") or _card_id_to_chara_id(card) or 0)
        return LineageMember(
            chara_id=chara,
            name=uma_card_name(card) if card else "?parent",
            g1_race_ids=g1_race_ids_from_programs(_parent_program_ids(parent)),
        )

    p1_raw = parents[0] if len(parents) > 0 else None
    p2_raw = parents[1] if len(parents) > 1 else None
    p1 = _parent_member(p1_raw)
    p2 = _parent_member(p2_raw)

    gp1a = _grandparent_member(p1_raw, 10) if p1_raw else None
    gp1b = _grandparent_member(p1_raw, 20) if p1_raw else None
    gp2a = _grandparent_member(p2_raw, 10) if p2_raw else None
    gp2b = _grandparent_member(p2_raw, 20) if p2_raw else None

    return LineageBundle(
        trainee=trainee,
        p1=p1, p2=p2,
        gp1a=gp1a, gp1b=gp1b, gp2a=gp2a, gp2b=gp2b,
        p1_summary=_summarize_parent(p1_raw) if p1_raw else None,
        p2_summary=_summarize_parent(p2_raw) if p2_raw else None,
    )


def overall_from_lineage(lb: LineageBundle) -> OverallCompat | None:
    if lb.p1 is None or lb.p2 is None:
        return None
    return compute_overall(
        trainee=lb.trainee,
        p1=lb.p1, p2=lb.p2,
        gp1a=lb.gp1a, gp1b=lb.gp1b,
        gp2a=lb.gp2a, gp2b=lb.gp2b,
    )

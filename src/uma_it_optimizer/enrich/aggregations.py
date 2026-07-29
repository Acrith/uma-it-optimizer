"""Cross-run aggregations. Turn a list of individual RunMetrics into
per-deck / per-trainee summary tables — the "which of my setups actually
works best" view.

Only completed runs contribute to aggregate stats. Pre-training captures
are excluded upstream via ``[r for r in runs if r.run_state == 'completed']``
before being passed in.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from .lookups import (
    deck_summary,
    deck_type_composition,
    grade_icon_url,
    letter_grade,
    scenario_name,
    support_card_image_url,
    support_card_name,
    support_card_type_icon_url,
    uma_card_name,
)
from .run_metrics import RunMetrics


@dataclass(frozen=True)
class DeckAggregate:
    deck_hash: str
    deck_card_ids: tuple[int, ...]
    deck_limit_breaks: tuple[int, ...]   # per-card mode LB across the runs in this bucket
    deck_summary: str
    type_composition: dict[str, int]
    runs: int
    trainees: tuple[str, ...]          # sorted unique names
    scenarios: tuple[str, ...]         # sorted unique names
    avg_stat_sum: int
    best_stat_sum: int
    avg_fans: int
    best_fans: int
    avg_unspent_sp: int
    avg_factors: float
    avg_score: int                     # avg planned-score across the bucket
    best_score: int
    # Grade range (worst floor letter → best ceiling letter) across the bucket
    worst_rank: int
    best_rank: int

    def as_row(self) -> dict[str, object]:
        return {
            "deck_hash": self.deck_hash,
            "deck_summary": self.deck_summary,
            "deck_thumbnails": [support_card_image_url(c) for c in self.deck_card_ids],
            # Deck-aggregate rows can't show per-run LB (varies by run) —
            # emit type icon + image but leave limit_break null so the UI
            # shows the card without crystals.
            "deck_cards": [
                {
                    "card_id": cid,
                    "name": support_card_name(cid),
                    "image_url": support_card_image_url(cid),
                    "type_icon_url": support_card_type_icon_url(cid),
                    "limit_break": lb,
                }
                for cid, lb in zip(self.deck_card_ids, self.deck_limit_breaks, strict=False)
            ],
            "type_composition": self.type_composition,
            "type_label": " / ".join(
                f"{n}×{t}" for t, n in sorted(
                    self.type_composition.items(), key=lambda kv: -kv[1]
                )
            ),
            "runs": self.runs,
            "trainees": list(self.trainees),
            "trainees_label": ", ".join(self.trainees),
            "scenarios": list(self.scenarios),
            "scenarios_label": ", ".join(self.scenarios),
            "avg_stat_sum": self.avg_stat_sum,
            "best_stat_sum": self.best_stat_sum,
            "avg_fans": self.avg_fans,
            "best_fans": self.best_fans,
            "avg_unspent_sp": self.avg_unspent_sp,
            "avg_factors": round(self.avg_factors, 1),
            "avg_score": self.avg_score,
            "best_score": self.best_score,
            "worst_rank": self.worst_rank,
            "best_rank": self.best_rank,
            "worst_grade_letter": letter_grade(self.worst_rank) if self.worst_rank else None,
            "best_grade_letter": letter_grade(self.best_rank) if self.best_rank else None,
            "worst_grade_icon": (grade_icon_url(letter_grade(self.worst_rank))
                                 if self.worst_rank else None),
            "best_grade_icon": (grade_icon_url(letter_grade(self.best_rank))
                                if self.best_rank else None),
        }


def by_deck(runs: list[RunMetrics]) -> list[DeckAggregate]:
    """Group runs by deck_hash, one aggregate per unique deck.

    Sorts result by (runs desc, best_fans desc) — most-used first, then
    best-performing among ties. Only rows for completed runs make sense
    here; caller is expected to filter."""
    buckets: dict[str, list[RunMetrics]] = {}
    for r in runs:
        buckets.setdefault(r.deck_hash, []).append(r)

    out: list[DeckAggregate] = []
    for deck_hash, bucket in buckets.items():
        # deck_card_ids come from the first run (all runs in bucket share it by definition)
        deck_ids = bucket[0].deck_card_ids
        # LB per card: take the mode across the runs in this bucket
        # (most players don't change LB between runs of the same deck,
        # so this is usually stable — mode handles the rare edge case
        # where they levelled a card up mid-collection).
        from collections import Counter
        deck_lbs = tuple(
            Counter(r.deck_limit_breaks[i] for r in bucket
                    if i < len(r.deck_limit_breaks))
                .most_common(1)[0][0]
            for i in range(len(deck_ids))
        )
        trainee_names = sorted({uma_card_name(r.trainee_card_id) for r in bucket})
        scen_names = sorted({scenario_name(r.scenario_id) for r in bucket})
        stats = [r.stat_sum for r in bucket]
        fans = [r.fans for r in bucket]
        sp = [r.unspent_sp for r in bucket]
        factors = [r.factors_total for r in bucket]
        # Score / grade — use the planned (knapsack ceiling) since that's
        # the honest 'this deck's best-case outcome' number, and floor
        # rank (worst grade) so the range shows how much SP-picking varies.
        scores = [r.score_ceiling for r in bucket if r.score_ceiling]
        rank_ceilings = [r.rank_ceiling for r in bucket if r.rank_ceiling]
        rank_floors = [r.rank_floor for r in bucket if r.rank_floor]
        out.append(DeckAggregate(
            deck_hash=deck_hash,
            deck_card_ids=deck_ids,
            deck_limit_breaks=deck_lbs,
            deck_summary=deck_summary(deck_ids),
            type_composition=deck_type_composition(deck_ids),
            runs=len(bucket),
            trainees=tuple(trainee_names),
            scenarios=tuple(scen_names),
            avg_stat_sum=int(statistics.mean(stats)),
            best_stat_sum=max(stats),
            avg_fans=int(statistics.mean(fans)),
            best_fans=max(fans),
            avg_unspent_sp=int(statistics.mean(sp)),
            avg_factors=statistics.mean(factors),
            avg_score=int(statistics.mean(scores)) if scores else 0,
            best_score=max(scores) if scores else 0,
            worst_rank=min(rank_floors) if rank_floors else 0,
            best_rank=max(rank_ceilings) if rank_ceilings else 0,
        ))
    # Sort by best_score desc so highest-ceiling decks lead
    out.sort(key=lambda a: (-a.best_score, -a.runs))
    return out

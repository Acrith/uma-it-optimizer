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
    scenario_name,
    support_card_image_url,
    uma_card_name,
)
from .run_metrics import RunMetrics


@dataclass(frozen=True)
class DeckAggregate:
    deck_hash: str
    deck_card_ids: tuple[int, ...]
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

    def as_row(self) -> dict[str, object]:
        return {
            "deck_hash": self.deck_hash,
            "deck_summary": self.deck_summary,
            "deck_thumbnails": [support_card_image_url(c) for c in self.deck_card_ids],
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
        trainee_names = sorted({uma_card_name(r.trainee_card_id) for r in bucket})
        scen_names = sorted({scenario_name(r.scenario_id) for r in bucket})
        stats = [r.stat_sum for r in bucket]
        fans = [r.fans for r in bucket]
        sp = [r.unspent_sp for r in bucket]
        factors = [r.factors_total for r in bucket]
        out.append(DeckAggregate(
            deck_hash=deck_hash,
            deck_card_ids=deck_ids,
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
        ))
    out.sort(key=lambda a: (-a.runs, -a.best_fans))
    return out

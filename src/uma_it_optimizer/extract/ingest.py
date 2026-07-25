"""Walk a run folder, auto-detect each shot's tab, run the right extractor.

The folder is expected to contain the raw PNGs for a single IT run —
one per tab (single-shot tabs) or one per scroll (multi-scroll tabs).
Names don't matter; classification is content-based via
:func:`detect_tab`. Scroll order within a multi-scroll tab is inferred
from file mtime (capture order).

Only extractors that exist today are wired in — Overview and
Aptitudes/Attributes scroll 1. Hints, Inspiration, and multi-scroll
merges land as their extractors are built.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uma_it_optimizer.extract.aptattr import extract_aptattr
from uma_it_optimizer.extract.hints import extract_hints_scroll
from uma_it_optimizer.extract.inspiration import extract_inspiration
from uma_it_optimizer.extract.overview import extract_overview
from uma_it_optimizer.extract.tab import TabKind, detect_tab


def ingest_run(folder: str | Path) -> dict[str, Any]:
    """Extract every field we currently know how to read from a run folder.

    Returns a dict shaped like::

        {
            "extracted": {...merged outcome fragments...},
            "grouped": {tab_kind: [Path, ...]},
            "skipped": [str, ...],  # human-readable reasons
        }
    """
    folder = Path(folder)
    pngs = sorted(folder.glob("*.png"))
    grouped: dict[TabKind, list[Path]] = {}
    for png in pngs:
        kind = detect_tab(png)
        grouped.setdefault(kind, []).append(png)
    # Within each tab, keep capture order (mtime asc). Assumes ALT+PRTSCR
    # or any tool that writes files as the shots are taken.
    for kind in grouped:
        grouped[kind].sort(key=lambda p: p.stat().st_mtime)

    extracted: dict[str, Any] = {}
    skipped: list[str] = []

    if TabKind.OVERVIEW in grouped:
        shots = grouped[TabKind.OVERVIEW]
        extracted.update(extract_overview(shots[0]))
        if len(shots) > 1:
            skipped.append(f"overview: {len(shots)} shots present, using the first")

    if TabKind.APTATTR in grouped:
        shots = grouped[TabKind.APTATTR]
        extracted.update(extract_aptattr(shots))

    if TabKind.HINTS in grouped:
        shots = grouped[TabKind.HINTS]
        # v0.1: only the first scroll; multi-scroll merge (section state
        # carry-over + card_slot assignment) is a follow-up.
        extracted["skill_hints_earned"] = extract_hints_scroll(shots[0])
        if len(shots) > 1:
            skipped.append(
                f"hints: {len(shots)} scrolls present, only scroll 1 parsed"
                " (multi-scroll merge not yet built — later scrolls hold more"
                " support-card and event skills)"
            )

    if TabKind.INSPIRATION in grouped:
        shots = grouped[TabKind.INSPIRATION]
        extracted.update(extract_inspiration(shots[0]))
        if len(shots) > 1:
            skipped.append(
                f"inspiration: {len(shots)} shots present, using the first"
                " (multi-scroll for large spark lists not yet built)"
            )

    if TabKind.CAREER in grouped:
        skipped.append(f"career: {len(grouped[TabKind.CAREER])} shots, tab intentionally skipped")

    if TabKind.UNKNOWN in grouped:
        skipped.append(
            f"unknown tab: {len(grouped[TabKind.UNKNOWN])} shots could not be classified"
        )

    return {"extracted": extracted, "grouped": grouped, "skipped": skipped}

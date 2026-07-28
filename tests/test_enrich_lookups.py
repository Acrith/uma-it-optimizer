from __future__ import annotations

import pytest

from uma_it_optimizer.enrich import lookups


def test_scenario_names_resolve():
    assert lookups.scenario_name(1) == "URA Finale"
    assert lookups.scenario_name(2) == "Unity Cup"
    assert lookups.scenario_name(3) == "Our Grand Concert"
    assert lookups.scenario_name(4) == "Trackblazer"


def test_scenario_unknown_falls_back():
    assert lookups.scenario_name(99) == "?scen:99"


def test_trainee_name_agnes_tachyon():
    # card_id 103201 == Agnes Tachyon variant 1
    assert lookups.uma_card_name(103201) == "Agnes Tachyon"


def test_trainee_name_other_umas_seen_in_captures():
    # From IT-references/allRuns
    assert lookups.uma_card_name(101601) == "Narita Brian"
    assert lookups.uma_card_name(100601) == "Oguri Cap"


def test_trainee_unknown_falls_back():
    assert lookups.uma_card_name(999999) == "?uma:999999"


def test_support_card_resolves_with_rarity_prefix():
    # From real Unity Cup capture: 30028 == SSR Kitasan Black
    assert lookups.support_card_name(30028) == "SSR Kitasan Black"
    # SR rarity 2 card
    assert lookups.support_card_name(20027).startswith("SR ")


def test_support_card_without_rarity():
    assert "SSR" not in lookups.support_card_name(30028, with_rarity=False)


def test_skill_agnes_unique():
    # skill_id 100321 is Agnes' unique skill; genuinely named "U=ma2"
    # (Einstein-style pun on E=mc²) — not a placeholder
    assert lookups.skill_name(100321) == "U=ma2"


def test_race_program_id_resolves():
    # program_id 1069 -> race_instance -> "Make Debut"
    assert lookups.race_name(1069) == "Make Debut"
    # 2225 -> URA Finale Finals
    assert "URA" in lookups.race_name(2225)


def test_deck_summary_composes_all_six():
    ids = [20027, 30074, 30010, 20031, 30028, 30003]  # Unity Cup deck
    summary = lookups.deck_summary(ids)
    assert "Kitasan Black" in summary
    assert summary.count(" / ") == 5   # 6 cards, 5 separators


def test_masters_bundled_snapshot_loads():
    """The bundled snapshot must have the expected top-level keys.
    Guards against a shipped-empty file or a schema drift."""
    m = lookups.load_masters()
    for key in ("scenarios", "umas", "uma_cards", "support_cards",
                "skills", "races", "programs", "factors"):
        assert key in m, f"masters.json missing top-level key: {key}"
    assert len(m["scenarios"]) == 4
    assert len(m["umas"]) >= 90
    assert len(m["skills"]) >= 700

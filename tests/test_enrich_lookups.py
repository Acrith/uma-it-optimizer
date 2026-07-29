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


def test_support_card_image_urls():
    small = lookups.support_card_image_url(30028)
    full = lookups.support_card_image_url(30028, size="full")
    assert small.endswith("/supports/support_card_s_30028.png")
    assert full.endswith("/supports/tex_support_card_30028.png")


def test_uma_card_image_url_uses_chara_and_card_ids():
    # Agnes Tachyon: chara_id=1032, card_id=103201
    thumb = lookups.uma_card_image_url(103201)
    full = lookups.uma_card_image_url(103201, size="full")
    assert thumb is not None and "chara_stand_1032_103201.png" in thumb
    assert "/thumb/" in thumb
    assert full is not None and "chara_stand_1032_103201.png" in full
    assert "/thumb/" not in full


def test_uma_card_image_url_unknown_returns_none():
    assert lookups.uma_card_image_url(999999) is None


def test_letter_grade_known_mappings():
    assert lookups.letter_grade(1) == "G"
    assert lookups.letter_grade(11) == "B"
    assert lookups.letter_grade(15) == "S"
    assert lookups.letter_grade(17) == "SS"
    assert lookups.letter_grade(18) == "SS+"
    # Above 18 = EX+N
    assert lookups.letter_grade(19) == "EX+1"
    assert lookups.letter_grade(98) == "EX+80"


def test_letter_grade_range_same_and_different():
    # Same tier → single letter
    assert lookups.letter_grade_range(15, 15) == "S"
    # Different → 'lo–hi'
    assert lookups.letter_grade_range(13, 17) == "A–SS"


def test_factor_name_stat_factor():
    # factor_id 103 = Stat group 1 (Speed), rarity 3 → 'Speed ★★★'
    assert lookups.factor_name(103) == "Speed ★★★"
    # 203 = group 2 (Stamina) rarity 3 → 'Stamina ★★★'
    assert lookups.factor_name(203) == "Stamina ★★★"
    # 102 = Speed rarity 2 → 'Speed ★★'
    assert lookups.factor_name(102) == "Speed ★★"


def test_factor_name_aptitude_factor():
    # From real capture: 3402 → group 34 (End), rarity 2 → 'End ★★'
    assert lookups.factor_name(3402) == "End ★★"
    # 3202 → group 32 (Pace) rarity 2 → 'Pace ★★'
    assert lookups.factor_name(3202) == "Pace ★★"


def test_factor_name_skill_factor():
    # factor_id 2003501 = skill group 20035 (Corner Recovery), rarity 1
    # → 'Corner Recovery ○ ★'
    name = lookups.factor_name(2003501)
    assert "Corner Recovery" in name
    assert "★" in name


def test_factor_name_unique_factor():
    # 10060102 = type 3, group 100601 (Nice Nature? or Kitasan?), rarity 2
    # Just verify shape — should say 'Unique: <name> ★★'
    name = lookups.factor_name(10060102)
    assert name.startswith("Unique:")
    assert "★★" in name


def test_factor_name_unknown_falls_back():
    assert lookups.factor_name(999999999) == "?factor:999999999"


def test_classify_skill_self_style_from_condition():
    # 'Pace Chaser Corners ○' condition: running_style==2 & all_corner_random==1
    c = lookups.classify_skill(condition_1="running_style==2&all_corner_random==1")
    assert c["styles"] == ["Pace"]
    assert c["distances"] == []


def test_classify_skill_self_distance_from_condition():
    # 'Long Corners ○' condition: distance_type==4 & all_corner_random==1
    c = lookups.classify_skill(condition_1="distance_type==4&all_corner_random==1")
    assert c["distances"] == ["Long"]


def test_classify_skill_opponent_count_is_universal():
    # 'Hesitant Pace Chasers': running_style_count_senko_otherself>=1
    # — triggers off OPPONENT count, not trainee → universal.
    c = lookups.classify_skill(
        condition_1="running_style_count_senko_otherself>=1&phase_random==2",
    )
    assert c["is_universal"] is True
    assert c["styles"] == []


def test_classify_skill_thunderbolt_step_is_medium():
    # 'Thunderbolt Step': distance_type==3&phase_random==1
    c = lookups.classify_skill(condition_1="distance_type==3&phase_random==1")
    assert c["distances"] == ["Medium"]


def test_classify_skill_always_condition_is_universal():
    c = lookups.classify_skill(condition_1="always==1")
    assert c["is_universal"] is True


def test_classify_skill_empty_conditions():
    c = lookups.classify_skill()
    assert c["is_universal"] is True


def test_hint_group_variants_include_classification():
    # Corner Recovery group — no style/distance keywords in that name
    variants = lookups.hint_group_variants(20033)
    assert variants
    for v in variants:
        assert "styles" in v and "distances" in v and "is_universal" in v


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

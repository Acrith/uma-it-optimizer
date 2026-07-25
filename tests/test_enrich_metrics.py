from __future__ import annotations

import json
from pathlib import Path

import pytest

from uma_it_optimizer.enrich.run_metrics import (
    FILENAME_RE,
    summarize,
    summarize_directory,
)


def _make_run_json(
    tmp_path: Path,
    name: str = "20260725T185207_scen2_uma103201.json",
    *,
    speed: int = 870,
    stamina: int = 519,
    power: int = 790,
    wiz: int = 631,
    guts: int = 404,
    fans: int = 959461,
    talent_level: int = 5,
    deck_ids: tuple[int, ...] = (20027, 20031, 30015, 30089, 30201, 30310),
    factors_per_year: tuple[int, ...] = (13, 13, 13),
    gain_infos_sp: tuple[int, ...] = (2897, 0, 0, 0, 0, 0, 0, 0),
    race_count: int = 40,
    skills_owned: int = 1,
    hints_per_gain: tuple[int, ...] = (23, 3, 3, 3, 3, 3, 3, 3),
) -> Path:
    payload = {
        "SingleModeChara": [
            {
                "single_mode_chara_id": 745,
                "card_id": 103201,
                "chara_grade": 10,
                "speed": speed,
                "stamina": stamina,
                "power": power,
                "wiz": wiz,
                "guts": guts,
                "vital": 10,
                "max_speed": 1313,
                "max_stamina": 1361,
                "max_power": 1472,
                "max_wiz": 1800,
                "max_guts": 1300,
                "motivation": 5,
                "fans": fans,
                "rarity": 4,
                "talent_level": talent_level,
                "skill_array": [{"skill_id": 100321, "level": 5}] * skills_owned,
            }
        ],
        "SupportCardGainInfo": [
            {"<SupportCardId>k__BackingField": cid} for cid in deck_ids
        ],
        "SuccessionFactorGainInfo": [
            {
                "<Year>k__BackingField": year_idx + 1,
                "<GainFactorInfoArray>k__BackingField": [
                    {"<FactorId>k__BackingField": 100 + i, "<Level>k__BackingField": 0}
                    for i in range(count)
                ],
            }
            for year_idx, count in enumerate(factors_per_year)
        ],
        "GainInfo": [
            {
                "<Speed>k__BackingField": 0,
                "<Stamina>k__BackingField": 0,
                "<Power>k__BackingField": 0,
                "<Wiz>k__BackingField": 0,
                "<Guts>k__BackingField": 0,
                "<SkillPoint>k__BackingField": sp,
                "<SkillTipsArray>k__BackingField": [{"group_id": i, "rarity": 1,
                    "level": 1} for i in range(hints)],
            }
            for sp, hints in zip(gain_infos_sp, hints_per_gain, strict=True)
        ],
        "RaceHistory": [
            {"turn": i, "program_id": 1000 + i, "weather": 1, "ground_condition": 1,
             "running_style": 2, "result_rank": 1, "frame_order": 1, "npc_count": 0}
            for i in range(race_count)
        ],
        "IdleSingleModeRaceHistory": [],
    }
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_filename_regex_accepts_extractor_output():
    m = FILENAME_RE.search("20260725T185207_scen2_uma103201.json")
    assert m
    assert m["ts"] == "20260725T185207"
    assert m["scen"] == "2"
    assert m["uma"] == "103201"


def test_filename_regex_rejects_bad_names():
    for bad in ["run.json", "20260725_scen2_uma103201.json", "foo/bar.json"]:
        assert FILENAME_RE.search(bad) is None


def test_summarize_extracts_expected_fields(tmp_path: Path):
    p = _make_run_json(tmp_path)
    m = summarize(p)

    assert m.timestamp == "20260725T185207"
    assert m.scenario_id == 2
    assert m.trainee_card_id == 103201
    assert m.stat_sum == 870 + 519 + 790 + 631 + 404
    assert m.cap_sum == 1313 + 1361 + 1472 + 1800 + 1300
    assert m.fans == 959461
    assert m.factors_total == 13 * 3
    assert m.unspent_sp == 2897
    assert m.races_run == 40
    assert m.skills_owned == 1
    assert m.skill_hints_available == 23 + 3 * 7
    assert m.deck_card_ids == (20027, 20031, 30015, 30089, 30201, 30310)
    assert len(m.deck_hash) == 6      # blake2b(digest_size=3) → 6 hex chars


def test_deck_hash_is_order_independent(tmp_path: Path):
    a = _make_run_json(
        tmp_path,
        name="20260725T185207_scen2_uma103201.json",
        deck_ids=(20027, 20031, 30015, 30089, 30201, 30310),
    )
    b = _make_run_json(
        tmp_path,
        name="20260725T185208_scen2_uma103201.json",
        deck_ids=(30310, 30201, 30089, 30015, 20031, 20027),
    )
    assert summarize(a).deck_hash == summarize(b).deck_hash


def test_deck_hash_differs_for_different_decks(tmp_path: Path):
    a = _make_run_json(
        tmp_path,
        name="20260725T185207_scen2_uma103201.json",
        deck_ids=(20027, 20031, 30015, 30089, 30201, 30310),
    )
    b = _make_run_json(
        tmp_path,
        name="20260725T185208_scen2_uma103201.json",
        deck_ids=(20027, 20031, 30015, 30089, 30201, 99999),
    )
    assert summarize(a).deck_hash != summarize(b).deck_hash


def test_summarize_directory_ignores_non_matching_files(tmp_path: Path):
    _make_run_json(tmp_path, name="20260725T185207_scen2_uma103201.json")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "unrelated.json").write_text('{"foo":1}')
    results = summarize_directory(tmp_path)
    assert len(results) == 1


def test_summarize_bad_filename_raises(tmp_path: Path):
    p = tmp_path / "wrong.json"
    p.write_text("{}")
    with pytest.raises(ValueError):
        summarize(p)


REAL_RUN = (
    Path(__file__).parent.parent
    / "IT-references"
    / "20260725T185207_scen2_uma103201.json"
)


@pytest.mark.skipif(not REAL_RUN.exists(), reason="no real run available in checkout")
def test_summarize_real_production_run():
    m = summarize(REAL_RUN)
    assert m.trainee_card_id == 103201            # Agnes Tachyon
    assert m.scenario_id == 2
    assert m.races_run == 40                      # buffer capacity
    assert len(m.deck_card_ids) == 6              # full deck present
    assert m.stat_sum == 870 + 519 + 790 + 631 + 404
    assert m.fans == 959461
    assert m.run_state == "completed"


def test_run_state_completed_vs_pre_training(tmp_path: Path):
    ok = summarize(_make_run_json(tmp_path, name="20260725T185207_scen2_uma103201.json"))
    assert ok.run_state == "completed"

    early = summarize(_make_run_json(
        tmp_path,
        name="20260725T195544_scen3_uma103201.json",
        speed=114, stamina=158, power=137, wiz=110, guts=98, fans=1,
    ))
    assert early.run_state == "pre_training"

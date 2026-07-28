from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .lookups import deck_summary, scenario_name, uma_card_name


FILENAME_RE = re.compile(
    r"(?P<ts>\d{8}T\d{6})_scen(?P<scen>\d+)_uma(?P<uma>\d+)\.json$"
)


@dataclass(frozen=True)
class RunMetrics:
    filename: str
    timestamp: str            # 20260725T185207
    scenario_id: int
    trainee_card_id: int
    deck_hash: str            # 6-char hex
    deck_card_ids: tuple[int, ...]

    speed: int
    stamina: int
    power: int
    wiz: int
    guts: int
    stat_sum: int

    max_speed: int
    max_stamina: int
    max_power: int
    max_wiz: int
    max_guts: int
    cap_sum: int

    fans: int
    vital: int
    motivation: int
    talent_level: int

    unspent_sp: int
    skills_owned: int
    skill_hints_available: int
    factors_total: int
    races_run: int

    @property
    def run_state(self) -> str:
        """Rough heuristic for whether the capture was of a completed
        Training Log or a pre-training / mid-scenario state. Completed IT
        always produces at least tens of thousands of fans and a stat sum
        well over 1000; anything below that is almost certainly an
        early-scenario capture (or a Grand-Live-style scenario where the
        extractor picked the wrong SingleModeChara instance)."""
        if self.fans >= 100 and self.stat_sum >= 1000:
            return "completed"
        return "pre_training"

    def as_row(self) -> dict[str, object]:
        return {
            "run_state": self.run_state,
            "timestamp": self.timestamp,
            "scenario_id": self.scenario_id,
            "scenario_name": scenario_name(self.scenario_id),
            "trainee_card_id": self.trainee_card_id,
            "trainee_name": uma_card_name(self.trainee_card_id),
            "deck_hash": self.deck_hash,
            "deck_card_ids": list(self.deck_card_ids),
            "deck_summary": deck_summary(self.deck_card_ids),
            "speed": self.speed,
            "stamina": self.stamina,
            "power": self.power,
            "wiz": self.wiz,
            "guts": self.guts,
            "stat_sum": self.stat_sum,
            "cap_sum": self.cap_sum,
            "fans": self.fans,
            "vital": self.vital,
            "motivation": self.motivation,
            "talent_level": self.talent_level,
            "unspent_sp": self.unspent_sp,
            "skills_owned": self.skills_owned,
            "skill_hints_available": self.skill_hints_available,
            "factors_total": self.factors_total,
            "races_run": self.races_run,
            "filename": self.filename,
        }


def _deck_hash(card_ids: tuple[int, ...]) -> str:
    payload = ",".join(str(x) for x in sorted(card_ids)).encode()
    return hashlib.blake2b(payload, digest_size=3).hexdigest()


def _support_card_id(entry: dict) -> int:
    return int(entry["<SupportCardId>k__BackingField"])


def _gain_info_sp(entry: dict) -> int:
    return int(entry.get("<SkillPoint>k__BackingField", 0))


def summarize(path: Path) -> RunMetrics:
    m = FILENAME_RE.search(path.name)
    if not m:
        raise ValueError(
            f"filename {path.name!r} doesn't match "
            "<timestamp>_scen<N>_uma<N>.json"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))

    chara = raw["SingleModeChara"][0]
    speed = int(chara["speed"])
    stamina = int(chara["stamina"])
    power = int(chara["power"])
    wiz = int(chara["wiz"])
    guts = int(chara["guts"])

    deck_ids = tuple(_support_card_id(c) for c in raw.get("SupportCardGainInfo", []))

    factors_total = sum(
        len(year.get("<GainFactorInfoArray>k__BackingField", []))
        for year in raw.get("SuccessionFactorGainInfo", [])
    )

    gain_infos = raw.get("GainInfo", [])
    unspent_sp = sum(_gain_info_sp(g) for g in gain_infos)

    skill_hints_available = sum(
        len(g.get("<SkillTipsArray>k__BackingField", [])) for g in gain_infos
    )

    return RunMetrics(
        filename=path.name,
        timestamp=m["ts"],
        scenario_id=int(m["scen"]),
        trainee_card_id=int(m["uma"]),
        deck_hash=_deck_hash(deck_ids),
        deck_card_ids=deck_ids,
        speed=speed,
        stamina=stamina,
        power=power,
        wiz=wiz,
        guts=guts,
        stat_sum=speed + stamina + power + wiz + guts,
        max_speed=int(chara["max_speed"]),
        max_stamina=int(chara["max_stamina"]),
        max_power=int(chara["max_power"]),
        max_wiz=int(chara["max_wiz"]),
        max_guts=int(chara["max_guts"]),
        cap_sum=(
            int(chara["max_speed"])
            + int(chara["max_stamina"])
            + int(chara["max_power"])
            + int(chara["max_wiz"])
            + int(chara["max_guts"])
        ),
        fans=int(chara["fans"]),
        vital=int(chara["vital"]),
        motivation=int(chara["motivation"]),
        talent_level=int(chara["talent_level"]),
        unspent_sp=unspent_sp,
        skills_owned=len(chara.get("skill_array", [])),
        skill_hints_available=skill_hints_available,
        factors_total=factors_total,
        races_run=len(raw.get("RaceHistory", [])),
    )


def summarize_directory(runs_dir: Path) -> list[RunMetrics]:
    out: list[RunMetrics] = []
    for p in sorted(runs_dir.glob("*.json")):
        if not FILENAME_RE.search(p.name):
            continue
        try:
            out.append(summarize(p))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    return out

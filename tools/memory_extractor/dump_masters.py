"""Master-data dumper — reads the game's local SQLite master.mdb and
writes a clean masters.json with all the lookup tables the enrichment
layer needs to resolve numeric IDs (skills, umas, cards, races, factors,
scenarios) into human-readable names.

No Frida needed. Game does not need to be running (but if it is, we copy
the file first to avoid SQLite lock conflicts).

Standard Windows path:
    C:/Users/<name>/AppData/LocalLow/Cygames/Umamusume/master/master.mdb

Usage:
    python dump_masters.py                    # auto-find, write masters.json here
    python dump_masters.py --mdb <path>       # custom source
    python dump_masters.py --out masters.json # custom output

Design notes:
- Names live in `text_data`, joined by (category, index). Category IDs
  are stable per Global build 2026-07; if they shift, update TEXT_CAT.
- SQLite `_notFounds` cache and `_lazy*` dictionaries in the IL2CPP-side
  wrappers mean walking Frida gives you only cached rows. Reading master.mdb
  directly gets everything the game knows about, regardless of what a
  particular player has actually opened in-game.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MDB_PATHS = [
    # Windows (native)
    Path(os.path.expandvars(r"%LocalAppData%\..\LocalLow\Cygames\Umamusume\master\master.mdb")),
    # WSL access to Windows user profile — grab the current user's LocalLow
    *(
        [Path(f"/mnt/c/Users/{os.environ.get('USER', '')}/AppData/LocalLow/Cygames/Umamusume/master/master.mdb")]
        if os.environ.get("USER") else []
    ),
]


# text_data categories, verified against Global build 2026-07.
# Update if a game update shifts these.
TEXT_CAT = {
    "uma_name": 6,            # index = chara_id (e.g. 1032 -> "Agnes Tachyon")
    "skill_name": 47,         # index = skill_id (e.g. 200352 -> "Corner Recovery ○")
    "race_name": 33,          # index = race id  (e.g. 1001 -> "February Stakes")
    "factor_name": 147,       # index = factor_id — authoritative game display
                              # names (e.g. 2303 -> "Late Surger",
                              # 2102102 -> "Ignited Spirit: Speed +").
}

# Scenario id -> Global display name. Derived from release-date + champion
# title cross-reference (see the SQL exploration in the commit that added
# this file). single_mode_scenario contains 4 rows currently.
SCENARIO_NAMES = {
    1: "URA Finale",
    2: "Unity Cup",
    3: "Our Grand Concert",       # Grand Live
    4: "Trackblazer",             # MANT: Make A New Track
}


def _find_mdb() -> Path:
    for p in DEFAULT_MDB_PATHS:
        try:
            if p.exists():
                return p
        except (OSError, ValueError):
            continue
    raise FileNotFoundError(
        "Could not auto-find master.mdb. Pass --mdb <path> explicitly.\n"
        "Typical Windows path: "
        r"C:\Users\<you>\AppData\LocalLow\Cygames\Umamusume\master\master.mdb"
    )


def _copy_to_temp(src: Path) -> Path:
    """Copy the .mdb to a temp file. Game holds a SQLite connection while
    running; opening the live file works most of the time but reading a
    snapshot is safer and avoids the very unlikely lock-contention corner."""
    tmp = Path(tempfile.gettempdir()) / f"masters_snapshot_{os.getpid()}.mdb"
    shutil.copy2(src, tmp)
    return tmp


def _load_text_map(con: sqlite3.Connection, category: int) -> dict[int, str]:
    """Build {index -> text} for a text_data category."""
    return {
        idx: text
        for (idx, text) in con.execute(
            "SELECT `index`, text FROM text_data WHERE category = ?", (category,)
        )
    }


def dump(mdb_path: Path, out_path: Path) -> dict:
    snapshot = _copy_to_temp(mdb_path)
    try:
        con = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row

        # ── text maps (loaded once, joined by many things) ─────────────
        uma_names = _load_text_map(con, TEXT_CAT["uma_name"])
        skill_names = _load_text_map(con, TEXT_CAT["skill_name"])
        race_names = _load_text_map(con, TEXT_CAT["race_name"])
        factor_names = _load_text_map(con, TEXT_CAT["factor_name"])

        # ── umas (chara_data) ──────────────────────────────────────────
        umas: dict[str, dict] = {}
        for r in con.execute("SELECT id FROM chara_data"):
            cid = r["id"]
            umas[str(cid)] = {"id": cid, "name": uma_names.get(cid, f"?uma:{cid}")}

        # ── uma cards (card_data — one uma has multiple card variants) ─
        # available_skill_set_id maps into `available_skill_set` table
        # which lists the trainee's built-in skills — the ones that
        # appear in the skill panel from turn 1 without needing a hint
        # from support cards or events. Each row has a ``need_rank``
        # (0 = always available, N = unlocks when trainee reaches
        # career rank N).
        uma_cards: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, chara_id, default_rarity, running_style, "
            "available_skill_set_id, "
            "talent_speed, talent_stamina, talent_pow, talent_guts, talent_wiz "
            "FROM card_data"
        ):
            cid = r["id"]
            uma_cards[str(cid)] = {
                "id": cid,
                "chara_id": r["chara_id"],
                "chara_name": uma_names.get(r["chara_id"], f"?uma:{r['chara_id']}"),
                "default_rarity": r["default_rarity"],
                "running_style": r["running_style"],
                "available_skill_set_id": r["available_skill_set_id"],
                "talent_bonus": {
                    "speed": r["talent_speed"],
                    "stamina": r["talent_stamina"],
                    "power": r["talent_pow"],
                    "guts": r["talent_guts"],
                    "wiz": r["talent_wiz"],
                },
            }

        # ── innate skill sets ──────────────────────────────────────────
        # available_skill_set_id -> [(skill_id, need_rank), ...]. Each
        # trainee starts a run with these skills already accessible in
        # the buy-panel. Any hint proc'd during the run adds a level
        # discount to the SAME skills; without a hint they cost full
        # SP but they're still buyable from turn 1.
        innate_skills: dict[str, list[dict]] = {}
        for r in con.execute(
            "SELECT available_skill_set_id, skill_id, need_rank "
            "FROM available_skill_set ORDER BY available_skill_set_id, need_rank, skill_id"
        ):
            innate_skills.setdefault(str(r["available_skill_set_id"]), []).append({
                "skill_id": r["skill_id"],
                "need_rank": r["need_rank"],
            })

        # ── support cards ──────────────────────────────────────────────
        # command_type maps to the training focus (1=Speed, 2=Stamina, etc.)
        # Rather than hardcode a partial map, pass it through raw and let
        # the enrichment layer decorate.
        support_cards: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, chara_id, rarity, command_type, command_id, "
            "support_card_type, skill_set_id "
            "FROM support_card_data"
        ):
            cid = r["id"]
            support_cards[str(cid)] = {
                "id": cid,
                "chara_id": r["chara_id"],
                "chara_name": uma_names.get(r["chara_id"], f"?uma:{r['chara_id']}"),
                "rarity": r["rarity"],
                # command_id is the training-focus indicator (101=Power,
                # 102=Speed, 103=Stamina, 105=Guts, 106=Wit, 0=Friend).
                # See lookups.SUPPORT_TYPE_BY_CMD for the mapping.
                "command_id": r["command_id"],
                "command_type": r["command_type"],
                "support_card_type": r["support_card_type"],
                "skill_set_id": r["skill_set_id"],
            }

        # ── skills ─────────────────────────────────────────────────────
        # Do NOT filter by disable_singlemode — unique skills (e.g. Agnes
        # Tachyon's "Triumphant Pulse", id 100321) have disable_singlemode=1
        # but appear in IT runs regardless. That flag means "cannot be
        # acquired by random skill hint" — not "cannot appear in IT".
        #
        # Skill SP cost lives in single_mode_skill_need_point (only 569
        # entries — many skills are inheritance-only and can't be bought).
        # We LEFT JOIN so all skills come through even without a cost row.
        skills: dict[str, dict] = {}
        for r in con.execute(
            """
            SELECT s.id, s.rarity, s.group_id, s.group_rate, s.skill_category,
                   s.grade_value, s.disable_singlemode, s.condition_1, s.condition_2,
                   s.icon_id,
                   n.need_skill_point
            FROM skill_data s
            LEFT JOIN single_mode_skill_need_point n ON n.id = s.id
            """
        ):
            sid = r["id"]
            skills[str(sid)] = {
                "id": sid,
                "name": skill_names.get(sid, f"?skill:{sid}"),
                "rarity": r["rarity"],
                "group_id": r["group_id"],
                "group_rate": r["group_rate"],
                "category": r["skill_category"],
                "grade_value": r["grade_value"],
                "sp_cost": r["need_skill_point"],  # None if not purchasable in IT
                "singlemode_only_unique": bool(r["disable_singlemode"]),
                # Game asset id for the skill's icon (green passive, orange
                # active, blue/purple unique, purple debuff heart). Rendered
                # via https://gametora.com/images/umamusume/skill_icons/utx_ico_skill_<icon_id>.png
                "icon_id": r["icon_id"],
                # Activation predicates — used by the classifier to
                # separate trainee-affinity skills (running_style==N,
                # distance_type==N) from opponent/universal ones.
                "condition_1": r["condition_1"] or "",
                "condition_2": r["condition_2"] or "",
            }

        # ── races ──────────────────────────────────────────────────────
        # `race` table has 1524 rows (all instances/reruns).
        # For enrichment, we just need id -> name.
        races: dict[str, dict] = {}
        for r in con.execute("SELECT id, grade, entry_num FROM race"):
            rid = r["id"]
            races[str(rid)] = {
                "id": rid,
                "name": race_names.get(rid, f"?race:{rid}"),
                "grade": r["grade"],
                "entry_num": r["entry_num"],
            }

        # ── single-mode program IDs (what shows up in RaceHistory.program_id) ─
        # program.race_instance_id → race_instance.race_id → race.id →
        # text_data(category=33). Precomputed here so the enrichment layer
        # gets a program_id → name lookup in one hop.
        programs: dict[str, dict] = {}
        for r in con.execute(
            """
            SELECT p.id AS program_id, p.race_instance_id, ri.race_id,
                   r.grade, r.entry_num,
                   p.month, p.half
            FROM single_mode_program p
            JOIN race_instance ri ON ri.id = p.race_instance_id
            JOIN race r ON r.id = ri.race_id
            """
        ):
            pid = r["program_id"]
            programs[str(pid)] = {
                "id": pid,
                "race_id": r["race_id"],
                "name": race_names.get(r["race_id"], f"?race:{r['race_id']}"),
                "grade": r["grade"],
                "entry_num": r["entry_num"],
                "month": r["month"],
                "half": r["half"],
            }

        # ── factors (succession_factor) ────────────────────────────────
        # factor_type: 1=stat, 2=aptitude, 3=unique-chara-inherit, 4=skill,
        #              5=chara-green, 6=race-green, 7=very-rare.
        # For type 5/6/7 (greens) we join succession_factor_effect to
        # find what the green actually grants: either a skill hint
        # (target_type=41 → value_1 = skill_id) or stat bonuses
        # (target_type in 1..5 → Speed/Stamina/Power/Guts/Wit).
        stat_names_by_target = {1: "Speed", 2: "Stamina", 3: "Power",
                                4: "Guts", 5: "Wit"}
        green_grants: dict[int, dict] = {}
        for r in con.execute(
            "SELECT DISTINCT factor_group_id, target_type, value_1 "
            "FROM succession_factor_effect"
        ):
            gid = r["factor_group_id"]
            g = green_grants.setdefault(gid, {"skill_ids": set(), "stats": set()})
            if r["target_type"] == 41:
                g["skill_ids"].add(int(r["value_1"]))
            elif r["target_type"] in stat_names_by_target:
                g["stats"].add(stat_names_by_target[r["target_type"]])

        factors: dict[str, dict] = {}
        for r in con.execute(
            "SELECT factor_id, factor_group_id, rarity, grade, factor_type, effect_group_id "
            "FROM succession_factor"
        ):
            fid = r["factor_id"]
            gid = r["factor_group_id"]
            grant = green_grants.get(gid, {})
            granted_skill_ids = sorted(grant.get("skill_ids") or [])
            granted_skill_names = [
                skill_names.get(sid, f"?skill:{sid}") for sid in granted_skill_ids
            ]
            factors[str(fid)] = {
                "id": fid,
                "group_id": gid,
                "rarity": r["rarity"],
                "grade": r["grade"],
                "factor_type": r["factor_type"],
                "effect_group_id": r["effect_group_id"],
                # Authoritative game display name — replaces the earlier
                # composed-name logic which had aptitude
                # distance/style mixed up and couldn't attach the +stat
                # suffix to skill-inheritance factors like
                # 'Ignited Spirit: Speed +'.
                "display_name": factor_names.get(fid, ""),
                "granted_skill_ids": granted_skill_ids,
                "granted_skill_names": granted_skill_names,
                "granted_stats": sorted(grant.get("stats") or []),
            }

        # ── scenarios ──────────────────────────────────────────────────
        scenarios: dict[str, dict] = {}
        for r in con.execute("SELECT id, sort_id, start_date FROM single_mode_scenario"):
            sid = r["id"]
            scenarios[str(sid)] = {
                "id": sid,
                "name": SCENARIO_NAMES.get(sid, f"?scenario:{sid}"),
                "sort_id": r["sort_id"],
                "released_at": datetime.fromtimestamp(r["start_date"], tz=timezone.utc).date().isoformat(),
            }

        # ── parent-compatibility tables ────────────────────────────────
        # Base pair compat = sum of `succession_relation.relation_point` over
        # the intersection of `succession_relation_member.relation_type` sets
        # between two chara_ids. Verified against Special Week reference
        # numbers (Narita Brian=37, Nice Nature=37, T.M. Opera O=35, etc.).
        #
        # Overall compat (◎/○/△) uses `succession_relation_rank` thresholds
        # against the summed score across all lineage pairs + G1-race overlap
        # bonuses. See enrich.compat for the pairing formula.
        relation_points: dict[str, int] = {
            str(rt): int(pts)
            for (rt, pts) in con.execute(
                "SELECT relation_type, relation_point FROM succession_relation")
        }
        chara_relations: dict[str, list[int]] = {}
        for (rt, cid) in con.execute(
            "SELECT relation_type, chara_id FROM succession_relation_member"):
            chara_relations.setdefault(str(cid), []).append(int(rt))
        compat_thresholds: list[dict] = [
            {"rank": r["relation_rank"],
             "min": r["rank_value_min"],
             "max": r["rank_value_max"]}
            for r in con.execute(
                "SELECT relation_rank, rank_value_min, rank_value_max "
                "FROM succession_relation_rank ORDER BY relation_rank")
        ]

        # ── win-saddle → race-instance expansion ───────────────────────
        # Grandparents (SuccessionCharaData) don't carry per-run race history;
        # only `_winSaddleIdArray`. Each saddle stands for up to 8
        # race_instance_ids (Triple-Crown-style titles). We flatten each
        # saddle to its set of race_ids so compat.py can intersect a
        # grandparent's saddles with a trainee's races for the G1 overlap
        # bonus. Direct parents use their full <SingleModeRaceResultArray>.
        win_saddles: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, priority, group_id, win_saddle_type, "
            "race_instance_id_1, race_instance_id_2, race_instance_id_3, "
            "race_instance_id_4, race_instance_id_5, race_instance_id_6, "
            "race_instance_id_7, race_instance_id_8 "
            "FROM single_mode_wins_saddle"):
            rids = [r[f"race_instance_id_{i}"] for i in range(1, 9)]
            rids = [x for x in rids if x]
            win_saddles[str(r["id"])] = {
                "id": r["id"],
                "priority": r["priority"],
                "group_id": r["group_id"],
                "win_saddle_type": r["win_saddle_type"],
                "race_instance_ids": rids,
            }
        # race_instance_id → race_id (needed to go saddle → grade).
        race_instances: dict[str, int] = {
            str(r["id"]): r["race_id"]
            for r in con.execute("SELECT id, race_id FROM race_instance")
        }

        # ── rank thresholds (single_mode_rank) ─────────────────────────
        # Given a computed SS-grade score, look up the rank tier.
        # 98 rows, id=1 lowest, higher id = better rank. Letter-grade
        # mapping (SS/S+/etc) is rendered as UI assets, not text_data —
        # kept as numeric ranks here.
        rank_tiers: list[dict] = []
        for r in con.execute("SELECT id, min_value, max_value FROM single_mode_rank ORDER BY id"):
            rank_tiers.append({
                "rank": r["id"],
                "min": r["min_value"],
                "max": r["max_value"],
            })

        con.close()

        # ── assemble output ────────────────────────────────────────────
        st = mdb_path.stat()
        result = {
            "_meta": {
                "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "source_mdb": str(mdb_path),
                "source_size_bytes": st.st_size,
                "source_mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                "text_categories": TEXT_CAT,
                "counts": {
                    "umas": len(umas),
                    "uma_cards": len(uma_cards),
                    "support_cards": len(support_cards),
                    "skills": len(skills),
                    "races": len(races),
                    "programs": len(programs),
                    "factors": len(factors),
                    "scenarios": len(scenarios),
                    "relation_points": len(relation_points),
                    "chara_relations": len(chara_relations),
                    "win_saddles": len(win_saddles),
                    "race_instances": len(race_instances),
                    "innate_skill_sets": len(innate_skills),
                },
            },
            "scenarios": scenarios,
            "rank_tiers": rank_tiers,
            "umas": umas,
            "uma_cards": uma_cards,
            "support_cards": support_cards,
            "skills": skills,
            "races": races,
            "programs": programs,
            "factors": factors,
            "relation_points": relation_points,
            "chara_relations": chara_relations,
            "compat_thresholds": compat_thresholds,
            "win_saddles": win_saddles,
            "race_instances": race_instances,
            "innate_skills": innate_skills,
        }
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result
    finally:
        try: snapshot.unlink()
        except OSError: pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mdb", type=Path, default=None,
                    help="Path to master.mdb (auto-detected if omitted)")
    ap.add_argument("--out", type=Path, default=Path("masters.json"),
                    help="Output JSON path (default: ./masters.json)")
    args = ap.parse_args(argv)

    try:
        mdb = args.mdb or _find_mdb()
    except FileNotFoundError as e:
        print(f"[X] {e}", file=sys.stderr)
        return 2
    if not mdb.exists():
        print(f"[X] master.mdb not found at {mdb}", file=sys.stderr)
        return 2

    print(f"[+] Source: {mdb}  ({mdb.stat().st_size // 1024} KB)")
    result = dump(mdb, args.out)
    counts = result["_meta"]["counts"]
    print(f"[OK] wrote {args.out}")
    for k, v in counts.items():
        print(f"       {v:>6}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

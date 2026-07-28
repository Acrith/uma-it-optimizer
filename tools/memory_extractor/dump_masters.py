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

        # ── umas (chara_data) ──────────────────────────────────────────
        umas: dict[str, dict] = {}
        for r in con.execute("SELECT id FROM chara_data"):
            cid = r["id"]
            umas[str(cid)] = {"id": cid, "name": uma_names.get(cid, f"?uma:{cid}")}

        # ── uma cards (card_data — one uma has multiple card variants) ─
        uma_cards: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, chara_id, default_rarity, running_style, "
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
                "talent_bonus": {
                    "speed": r["talent_speed"],
                    "stamina": r["talent_stamina"],
                    "power": r["talent_pow"],
                    "guts": r["talent_guts"],
                    "wiz": r["talent_wiz"],
                },
            }

        # ── support cards ──────────────────────────────────────────────
        # command_type maps to the training focus (1=Speed, 2=Stamina, etc.)
        # Rather than hardcode a partial map, pass it through raw and let
        # the enrichment layer decorate.
        support_cards: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, chara_id, rarity, command_type, support_card_type, skill_set_id "
            "FROM support_card_data"
        ):
            cid = r["id"]
            support_cards[str(cid)] = {
                "id": cid,
                "chara_id": r["chara_id"],
                "chara_name": uma_names.get(r["chara_id"], f"?uma:{r['chara_id']}"),
                "rarity": r["rarity"],
                "command_type": r["command_type"],
                "support_card_type": r["support_card_type"],
                "skill_set_id": r["skill_set_id"],
            }

        # ── skills ─────────────────────────────────────────────────────
        # Do NOT filter by disable_singlemode — unique skills (e.g. Agnes
        # Tachyon's "Triumphant Pulse", id 100321) have disable_singlemode=1
        # but appear in IT runs regardless. That flag means "cannot be
        # acquired by random skill hint" — not "cannot appear in IT".
        skills: dict[str, dict] = {}
        for r in con.execute(
            "SELECT id, rarity, group_id, group_rate, skill_category, "
            "grade_value, disable_singlemode "
            "FROM skill_data"
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
                "singlemode_only_unique": bool(r["disable_singlemode"]),
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
        # factor_type: 1=stat, 2=aptitude, 3=skill, 4=unique (approx.)
        # Factor names aren't in a simple text_data category — they're
        # composed (e.g. "Speed ★★" is factor_type=1 + effect_group=speed
        # + grade=2). Pass raw fields through for the enrichment layer.
        factors: dict[str, dict] = {}
        for r in con.execute(
            "SELECT factor_id, factor_group_id, rarity, grade, factor_type, effect_group_id "
            "FROM succession_factor"
        ):
            fid = r["factor_id"]
            factors[str(fid)] = {
                "id": fid,
                "group_id": r["factor_group_id"],
                "rarity": r["rarity"],
                "grade": r["grade"],
                "factor_type": r["factor_type"],
                "effect_group_id": r["effect_group_id"],
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
                },
            },
            "scenarios": scenarios,
            "umas": umas,
            "uma_cards": uma_cards,
            "support_cards": support_cards,
            "skills": skills,
            "races": races,
            "programs": programs,
            "factors": factors,
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

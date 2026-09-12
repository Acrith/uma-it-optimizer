"""Additively patch uma-it-web's masters.json trainee cards and skills
from the GLOBAL client's master.mdb (EN text) plus the JP reference mdb
(structural superset). Trainees released after the last full masters
snapshot render as '?uma:<id>' everywhere the site names a run, and
their unique skills go unscored (the unique bonus reads masters).

Release filter, same principle as the support-card patch: a card counts
as released if the global client knows it (card_data row) or the corpus
has actually run it. That keeps JP-ahead trainees out of the pickers
while guaranteeing no uploaded run stays nameless.

Text categories in the global mdb: 5 = card title ('[Golden Dream]'),
6 = character name, both in EN. The JP mdb carries EN character names
in category 372 as a fallback.

Usage:
    python patch_masters_umas.py --global-mdb <global master.mdb> \
        [--runs <runs dir>]           # union in every trainee seen
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
MASTERS = HERE / "../../../uma-it-web/uma_it_web/enrich/data/masters.json"
JP_MDB = HERE / "../../references/master.mdb"

STAT_BY_TARGET = {1: "Speed", 2: "Stamina", 3: "Power", 4: "Guts",
                  5: "Wit"}
CARD_COLS = ("chara_id, default_rarity, running_style, "
             "available_skill_set_id, talent_speed, talent_stamina, "
             "talent_pow, talent_guts, talent_wiz")


def _text(conn: sqlite3.Connection, category: int) -> dict[int, str]:
    return {r[0]: r[1] for r in conn.execute(
        "select `index`, text from text_data where category=?", (category,))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-mdb", type=Path, required=True)
    ap.add_argument("--runs", type=Path)
    ap.add_argument("--seen-file", type=Path,
                    help="ids seen in the corpus, one per line (a leading "
                         "count column is ignored) - lets a cheap prod "
                         "filename scan stand in for the whole runs dir")
    args = ap.parse_args()

    m = json.loads(MASTERS.read_text(encoding="utf-8"))
    umas = m.setdefault("uma_cards", {})
    innate = m.setdefault("innate_skills", {})

    g = sqlite3.connect(str(args.global_mdb))
    jp = sqlite3.connect(str(JP_MDB))

    released = {r[0] for r in g.execute("select id from card_data")}
    if args.runs:
        for p in args.runs.glob("*/*.json"):
            parts = p.stem.split("_")
            if len(parts) > 2 and parts[2].startswith("uma") \
                    and parts[2][3:].isdigit():
                released.add(int(parts[2][3:]))
    if args.seen_file:
        for line in args.seen_file.read_text(encoding="utf-8").split("\n"):
            tok = line.split()
            if tok and tok[-1].isdigit():
                released.add(int(tok[-1]))

    titles = _text(g, 5)
    names = _text(g, 6)
    jp_names = _text(jp, 372)

    added, no_text = [], []
    for cid in sorted(released):
        if str(cid) in umas:
            continue
        row = (g.execute(f"select {CARD_COLS} from card_data where id=?",
                         (cid,)).fetchone()
               or jp.execute(f"select {CARD_COLS} from card_data where id=?",
                             (cid,)).fetchone())
        if row is None:
            no_text.append(cid)
            continue
        chara = row[0]
        name = names.get(chara) or jp_names.get(chara)
        if not name:
            no_text.append(cid)
            continue
        umas[str(cid)] = {
            "id": cid, "chara_id": chara, "chara_name": name,
            "card_title": titles.get(cid, ""),
            "default_rarity": row[1], "running_style": row[2],
            "available_skill_set_id": row[3],
            "talent_bonus": {"speed": row[4], "stamina": row[5],
                             "power": row[6], "guts": row[7], "wiz": row[8]},
        }
        # innate (always-available) skills for the new card's set
        ssid = row[3]
        if ssid and str(ssid) not in innate:
            rows = list(g.execute(
                "select skill_id, need_rank from available_skill_set "
                "where available_skill_set_id=? order by need_rank", (ssid,))) \
                or list(jp.execute(
                    "select skill_id, need_rank from available_skill_set "
                    "where available_skill_set_id=? order by need_rank",
                    (ssid,)))
            if rows:
                innate[str(ssid)] = [{"skill_id": s, "need_rank": n}
                                     for s, n in rows]
        added.append((cid, f"{name} {titles.get(cid, '')}".strip()))

    # ── skills ── a new trainee's unique is missing too, and the floor
    # score reads grade_value from masters, so an unknown unique
    # silently scores ZERO (Inari One [Golden Dream] shipped with
    # 'Firelight' unresolvable, 2026-09-12).
    #
    # The global client's skill_data lags its own text bundle, exactly
    # like card_data does, so take structural rows from whichever mdb
    # has them - global first, JP as the superset - and gate a JP-only
    # row on the global bundle knowing an EN name for it. Unlike the
    # trainee pickers, `skills` is a pure lookup: an entry nothing
    # references costs nothing, while a missing one costs a wrong score.
    skills = m.setdefault("skills", {})
    s_names, s_descs = _text(g, 47), _text(g, 48)

    def _is_en(text: str | None) -> bool:
        return bool(text) and all(ord(c) < 0x3000 for c in text)

    SKILL_COLS = ("s.id, s.rarity, s.group_id, s.group_rate, "
                  "s.skill_category, s.grade_value, s.disable_singlemode, "
                  "s.condition_1, s.condition_2, s.icon_id, s.disp_order, "
                  "n.need_skill_point from skill_data s left join "
                  "single_mode_skill_need_point n on n.id = s.id")
    rows_by_id = {}
    for conn in (jp, g):                      # global wins on overlap
        for row in conn.execute(f"select {SKILL_COLS}"):
            rows_by_id[row[0]] = (row, conn is g)

    s_added = []
    for sid, (row, from_global) in sorted(rows_by_id.items()):
        if str(sid) in skills:
            continue
        if not from_global and not _is_en(s_names.get(sid)):
            continue                          # JP-only and unnamed here
        skills[str(sid)] = {
            "id": sid, "name": s_names.get(sid, f"?skill:{sid}"),
            "description": s_descs.get(sid, ""), "rarity": row[1],
            "group_id": row[2], "group_rate": row[3], "category": row[4],
            "grade_value": row[5], "sp_cost": row[11],
            "singlemode_only_unique": bool(row[6]), "icon_id": row[9],
            "condition_1": row[7] or "", "condition_2": row[8] or "",
            "disp_order": row[10],
        }
        s_added.append((sid, s_names.get(sid, "?")))

    # ── factors ── a new chara's own inheritance sparks (Firelight,
    # I'm Possible!) arrive with the chara, so a stale snapshot leaves
    # the lineage and inspiration panels showing unnamed rows.
    factors = m.setdefault("factors", {})
    f_names, sk_names = _text(g, 147), s_names
    grants: dict = {}
    for conn in (jp, g):
        for gid, target, value in conn.execute(
                "select distinct factor_group_id, target_type, value_1 "
                "from succession_factor_effect"):
            e = grants.setdefault(gid, {"skills": set(), "stats": set()})
            if target == 41:
                e["skills"].add(int(value))
            elif target in STAT_BY_TARGET:
                e["stats"].add(STAT_BY_TARGET[target])
    f_rows = {}
    for conn in (jp, g):
        for row in conn.execute(
                "select factor_id, factor_group_id, rarity, grade, "
                "factor_type, effect_group_id from succession_factor"):
            f_rows[row[0]] = (row, conn is g)
    f_added = []
    for fid, (row, from_global) in sorted(f_rows.items()):
        if str(fid) in factors:
            continue
        if not from_global and not _is_en(f_names.get(fid)):
            continue
        grant = grants.get(row[1]) or {"skills": set(), "stats": set()}
        sids = sorted(grant["skills"])
        factors[str(fid)] = {
            "id": fid, "group_id": row[1], "rarity": row[2],
            "grade": row[3], "factor_type": row[4],
            "effect_group_id": row[5],
            "display_name": f_names.get(fid, f"?factor:{fid}"),
            "granted_skill_ids": sids,
            "granted_skill_names": [sk_names.get(x, f"?skill:{x}")
                                    for x in sids],
            "granted_stats": sorted(grant["stats"]),
        }
        f_added.append((fid, f_names.get(fid, "?")))

    # ── programs ── career race slots; a new one (a Make Debut variant)
    # leaves the race calendar unable to name that turn.
    programs = m.setdefault("programs", {})
    r_names = _text(g, 33)
    p_rows = {}
    for conn in (jp, g):
        for row in conn.execute(
                "select p.id, ri.race_id, r.grade, r.entry_num, p.month, "
                "p.half from single_mode_program p join race_instance ri "
                "on ri.id = p.race_instance_id join race r on r.id = "
                "ri.race_id"):
            p_rows[row[0]] = (row, conn is g)
    p_added = []
    for pid, (row, from_global) in sorted(p_rows.items()):
        if str(pid) in programs:
            continue
        if not from_global and not _is_en(r_names.get(row[1])):
            continue
        programs[str(pid)] = {
            "id": pid, "race_id": row[1],
            "name": r_names.get(row[1], f"?race:{row[1]}"),
            "grade": row[2], "entry_num": row[3],
            "month": row[4], "half": row[5],
        }
        p_added.append((pid, r_names.get(row[1], "?")))

    MASTERS.write_text(json.dumps(m, ensure_ascii=False,
                                  separators=(",", ":")), encoding="utf-8")
    for cid, label in added:
        print(f"  + {cid}  {label}")
    if no_text:
        print(f"  (skipped, no master row/name: {no_text})")
    for sid, label in s_added:
        print(f"  + skill {sid}  {label}")
    for fid, label in f_added:
        print(f"  + factor {fid}  {label}")
    for pid, label in p_added:
        print(f"  + program {pid}  {label}")
    print(f"added {len(added)} trainee cards (total {len(umas)}), "
          f"{len(s_added)} skills (total {len(skills)}), "
          f"{len(f_added)} factors (total {len(factors)}), "
          f"{len(p_added)} programs (total {len(programs)}), "
          f"innate sets {len(innate)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

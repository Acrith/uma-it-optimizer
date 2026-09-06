"""Additively patch uma-it-web's masters.json support_cards from the
gametora reference dump (EN names) + master.mdb (authoritative ids /
rarity / command / type). New global card releases land in decks weeks
before anyone refreshes the full masters snapshot; missing entries
render as '?sup:<id>' all over the site.

Usage: python patch_masters_cards.py            # patches in place
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
MASTERS = HERE / "../../../uma-it-web/uma_it_web/enrich/data/masters.json"
GT = (HERE / "../../references/support_cards_gametora_data"
      / "gametora_support_cards_all_lb_2026-08-07.json")
MDB = HERE / "../../references/master.mdb"


def main() -> int:
    m = json.loads(MASTERS.read_text(encoding="utf-8"))
    sc = m.setdefault("support_cards", {})
    en = {}
    for row in json.loads(GT.read_text(encoding="utf-8")):
        en[int(row["Support_ID"])] = row.get("Character_EN") or ""
    conn = sqlite3.connect(str(MDB))
    added = 0
    for cid, chara, rar, cmd, ctype, cskill in conn.execute(
            "select id, chara_id, rarity, command_id, support_card_type, "
            "skill_set_id from support_card_data"):
        if str(cid) in sc or cid not in en or not en[cid]:
            continue
        sc[str(cid)] = {"id": cid, "chara_id": chara, "chara_name": en[cid],
                        "rarity": rar, "command_id": cmd,
                        "command_type": 0, "support_card_type": ctype,
                        "skill_set_id": cskill}
        added += 1
    MASTERS.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    print(f"added {added} cards; total {len(sc)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

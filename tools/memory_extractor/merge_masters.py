"""Merge a fresh master dump (dump_masters.py) into the site's masters.json.

The site's masters.json is not a plain dump: tables were added since
(campaigns, items, card hint skills) and entries patched in (support cards
and skills from other sources, ahead of Global). Replacing it with a fresh
dump would drop those, so a refresh merges:

- a table both have, keyed by id: the game's entries win field by field,
  new ids are added, and ids only the site has are kept;
- a list both have (rank tiers, compat thresholds): the game's;
- a table only the site has: kept as it is.

    python merge_masters.py --fresh <dump.json> --site <masters.json> [--write]

Without --write it only reports what would change.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def merge(site: dict, fresh: dict) -> tuple[dict, dict[str, dict[str, int]]]:
    """The merged masters, and per table what changed (added, updated, kept)."""
    out = dict(site)
    report: dict[str, dict[str, int]] = {}
    for table, new in fresh.items():
        if table == "_meta":
            continue
        old = site.get(table)
        if isinstance(old, dict) and isinstance(new, dict):
            merged = dict(old)
            added = updated = 0
            for key, value in new.items():
                if key not in old:
                    merged[key] = value
                    added += 1
                elif isinstance(old[key], dict) and isinstance(value, dict):
                    both = {**old[key], **value}
                    if both != old[key]:
                        merged[key] = both
                        updated += 1
                elif old[key] != value:
                    merged[key] = value
                    updated += 1
            out[table] = merged
            report[table] = {"added": added, "updated": updated, "kept": len(set(old) - set(new))}
        else:
            if old != new:
                report[table] = {"replaced": 1}
            out[table] = new
    meta = dict(site.get("_meta") or {})
    meta.update({
        "merged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "merged_mdb_mtime": (fresh.get("_meta") or {}).get("source_mtime"),
    })
    out["_meta"] = meta
    return out, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fresh", type=Path, required=True, help="a dump_masters.py output")
    ap.add_argument("--site", type=Path, required=True, help="the site's masters.json")
    ap.add_argument("--write", action="store_true", help="write the merged file over --site")
    args = ap.parse_args()
    site = json.loads(args.site.read_text(encoding="utf-8"))
    fresh = json.loads(args.fresh.read_text(encoding="utf-8"))
    merged, report = merge(site, fresh)
    changed = {t: r for t, r in report.items()
               if r.get("added") or r.get("updated") or r.get("replaced")}
    for t, r in sorted(changed.items()):
        print(f"  {t:18} " + ", ".join(f"{k} {v}" for k, v in r.items()))
    if not changed:
        print("  nothing changed")
    if args.write:
        # As the site keeps it (and patch_masters_umas.py writes it): compact, one line.
        text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        args.site.write_text(text, encoding="utf-8")
        print(f"  written: {args.site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

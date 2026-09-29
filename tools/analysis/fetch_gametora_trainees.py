"""Snapshot GameTora's trainee pages: each trainee card's event skills and
events, with the conditions of its secret events (races to win, rivals to
beat) and their rewards. Read-only upstream data for export_trainee_events.py,
kept in references/gametora_trainees_<date>/<card id>.json (the page's
`props.pageProps`), like the support-card snapshot.

    python fetch_gametora_trainees.py [--date YYYY-MM-DD]

The page address is `<card id>-<character slug>`; the slug is taken from the
support-card snapshot's addresses (same character, same slug), else made from
the English name. One page a second; pages already fetched are kept.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
REFS = HERE / "../../references"
CARDS = REFS / "gametora_events_2026-09-05"
WEB = HERE / "../../../uma-it-web/uma_it_web/enrich/data"
PAGE = "https://gametora.com/umamusume/characters/{}"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def slugify(name: str) -> str:
    """GameTora drops dots: "T.M. Opera O" -> "tm-opera-o"."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower().replace(".", ""))).strip("-")


def addresses() -> dict[int, str]:
    slug: dict[str, str] = {}
    for f in glob.glob(str(CARDS / "*.json")):
        if not Path(f).stem.isdigit():
            continue
        item = json.loads(Path(f).read_text(encoding="utf-8"))["pageProps"]["itemData"]
        slug.setdefault(item["char_name"], item["url_name"].split("-", 1)[1])
    masters = json.loads((WEB / "masters.json").read_text(encoding="utf-8"))["uma_cards"]
    catalog = json.loads((WEB / "collection_catalog.json").read_text(encoding="utf-8"))["trainees"]
    out = {}
    for cid in sorted(int(k) for k in catalog):
        name = masters[str(cid)]["chara_name"]
        out[cid] = f"{cid}-{slug.get(name) or slugify(name)}"
    return out


def fetch(address: str) -> dict:
    req = urllib.request.Request(PAGE.format(address), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = NEXT_DATA.search(html)
    if not m:
        raise ValueError("no page data")
    return json.loads(m.group(1))["props"]["pageProps"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()
    out = REFS / f"gametora_trainees_{args.date}"
    out.mkdir(parents=True, exist_ok=True)
    missed = []
    for cid, address in addresses().items():
        path = out / f"{cid}.json"
        if path.exists():
            continue
        try:
            path.write_text(json.dumps(fetch(address), ensure_ascii=False), encoding="utf-8")
        except (urllib.error.URLError, ValueError) as e:
            missed.append(f"{address}: {e}")
        time.sleep(1)
    got = len(list(out.glob("*.json")))
    print(f"{got} trainee pages in {out.resolve()}")
    for m in missed:
        print(f"  missed {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

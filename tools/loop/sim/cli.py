"""The simulation's inputs, shared by its scripts: the game's master data,
the player's box and rental, and two companion data files (defaults: a
checkout of umaladder-companion beside this repo)."""
from __future__ import annotations

import argparse
from pathlib import Path

import world

COMPANION_DATA = Path(__file__).resolve().parents[3].parent / "umaladder-companion" / "data"


def inputs(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--master", required=True, help="the game's master.mdb")
    ap.add_argument("--account", required=True, help="the companion's account.json (Settings > Your data > Open data folder)")
    ap.add_argument("--rental", required=True, help="the borrowed parent: rental_one.py's file")
    ap.add_argument("--names", default=str(COMPANION_DATA / "names.json"))
    ap.add_argument("--loop-data", default=str(COMPANION_DATA / "loop_data.json"), help="the trainees' own skills")
    ap.add_argument("--scenario", type=int, default=1, help="looping in: 1 URA Finale, 2 Unity Cup, 3 Grand Concert")


def init(args: argparse.Namespace) -> None:
    world.init(args.master, args.names, args.account, args.rental, args.loop_data)

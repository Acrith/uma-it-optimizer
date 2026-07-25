from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dashboard import build_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uma_it_optimizer.enrich",
        description="Build an HTML dashboard summarizing all IT runs in a directory.",
    )
    parser.add_argument(
        "runs_dir",
        type=Path,
        nargs="?",
        default=Path("runs"),
        help="Directory containing the extractor's *.json output (default: ./runs)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output HTML path (default: <runs_dir>/dashboard.html)",
    )
    args = parser.parse_args(argv)

    if not args.runs_dir.is_dir():
        print(f"error: {args.runs_dir} is not a directory", file=sys.stderr)
        return 2

    out = args.output or (args.runs_dir / "dashboard.html")
    build_dashboard(args.runs_dir, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

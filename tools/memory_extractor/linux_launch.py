"""Linux launcher for the Windows uma-it-extract.exe.

Native-Linux frida can't attach to a wine-hosted Windows process
without its bootstrapper crashing (Frida's Linux injector doesn't
handle the mixed PE + ELF address space wine creates). Workaround:
run the Windows .exe extractor UNDER wine, pointing wine at the same
Proton prefix the game is running in. Frida-inside-wine attaches to
another wine-hosted process natively.

This script does the plumbing:
  - Finds uma-it-extract.exe (next to this script, or via --exe)
  - Finds the game's Proton prefix (Steam AppID 3224770 by default)
  - Prefers Proton's own wine64 over system wine (versions match the
    prefix; system wine can trip on newer prefix versions)
  - execs `wine64 uma-it-extract.exe` with WINEPREFIX set

Run this WHILE the game is open in Steam/Proton.

Usage:
    python linux_launch.py                       # defaults
    python linux_launch.py --exe /path/to/exe    # custom .exe location
    python linux_launch.py --appid 3224770       # override Steam AppID
    python linux_launch.py --prefix /path/to/pfx # skip appid → prefix
    python linux_launch.py --wine /path/to/wine  # force a specific wine
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_APPID = "3224770"   # Umamusume Pretty Derby on Steam Global
DEFAULT_EXE_NAME = "uma-it-extract.exe"

# Steam install roots to search for compatdata + compatibilitytools.d.
# Covers native Steam, Flatpak Steam, and the older ~/.steam symlink.
STEAM_ROOTS = [
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam"
        / ".local" / "share" / "Steam",
]


def find_extractor(explicit: str | None) -> Path:
    """Locate uma-it-extract.exe. --exe wins; else look next to this
    script; else look in cwd."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            _die(f"--exe path does not exist: {p}")
        return p
    here = Path(__file__).parent
    for candidate in (here / DEFAULT_EXE_NAME, Path.cwd() / DEFAULT_EXE_NAME):
        if candidate.exists():
            return candidate.resolve()
    _die(
        f"{DEFAULT_EXE_NAME} not found next to this script or in the "
        "current directory.\n"
        f"  → Run {here / 'install_linux.sh'} to fetch it automatically\n"
        f"  → Or download manually from "
        "https://github.com/Acrith/uma-it-optimizer/releases "
        f"and drop it in {here}"
    )


def find_proton_prefix(explicit: str | None, appid: str) -> Path:
    """Locate the Proton prefix for the given AppID."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            _die(f"--prefix path does not exist: {p}")
        return p
    tried: list[str] = []
    for root in STEAM_ROOTS:
        candidate = root / "steamapps" / "compatdata" / appid / "pfx"
        tried.append(str(candidate))
        if candidate.is_dir():
            return candidate
    _die(
        f"No Proton prefix found for AppID {appid}. Checked:\n"
        + "\n".join(f"  - {p}" for p in tried)
        + "\n  → Make sure Steam has run the game at least once (that's"
        " when Proton creates the prefix)."
        "\n  → If your Steam library is on another drive, pass --prefix."
    )


def find_wine(explicit: str | None) -> Path:
    """Prefer Proton's wine64 (matches the prefix version), then system
    wine. Scans compatibilitytools.d + steamapps/common for Proton
    installs, picks the newest by mtime."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            _die(f"--wine path does not exist: {p}")
        return p

    proton_wines: list[Path] = []
    for root in STEAM_ROOTS:
        for base in (root / "compatibilitytools.d",
                     root / "steamapps" / "common"):
            if not base.is_dir():
                continue
            for proton_dir in base.iterdir():
                if not proton_dir.is_dir():
                    continue
                # GE-Proton / official Proton layouts both put wine64 at
                # <proton>/files/bin/wine64.
                w = proton_dir / "files" / "bin" / "wine64"
                if w.is_file() and os.access(w, os.X_OK):
                    proton_wines.append(w)
    if proton_wines:
        # Newest install wins — a user with GE-Proton10-34 alongside an
        # older Proton wants the new one, and mtime is a decent proxy.
        proton_wines.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return proton_wines[0]

    system = shutil.which("wine64") or shutil.which("wine")
    if system:
        return Path(system)
    _die(
        "No wine found. Install Steam+Proton (needed anyway to run the "
        "game), or install a system 'wine' package. If you already have "
        "one somewhere non-standard, pass --wine /path/to/wine."
    )


def launch(wine: Path, prefix: Path, exe: Path) -> int:
    """exec `wine <exe>` with WINEPREFIX pointed at the game's prefix.
    Prints the resolved paths first so users can eyeball what got
    picked up before the frida attach happens."""
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    # Silence wine's console noise unless the user opted into debugging.
    env.setdefault("WINEDEBUG", "-all")

    print(f"[+] wine:    {wine}")
    print(f"[+] prefix:  {prefix}")
    print(f"[+] exe:     {exe}")
    print(f"[+] Launching under wine...\n")

    # Runs from the .exe's directory so its "runs/" output folder lands
    # next to the exe (matches the Windows one-click behaviour).
    return subprocess.call([str(wine), str(exe)], env=env, cwd=str(exe.parent))


def _die(msg: str) -> None:
    print(f"[X] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", help=f"Path to {DEFAULT_EXE_NAME}")
    ap.add_argument("--appid", default=DEFAULT_APPID,
                    help=f"Steam AppID (default: {DEFAULT_APPID} = Umamusume)")
    ap.add_argument("--prefix", help="Path to Proton prefix (overrides --appid)")
    ap.add_argument("--wine", help="Path to wine binary")
    args = ap.parse_args()

    if sys.platform != "linux":
        _die("This launcher is Linux-only. On Windows just run the .exe.")

    exe = find_extractor(args.exe)
    prefix = find_proton_prefix(args.prefix, args.appid)
    wine = find_wine(args.wine)
    return launch(wine, prefix, exe)


if __name__ == "__main__":
    sys.exit(main())

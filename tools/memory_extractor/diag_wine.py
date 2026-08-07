#!/usr/bin/env python3
"""Diagnose which Proton build owns a running prefix.

Run this WHILE THE GAME IS RUNNING:

    python diag_wine.py

Paste the whole output. It dumps every env var that could point at a
Proton install, for every process in the prefix, plus what the launcher's
detection would currently resolve. No writes, no attaching, read-only.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

APPID = "3224770"
ROOTS = [
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
]
# Anything that might carry a host-side path to the Proton tree. Steam
# containerises the game (pressure-vessel), so paths seen inside the
# container may not exist out here — which is the leading suspect for
# detection returning nothing.
VARS = [
    "WINELOADER", "WINESERVER", "WINEPREFIX", "WINEDLLPATH",
    "STEAM_COMPAT_TOOL_PATHS", "STEAM_COMPAT_CLIENT_INSTALL_PATH",
    "STEAM_COMPAT_DATA_PATH", "PROTONPATH", "PROTON_PATH",
    "STEAM_COMPAT_MOUNTS", "PRESSURE_VESSEL_RUNTIME", "container_manager",
]


def prefix_path() -> Path | None:
    for root in ROOTS:
        p = root / "steamapps" / "compatdata" / APPID / "pfx"
        if p.is_dir():
            return p
    return None


def main() -> int:
    pfx = prefix_path()
    print(f"prefix: {pfx}")
    if pfx is None:
        print("  !! no prefix found — is the game installed under a different Steam root?")
        return 1
    want = f"WINEPREFIX={pfx}".encode()

    hits = []
    for d in sorted(Path("/proc").iterdir()):
        if not d.name.isdigit():
            continue
        try:
            blob = (d / "environ").read_bytes()
        except (OSError, PermissionError):
            continue
        if want in blob:
            hits.append((d.name, blob))
    print(f"processes in this prefix: {len(hits)}\n")
    if not hits:
        print("  !! none — start the game first, then re-run this.")
        return 1

    seen: Counter[str] = Counter()
    for pid, blob in hits[:6]:
        env = {}
        for entry in blob.split(b"\x00"):
            if b"=" in entry:
                k, v = entry.split(b"=", 1)
                env[k.decode(errors="replace")] = v.decode(errors="replace")
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError as e:
            exe = f"<{e.__class__.__name__}>"
        print(f"--- pid {pid}")
        print(f"    /proc/{pid}/exe -> {exe}")
        print(f"        exists on host? {Path(exe).exists()}")
        for k in VARS:
            if k in env:
                v = env[k]
                mark = ""
                if k in ("WINELOADER", "WINESERVER"):
                    mark = f"   (exists: {Path(v).exists()})"
                print(f"    {k} = {v}{mark}")
                seen[k] += 1
        print()

    print("env vars present across those processes:", dict(seen))
    print("\ninstalled Proton builds and their loaders:")
    for root in ROOTS:
        for base in (root / "compatibilitytools.d", root / "steamapps" / "common"):
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                bindir = d / "files" / "bin"
                if not bindir.is_dir():
                    continue
                loaders = [n for n in ("wine64", "wine") if (bindir / n).is_file()]
                srv = "wineserver" if (bindir / "wineserver").is_file() else "-"
                print(f"    {d.name:<44} loaders={loaders or 'NONE'}  server={srv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

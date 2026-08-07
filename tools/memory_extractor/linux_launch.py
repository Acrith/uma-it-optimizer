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
  - Watches the wine process's stdout for "[!] Upload failed" lines;
    if the .exe couldn't POST the run (Wine + PyInstaller Python's
    bundled OpenSSL has a TLS fingerprint that Cloudflare's edge
    sometimes RSTs on odd IPs like VPNs), re-tries the upload from
    NATIVE Linux Python — same config + same token, different TLS
    stack (distro OpenSSL) that CF doesn't flag.

Run this WHILE the game is open in Steam/Proton.

Usage:
    python linux_launch.py                       # defaults
    python linux_launch.py --exe /path/to/exe    # custom .exe location
    python linux_launch.py --appid 3224770       # override Steam AppID
    python linux_launch.py --prefix /path/to/pfx # skip appid → prefix
    python linux_launch.py --wine /path/to/wine  # force a specific wine
    python linux_launch.py --upload 20260804T153304_scen2_uma102701.json
                                                 # re-upload a saved run
                                                 # (no wine, no game)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    # Distro-packaged compat tools live outside $HOME — CachyOS installs
    # proton-cachyos to /usr/share/steam/compatibilitytools.d.
    Path("/usr/share/steam"),
    Path("/usr/local/share/steam"),
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


def _dehost(p: Path) -> Path:
    """Map a pressure-vessel container path back to the host.

    Inside Steam's container the host filesystem is bind-mounted at
    /run/host, so a Proton install at /usr/share/steam/... is seen as
    /run/host/usr/share/steam/... — a path that does not exist when we
    look from outside. Strip the prefix so the host path is testable.
    """
    s = str(p)
    for pre in ("/run/host/", "/run/pressure-vessel/pv-from-host/"):
        if s.startswith(pre):
            return Path("/" + s[len(pre):])
    return p


def _loader_in(bindir: Path) -> Path | None:
    """The wine loader inside a Proton bin/ directory, or None.

    Wine 9 merged the 32/64-bit loaders: builds from that era ship only
    `wine`, with no `wine64`. Looking for `wine64` alone silently skips
    every modern Proton — including proton-cachyos 11.x — and falls back
    to whatever older build still has one, which is how a user ended up
    running Proton 10.0 against a proton-cachyos prefix and hit
    "version mismatch 932/856".
    """
    for name in ("wine64", "wine"):
        cand = bindir / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    return None


def wine_from_running_game(prefix: Path) -> Path | None:
    """wine64 of the Proton build ALREADY running this prefix, or None.

    "Newest Proton by mtime" is the wrong pick when the game runs under
    a different build: that prefix has a wineserver up already, and a
    mismatched client dies with

        wine client error:0: version mismatch 932/856.

    The wineserver protocol version is tied to the Wine build, so the
    only safe choice is the binary Steam actually launched. Every
    process in the prefix carries WINEPREFIX in its environ, so walk
    /proc and take the loader from the first match.
    """
    try:
        pids = [d.name for d in Path("/proc").iterdir() if d.name.isdigit()]
    except OSError:
        return None
    # Steam containerises the game (pressure-vessel), so paths seen in a
    # game process are container paths: /proc/PID/exe reads as
    # /run/host/usr/share/... which does not exist out here, and
    # WINELOADER/WINESERVER are not set at all. STEAM_COMPAT_TOOL_PATHS
    # is the reliable one — Steam sets it to HOST paths, first entry the
    # compat tool itself.
    want = f"WINEPREFIX={prefix}".encode()
    want_alt = want + b"/"          # Proton exports it with a trailing slash
    for pid in pids:
        try:
            blob = (Path("/proc") / pid / "environ").read_bytes()
        except (OSError, PermissionError):
            continue
        if want not in blob and want_alt not in blob:
            continue
        for entry in blob.split(b"\x00"):
            if entry.startswith(b"STEAM_COMPAT_TOOL_PATHS="):
                for part in entry.split(b"=", 1)[1].decode().split(os.pathsep):
                    if not part:
                        continue
                    cand = _loader_in(_dehost(Path(part)) / "files" / "bin")
                    if cand is not None:
                        return cand
            for var in (b"WINELOADER=", b"WINESERVER=", b"PROTONPATH="):
                if entry.startswith(var):
                    base = _dehost(Path(entry.split(b"=", 1)[1].decode()))
                    for d in (base.parent, base / "files" / "bin"):
                        cand = _loader_in(d)
                        if cand is not None:
                            return cand
        try:
            exe = _dehost(Path(os.readlink(f"/proc/{pid}/exe")))
            # .../files/bin/wineserver or .../files/lib/wine/*/wine-preloader
            for d in list(exe.parents)[:5]:
                cand = _loader_in(d / "files" / "bin") or _loader_in(d)
                if cand is not None:
                    return cand
        except OSError:
            continue
    return None


def find_wine(explicit: str | None, prefix: Path | None = None) -> Path:
    """Prefer the Proton already running this prefix, then the newest
    Proton install, then system wine."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            _die(f"--wine path does not exist: {p}")
        return p

    if prefix is not None:
        running = wine_from_running_game(prefix)
        if running is not None:
            print(f"[+] matched running game's Proton: {running}")
            return running

    proton_wines: list[Path] = []
    for root in STEAM_ROOTS:
        for base in (root / "compatibilitytools.d",
                     root / "steamapps" / "common"):
            if not base.is_dir():
                continue
            for proton_dir in base.iterdir():
                if not proton_dir.is_dir():
                    continue
                # GE-Proton / official Proton / proton-cachyos all use
                # <proton>/files/bin/. Wine 9+ ships only `wine` there.
                w = _loader_in(proton_dir / "files" / "bin")
                if w is not None:
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


_UPLOAD_FAIL_LINE = re.compile(r"^\[!\] Upload failed after \d+ attempts:")
_SAFE_AT_LINE = re.compile(r"^\[!\] Local file is safe at (\S+); retry later\.")

UPLOAD_TIMEOUT_SECONDS = 30
EXTRACTOR_VERSION_FALLBACK = "0.1.15"


def launch(wine: Path, prefix: Path, exe: Path) -> int:
    """exec `wine <exe>` with WINEPREFIX pointed at the game's prefix.
    Prints the resolved paths first so users can eyeball what got
    picked up before the frida attach happens.

    Streams the child's stdout live to our terminal AND captures it so
    we can look for "[!] Upload failed" + "[!] Local file is safe at"
    lines. When both appear, we retry the upload from native Linux
    Python (see :func:`retry_upload_native`) — the .exe's Wine-hosted
    urllib+OpenSSL is what CF is RSTing, native Linux has a different
    fingerprint. The retry fires IMMEDIATELY on seeing the marker,
    while the .exe is still parked on its "Press Enter to close..."
    prompt — waiting for the user to dismiss it first just delays the
    upload for no reason. Best-effort; the .exe already told the user
    the file is on disk, so a re-retry failure is a no-op UX-wise.
    """
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    # Silence wine's console noise unless the user opted into debugging.
    env.setdefault("WINEDEBUG", "-all")
    # Pin the toolchain to THIS wine's directory. Setting WINEPREFIX
    # alone leaves wine64 free to pick a wineserver off the system PATH,
    # which is the other half of the "version mismatch" failure — client
    # and server have to come from one build.
    bindir = wine.parent
    if (bindir / "wineserver").is_file():
        env["WINESERVER"] = str(bindir / "wineserver")
    env["WINELOADER"] = str(wine)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")

    print(f"[+] wine:    {wine}")
    print(f"[+] prefix:  {prefix}")
    print(f"[+] exe:     {exe}")
    print(f"[+] Launching under wine...\n")

    # Runs from the .exe's directory so its "runs/" output folder lands
    # next to the exe (matches the Windows one-click behaviour).
    proc = subprocess.Popen(
        [str(wine), str(exe)],
        env=env,
        cwd=str(exe.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # The exe's console output under Wine can arrive CP1252-encoded
        # (0x97 = em-dash) — strict UTF-8 would kill the tee mid-stream.
        # The marker lines we match are pure ASCII, so lossy is fine.
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # line-buffered so the tee is live, not chunked
    )

    saw_upload_fail = False
    saw_mismatch = False
    retried: set[str] = set()
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        if "version mismatch" in line:
            saw_mismatch = True
        if _UPLOAD_FAIL_LINE.match(line):
            saw_upload_fail = True
            continue
        m = _SAFE_AT_LINE.match(line)
        if m and saw_upload_fail:
            saw_upload_fail = False
            filename = m.group(1)
            if filename not in retried:
                retried.add(filename)
                retry_upload_native(exe.parent, filename)
    rc = proc.wait()
    if saw_mismatch:
        _print_mismatch_help(wine, prefix)
    return rc


def _print_mismatch_help(wine: Path, prefix: Path) -> None:
    """wineserver protocol mismatch — say what to do about it."""
    print(
        "\n[!] Wine reported a wineserver version mismatch.\n"
        "    This prefix already has a wineserver running from a DIFFERENT\n"
        "    Proton build than the wine64 used here; they must match.\n"
        f"      used: {wine}\n"
        f"    prefix: {prefix}\n"
        "    Try, in order:\n"
        "      1. Start the game first, then re-run this script — it reads\n"
        "         /proc to find the Proton that owns the prefix.\n"
        "      2. Name the build explicitly:\n"
        "           python linux_launch.py --wine '<Proton>/files/bin/wine64'\n"
        "         (Steam > game > Properties > Compatibility shows which.)\n"
        "      3. With the game closed, kill the stale server:\n"
        f"           WINEPREFIX='{prefix}' '{wine.parent / 'wineserver'}' -k",
        file=sys.stderr,
    )


def retry_upload_native(base_dir: Path, filename: str,
                        file_path: Path | None = None) -> None:
    """Upload a saved run JSON from native Linux Python. Reads the
    same uma-it-config.json the .exe writes/reads, POSTs the JSON
    with the same bearer/UA/X-Filename headers. Only reason to do this
    from the launcher is TLS-stack diversity — the .exe's bundled
    OpenSSL under Wine has a JA3 that some CF edges reject on flagged
    IPs; distro OpenSSL doesn't.

    ``file_path`` overrides the default ``base_dir/runs/filename``
    location (used by --upload with an explicit path).
    """
    cfg_path = base_dir / "uma-it-config.json"
    runs_path = file_path if file_path is not None else base_dir / "runs" / filename
    if not cfg_path.is_file():
        # No config = user never enabled auto-upload; the .exe already
        # skipped upload and saved the file. Nothing for us to do.
        return
    if not runs_path.is_file():
        print(f"[linux-retry] {runs_path} not found; nothing to retry.")
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[linux-retry] can't read {cfg_path.name}: {e}")
        return
    api_url = (cfg.get("api_url") or "").rstrip("/")
    api_token = cfg.get("api_token") or ""
    if not api_url or not api_token:
        # Config exists but auto-upload wasn't fully set up.
        return
    version = str(cfg.get("extractor_version") or EXTRACTOR_VERSION_FALLBACK)

    print(f"\n[linux-retry] Uploading {filename} from native Linux Python...")
    body = runs_path.read_bytes()
    req = urllib.request.Request(
        f"{api_url}/api/runs",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "X-Filename": filename,
            "Content-Type": "application/octet-stream",
            "Connection": "close",
            "User-Agent": (
                f"uma-it-extract-linux/{version} "
                f"(+https://training.umaladder.moe)"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_SECONDS) as resp:
            status = resp.status
            try:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, ValueError):
                payload = {}
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8") or "{}")
        except (json.JSONDecodeError, ValueError):
            msg = {}
        if e.code == 409:
            print(f"[linux-retry] [i] Already uploaded ({msg.get('message', 'duplicate')})")
        else:
            print(f"[linux-retry] [!] HTTP {e.code} — {msg.get('error', e.reason)}")
        return
    except urllib.error.URLError as e:
        print(f"[linux-retry] [!] Still failing from Linux: {e.reason}")
        print(f"[linux-retry] [!] The local file is safe at {runs_path}; ")
        print(f"[linux-retry]     drag/drop into {api_url}/upload as a last resort.")
        return

    if status == 201:
        detail_url = payload.get("url", "")
        print(f"[linux-retry] [OK] Uploaded → {detail_url or '(no url)'}")
        if detail_url:
            try:
                import webbrowser
                webbrowser.open(detail_url)
            except Exception:
                pass
    else:
        print(f"[linux-retry] [?] Unexpected HTTP {status}: {payload}")


def _die(msg: str) -> None:
    print(f"[X] {msg}", file=sys.stderr)
    sys.exit(1)


def upload_only(target: str) -> int:
    """--upload mode: push one saved run JSON with native Python.
    No wine, no game, no frida — just the HTTP POST. Accepts a bare
    filename (resolved against runs/ next to this script) or a path.
    """
    script_dir = Path(__file__).resolve().parent
    p = Path(target)
    if p.is_file():
        p = p.resolve()
        # Config lives next to the exe, i.e. one level above runs/.
        base_dir = p.parent.parent if p.parent.name == "runs" else script_dir
    else:
        candidate = script_dir / "runs" / p.name
        if not candidate.is_file():
            _die(f"{target} not found (also looked at {candidate})")
        p, base_dir = candidate, script_dir
    cfg = base_dir / "uma-it-config.json"
    if not cfg.is_file():
        _die(f"No uma-it-config.json at {base_dir} — run the extractor "
             "once and enable auto-upload to create it.")
    retry_upload_native(base_dir, p.name, file_path=p)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", help=f"Path to {DEFAULT_EXE_NAME}")
    ap.add_argument("--appid", default=DEFAULT_APPID,
                    help=f"Steam AppID (default: {DEFAULT_APPID} = Umamusume)")
    ap.add_argument("--prefix", help="Path to Proton prefix (overrides --appid)")
    ap.add_argument("--wine", help="Path to wine binary")
    ap.add_argument("--upload", metavar="FILE",
                    help="Skip wine entirely: upload a saved run JSON from "
                         "runs/ (bare filename or path) and exit.")
    args = ap.parse_args()

    if sys.platform != "linux":
        _die("This launcher is Linux-only. On Windows just run the .exe.")

    if args.upload:
        return upload_only(args.upload)

    exe = find_extractor(args.exe)
    prefix = find_proton_prefix(args.prefix, args.appid)
    # prefix first: find_wine() uses it to match the Proton already
    # running the game instead of guessing by install mtime.
    wine = find_wine(args.wine, prefix)
    return launch(wine, prefix, exe)


if __name__ == "__main__":
    sys.exit(main())

# UM:PD IT-run recorder

Saves the Independent Training run you're currently viewing to a local
JSON file, so you can look back at what happened later or feed it into
analysis tools. Reads what's on the Training Log screen — nothing
more, nothing that changes the game.

## For players (Windows)

Linux/Proton players: skip to the [Linux section](#for-linux-players-steam--proton) below.

**Do this once per IT run:**

1. Complete a run
2. Reach the Training Log screen (the pop-up right after IT finishes,
   before you press OK — any tab is fine)
3. Double-click **`uma-it-extract.exe`**
4. Wait a few seconds. A JSON file appears in the `runs/` folder next
   to the exe.

That's the whole thing. No Python, no command line, no configuration.

**If the game isn't running yet:** the recorder waits up to 5 minutes
for you to launch it, then extracts as soon as you reach a Training
Log.

**Files land at** `runs/<timestamp>_scen<N>_uma<N>.json` — new file
per run, sortable by name, they stay on your machine. You keep them.

**What's in each file:** everything the Training Log shows — stats,
aptitudes, deck contents, per-card contributions, factors per year,
skill hints, race history. Plus a few fields the game doesn't display
directly (parent IDs, exact numeric IDs for cards / uma / skills — the
same IDs the public gametora database uses, so cross-referencing later
is easy).

**Nothing is uploaded by default.** Everything stays local unless you
opt in to auto-upload (below). The recorder always writes the local
JSON first — a failed upload can never cost you a run.

## Auto-upload (optional)

Your runs can auto-upload to the community dashboard at
[training.umaladder.moe](https://training.umaladder.moe) so you don't
have to drag-and-drop each JSON.

**Setup is interactive on first run.** The extractor prompts once:

```
──────────────────────────────────────────────
  First-run setup
──────────────────────────────────────────────

Auto-upload runs to the community dashboard at
  https://training.umaladder.moe
...
Enable auto-upload? [Y/n]:
```

- Answer **Y** → it prints the token page URL, you sign in with Discord,
  click *Issue new token*, paste the `ext_…` string, done. Every future
  run auto-uploads.
- Answer **n** (or paste an empty token) → local-only mode, no upload.
  The extractor won't ask again.

Either way, a `uma-it-config.json` gets written next to the exe so
future runs know your choice. To change your mind later, open that file
in Notepad and edit `api_token` (empty = disabled, filled = enabled).

**Local JSONs are always written first**, before the upload. A failed
POST can never cost you a run — the file is safe on disk. If the server
already has a run (duplicate), it silently accepts and moves on.

## For Linux players (Steam + Proton)

Same one-JSON-per-run output as the Windows flow — just an extra
command-line step because native-Linux Frida can't attach to a wine-
hosted Windows process directly (see [why](#why-not-just-double-click-the-exe)
if you're curious). The launcher runs the Windows extractor under
your Proton prefix's wine, which Frida handles natively.

**Prerequisites**
- Uma Musume installed on Steam and launched at least once (Steam
  creates the Proton prefix the launcher needs)
- Python 3 (`python --version` — most distros have this out of the box)
- `curl` or `wget` (used once to grab the extractor .exe)

**One-time setup:**

```bash
git clone https://github.com/Acrith/uma-it-optimizer.git
cd uma-it-optimizer/tools/memory_extractor
./install_linux.sh
```

That downloads `uma-it-extract.exe` from the latest GitHub release and
drops it next to the launcher. Rerun the script anytime you want to
update the extractor to a newer release.

**Every run:**

1. Complete an IT run
2. Reach the Training Log screen (before pressing OK — any tab is fine)
3. In a terminal:
   ```bash
   cd path/to/uma-it-optimizer/tools/memory_extractor
   python linux_launch.py
   ```
4. Wait a few seconds. JSON appears in `runs/` next to the launcher.

The launcher auto-discovers the game's Proton prefix (Steam AppID
`3224770` for Umamusume Global) and Proton's own `wine64` binary,
prints what it picked up so you can eyeball, then attaches. Same
"waits up to 5 minutes for you to reach a Training Log" behaviour as
the Windows exe.

**If the game's on a non-standard Steam library** (extra drive,
Flatpak Steam in a weird spot, etc.) pass the prefix directly:

```bash
python linux_launch.py --prefix /path/to/steamapps/compatdata/3224770/pfx
```

See `python linux_launch.py --help` for all overrides (`--exe`,
`--wine`, `--appid`).

**Troubleshooting**

- **"No Proton prefix found for AppID 3224770"** — you haven't run
  the game through Steam+Proton yet, or Steam library is in a non-
  standard location. Launch Uma once, then retry; if it still can't
  find it, pass `--prefix`.
- **"uma-it-extract.exe not found"** — rerun `./install_linux.sh`
  (or grab the .exe from [Releases](https://github.com/Acrith/uma-it-optimizer/releases)
  manually and drop it next to `linux_launch.py`).
- **The game crashes after extraction completes** — sometimes
  happens under wine and it's a Frida-in-wine flake; the JSON was
  already captured before the crash. Relaunch and continue.
- **"bootstrapper crashed with signal 11"** — this means you're
  running native `dump_it_run.py` instead of the launcher. Use
  `python linux_launch.py`; the native path doesn't work under
  wine (that's why the launcher exists).

**Cleanup**

Nothing gets installed at system level — everything lives inside
the cloned repo. To remove: `rm -rf uma-it-optimizer/`.

**Why not just double-click the .exe?**

Frida's native-Linux injector uses ptrace to write shellcode into
the target's address space. Wine-hosted processes have Windows PE
code and the Linux wine loader ELF sharing one address space, and
the injector's bootstrapper SIGSEGVs when it hits the boundary.
Running the extractor .exe UNDER wine sidesteps this — Frida-inside-
wine treats another wine-hosted process as a native Windows target
and injects the same way it does on real Windows. `linux_launch.py`
is the small amount of Linux-side plumbing that makes that arrangement
one-command.

## For developers

**Run from source (Windows):**

```
pip install frida frida-tools
cd tools\memory_extractor
python setup.py       # one-time: fetches the bridge JS bundle
python dump_it_run.py
```

Auto-detects the game, waits if needed, auto-names the output.

**Build the standalone exe:**

```
pip install pyinstaller
pyinstaller build_exe.spec
```

Result at `dist/uma-it-extract.exe` (~15 MB, self-contained —
bundles Python, Frida, and the bridge JS).

**How it works — short version.** Attaches Frida to the running game
process, walks IL2CPP metadata via `frida-il2cpp-bridge`, reads the
current-run C# objects, unwraps CodeStage.AntiCheat obfuscated
integers, writes the result out as JSON. No memory writes, no
function hooks, no game state modification. Same technique the
community's existing veteran-list dumper (UmaExtractor) uses — that
tool has been in use for months. If you were comfortable with that,
this is the same category.

**Not shipped on purpose:** any behaviour that modifies the game,
automates decisions, changes race outcomes, or interacts with the
network. Please don't add any.

## Data notes

- Your own `viewer_id` doesn't appear in the dump.
- Friend-rental support cards include the borrowed card's
  `owner_viewer_id` (the friend's account ID). If you share runs
  publicly later, decide whether to strip those.
- Numeric IDs (support cards, uma cards, skills, races, factors) are
  the same integers gametora uses — so you can enrich locally by
  joining against a cached copy of the public gametora tables.

## Compatibility

Class layouts verified against the 2026-07 Global Steam build. Game
updates can shift field names; if the recorder starts failing, that's
where to look first. Mobile / Proton / non-Steam builds aren't
supported by this tool — use the screenshot-based fallback in the
main Python package instead.

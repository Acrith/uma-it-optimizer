# UM:PD IT-run recorder

Saves the Independent Training run you're currently viewing to a local
JSON file, so you can look back at what happened later or feed it into
analysis tools. Reads what's on the Training Log screen — nothing
more, nothing that changes the game.

## For players

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

**Nothing is uploaded anywhere.** Everything stays local. A future
opt-in tool may let you publish specific runs to a companion
community dashboard, but the recorder itself will always default to
local-only.

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

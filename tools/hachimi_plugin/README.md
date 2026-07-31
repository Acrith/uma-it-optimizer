# uma-it plugin

Records the Independent Training run you just finished to a local JSON
file, and (optionally) uploads it to
[training.umaladder.moe](https://training.umaladder.moe) — same output
schema as `uma-it-extract.exe`, but the trigger button lives inside the
game menu instead of a separate program.

**Status: v1.0.2 — stable.** Full field-level parity with the `.exe`
extractor: all seven data classes (gains, support-card gains, factor
gains, chara, race history × 2, and the two direct parents with their
grandparent lineage) are walked and serialized under the same JSON
keys the web app already reads.

Ships as a DLL plugin loaded by [Hachimi-Edge](https://github.com/kairusds/Hachimi-Edge),
which is the platform users already have for translations. If Hachimi
is set up for you, this plugin is one drop-in DLL plus one line of
config.

## For players

**One-time setup:**

1. Download `uma_it_plugin.dll` from the
   [Releases page](https://github.com/Acrith/uma-it-optimizer/releases)
   (look for a `hachimi-v*` tag; the newest one wins).
2. Right-click → **Properties** → tick **Unblock** at the bottom of
   the General tab → **OK**. (Windows blocks downloaded DLLs from
   loading unless you allow them.)
3. Drop the DLL in the game folder — same place your Hachimi DLL
   lives.
4. Open `<game folder>/hachimi/config.json` and add the DLL to the
   top-level `load_libraries` array:
   ```json
   "load_libraries": ["uma_it_plugin.dll"],
   ```
   If the array already has entries, just add ours alongside them.

**Every run:**

1. Complete an IT run.
2. Stay on the **Training Log** pop-up (the screen right after IT
   finishes, before you press OK — any tab is fine).
3. Open the Hachimi menu (**F1** on PC), click **Extract IT Run**
   under the Plugins section.
4. A brief (~50 ms) stutter on click is normal — that's the heap
   scan.

The run is saved to `<game folder>/hachimi/IT/` as
`<timestamp>_scen<N>_uma<N>.json`. Filename matches the `.exe`
extractor's convention so a shared runs folder sorts cleanly.

## Auto-upload (optional)

The Plugins section also exposes an **IT Token** field. Paste a token
from [training.umaladder.moe/settings/tokens](https://training.umaladder.moe/settings/tokens)
and click **Save**. Every future extract also POSTs the same JSON to
`/api/runs`; a Hachimi toast reports success, duplicate, or failure.

**The local file is always written first**, before the upload. A failed
POST can never cost you a run — the JSON is safe on disk.

Config persists at `<game folder>/hachimi/uma_it_plugin_config.json`
in the same shape the `.exe` extractor uses (`api_url` + `api_token`),
so you can share a token file between the two if you use both. The URL
defaults to production; power users running a dev server can edit
`api_url` by hand.

## Failure modes to watch for

- **Plugin doesn't log at all** — Hachimi didn't load the DLL. Check
  it's in the same folder as Hachimi's own DLL and that
  `uma_it_plugin.dll` appears in the top-level `load_libraries`
  array (not nested under `windows`).
- **`Hachimi too old? Need VERSION >= 3`** — update your Hachimi
  install.
- **Menu entry missing** — Hachimi's menu system wasn't ready at our
  init time. The plugin falls back to registering via
  `game_initialized`, so this should self-heal on the next launch.
- **Upload says HTTP 400 or 401** — token typo or the URL got
  corrupted. Re-paste the token; if the URL was hand-edited, restore
  it to `https://training.umaladder.moe` in the config file.
- **Everything worked but nothing appears on the site** — verify the
  Training Log pop-up was actually open when you clicked; the plugin
  reads that screen and nothing else. Local JSON is your fallback:
  upload it manually via the site's Upload page.

## For developers

Building requires a stable Rust toolchain with the
`x86_64-pc-windows-msvc` target.

**On Windows:**
```
cd tools/hachimi_plugin
cargo build --release --target x86_64-pc-windows-msvc
# → target/x86_64-pc-windows-msvc/release/uma_it_plugin.dll
```

**On Linux (cross-compile):**
```
rustup target add x86_64-pc-windows-msvc
cargo install cargo-xwin       # first time only
cd tools/hachimi_plugin
cargo xwin build --release --target x86_64-pc-windows-msvc
```

**Release cut:** tag the repo with `hachimi-v1.0.X`. GitHub Actions
builds on `windows-latest`, attaches `uma_it_plugin.dll` to the
release, and marks the release as *not-latest* so extractor releases
keep the `/releases/latest/download/…` pointer.

### Version history (brief)

- v0.0.1..v0.0.5 — hook-based prototypes. All failed for different
  reasons (wrong dialog, framerate collapse, unresolvable ctors).
- v0.0.6 — pivoted to IL2CPP GC heap-scan. Counting live instances
  of the IT data class, no field walking.
- v0.0.7 — walked scalar fields to JSON.
- v0.0.8 — extended walk to include support cards, race history,
  factor gains, and both parents with their grandparent lineage.
  Full field-level parity with the `.exe` extractor confirmed via
  side-by-side comparison.
- v0.0.9 — first HTTP POST to `/api/runs`, extractor-style
  filename, external-file config.
- v1.0.0..v1.0.2 — in-game settings section for the token, minimal
  UI, single-section layout.

### Layout

```
tools/hachimi_plugin/
├── LICENSE                  # GPL-3.0-or-later (whole subfolder)
├── NOTICE.md                # attribution for vendored edge-sdk
├── Cargo.toml               # workspace
├── edge-sdk/                # vendored Hachimi-Edge FFI bindings
│   ├── Cargo.toml
│   └── src/{lib,api,entry,ffi,log}.rs
└── uma_it_plugin/           # our cdylib
    ├── Cargo.toml
    └── src/{lib,config,http,settings_ui,gc_scan,introspect,json}.rs
```

### License

**This subfolder is GPL-3.0-or-later**, not MIT like the rest of
uma-it-optimizer. `edge-sdk/` is vendored from
[honse-tracker](https://github.com/jalbarrang/honse-tracker) which
is GPL, and it wraps Hachimi-Edge's plugin API which is also GPL.
See `NOTICE.md` for full attribution and `LICENSE` for the text.

# uma-it Hachimi plugin

A [Hachimi-Edge](https://github.com/kairusds/Hachimi-Edge) plugin
that captures Umamusume Independent Training runs directly from
inside the game, without needing the separate `uma-it-extract.exe`
tool.

**Status: v0.0.6 — heap-scan proof of concept.** The plugin
registers an "Extract IT Run" entry in Hachimi's in-game menu.
When clicked, it walks the IL2CPP GC heap for live instances of
`Gallop.ObscuredIdleSingleModeGainInfo` (the IT-specific data
class the Frida extractor scans) and logs the count. Same
signal as the extractor, without needing a separate .exe.

Only counts for now — no field walking or upload. Those land in
v0.0.7 and v0.0.8 respectively.

Why manual trigger (menu click) over auto-detect:
- A GC scan freezes all mutator threads for 20-80ms — never run
  it per-frame
- Auto-detecting Training Log open would require hooking specific
  IL2CPP methods that Cygames renames across game updates
- The heap-scan approach only depends on the data class name
  (stable across builds), making the plugin dramatically more
  update-resilient

Prior versions took the hook-based path and hit that fragility
head-on:
- v0.0.1..v0.0.3: hooked `DialogTrainedCharacterDetail::CreateSetupParameter`
  (Uma-ISC's older-build reference). Installed but fired on the
  wrong dialog (Trained Umas viewer, not IT log).
- v0.0.4: hooked `GainInfo::.ctor` — trampoline was `Object.ctor`,
  6,500 fires/sec, 5fps game.
- v0.0.5: added declared-on-class check → safe no-op (GainInfo
  has no declared ctor to hook). Confirmed hook-based path is a
  dead end.

## For testers (v0.0.6)

You need Hachimi-Edge already installed and working for
translations. If translations don't work, this plugin won't work
either.

1. Download `uma_it_plugin.dll` from the
   [Releases page](https://github.com/Acrith/uma-it-optimizer/releases)
   (look for a `hachimi-v*` tag).
2. Drop it in the same folder as your Hachimi DLL (usually the
   Umamusume game folder next to `UmamusumePrettyDerby.exe`, where
   Hachimi's `dxgi.dll` lives).
3. Open Hachimi's `config.json` (usually in `<game folder>/hachimi/`)
   and find the existing `load_libraries` field — it's a top-level
   array, not nested under `windows`. Add our DLL to it:
   ```json
   "load_libraries": ["uma_it_plugin.dll"],
   ```
   If the field already had entries, just add ours to the array.
   Also flip `enable_file_logging` to `true` in the same file so
   Hachimi writes a `hachimi.log` you can grep — plugin output
   otherwise only shows in the in-game debug console.
4. Launch the game. Complete an IT run, reach the Training Log
   popup screen.
5. Launch the game. On plugin load you should see:
   ```
   [uma-it] plugin loaded (v0.0.6 heap-scan POC)
   [uma-it] target class resolved: Gallop.ObscuredIdleSingleModeGainInfo @ 0x...
   [uma-it] IL2CPP liveness API resolved (Unity 2021.2+ path)
   [uma-it] setup complete — 'Extract IT Run' available in Hachimi menu
   ```
6. Open Hachimi's in-game menu (**F1** by default on PC). You
   should see a new entry: **Extract IT Run**.
7. To test the scan on an empty game state (Training Log NOT
   open — e.g. from the home screen), click **Extract IT Run**.
   Expect:
   ```
   [uma-it] starting heap scan for GainInfo instances (this pauses the game ~20-80ms)
   [uma-it] scan complete: 0 GainInfo instances found in NNms
   [uma-it] no instances — is the Training Log popup open? ...
   ```
   A visible ~50ms stutter on click is expected and normal.
8. To test the scan on the target state: complete an IT, open
   the **Training Log** popup, then open Hachimi menu → click
   **Extract IT Run**. Expect:
   ```
   [uma-it] scan complete: N GainInfo instances found in NNms
   ```
   where N > 0. If N == 0 on the Training Log screen, that means
   the class isn't populated there and we need to reconsider.

9. **Report back** — the counts (empty vs Training Log), the
   scan durations, and whether you saw any framerate weirdness
   OTHER than the expected click-time stutter.

## Failure modes to watch for

- **`Hachimi-Edge too old? Need VERSION >= 3`** — update Hachimi-Edge.
- **`Gallop.ObscuredIdleSingleModeGainInfo class not found`** —
  IL2CPP class was renamed in a game update (rare — stable
  across builds). Share log; we'll retarget.
- **`il2cpp_resolve_symbol(...) returned null`** — Unity < 2021.2
  or a stripped IL2CPP build. Share the specific symbol name in
  the message; we may have to switch to the legacy liveness API.
- **`gui_register_menu_item returned false`** — Hachimi's menu
  system isn't ready at our init time. Plugin falls back to
  registering via `game_initialized` — should work but if the
  menu entry never appears, share the log.
- **Menu entry appears but game freezes on click** — the
  stop_gc_world / start_gc_world pair got unbalanced. Bug in
  the plugin; report the log immediately (game will remain
  frozen until killed).
- **Plugin doesn't log at all** — Hachimi didn't load it. Check
  the DLL is in the right folder and appears in the top-level
  `load_libraries` array (not nested under `windows`) exactly as
  `uma_it_plugin.dll`.

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
# You'll need cargo-xwin or MinGW cross-toolchain; simplest is:
cargo install cargo-xwin
cd tools/hachimi_plugin
cargo xwin build --release --target x86_64-pc-windows-msvc
```

**Release cut:** tag the repo with `hachimi-v0.0.X`. GitHub Actions
builds on `windows-latest` and attaches `uma_it_plugin.dll` to the
release automatically.

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
    └── src/lib.rs
```

### License

**This subfolder is GPL-3.0-or-later**, not MIT like the rest of
uma-it-optimizer. `edge-sdk/` is vendored from
[honse-tracker](https://github.com/jalbarrang/honse-tracker) which
is GPL, and it wraps Hachimi-Edge's plugin API which is also GPL.
See `NOTICE.md` for full attribution and `LICENSE` for the text.

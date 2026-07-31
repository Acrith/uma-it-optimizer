# uma-it Hachimi plugin

A [Hachimi-Edge](https://github.com/kairusds/Hachimi-Edge) plugin
that captures Umamusume Independent Training runs directly from
inside the game, without needing the separate `uma-it-extract.exe`
tool.

**Status: v0.0.1 — proof of concept.** The plugin loads, hooks the
Training Log method, and logs when the hook fires. It doesn't yet
walk the run data or upload — those land in v0.0.2+ once we've
verified the hook fires reliably on the current game build.

## For testers (v0.0.1)

You need Hachimi-Edge already installed and working for
translations. If translations don't work, this plugin won't work
either.

1. Download `uma_it_plugin.dll` from the
   [Releases page](https://github.com/Acrith/uma-it-optimizer/releases)
   (look for a `hachimi-v*` tag).
2. Drop it in the same folder as your Hachimi DLL (usually the
   Umamusume game folder next to `UmamusumePrettyDerby.exe`, where
   Hachimi's `dxgi.dll` lives).
3. Open Hachimi's `config.json` and add `uma_it_plugin.dll` to the
   `windows.load_libraries` array:
   ```json
   {
     "windows": {
       "load_libraries": ["uma_it_plugin.dll"]
     }
   }
   ```
   (If `windows.load_libraries` already has entries, just append
   ours to the list.)
4. Launch the game. Complete an IT run, reach the Training Log
   popup screen.
5. Check Hachimi's log file (usually `hachimi.log` next to the
   game exe). You should see lines like:
   ```
   [uma-it] plugin loaded, waiting for game_initialized to install hooks
   [uma-it] game initialized — installing DialogTrainedCharacterDetail hook
   [uma-it] target method resolved at 0x...
   [uma-it] hook installed; trampoline at 0x...
   [uma-it] CreateSetupParameter fired: is_single_mode=true is_follow=false chara_data=0x...
   ```
6. **Report back** — if you see `is_single_mode=true` on the
   Training Log open, we're good to build the data-walking Phase 2.
   If not, share the log so we can diagnose (usually a game update
   changed the method arg count or a class name).

## Failure modes to watch for

- **`Hachimi-Edge too old? Need VERSION >= 3`** — update Hachimi-Edge.
- **`CreateSetupParameter(5) not found — arg count changed?`** —
  game update touched the method signature. Share the log; we'll
  bump the arg count in a v0.0.1a.
- **`Gallop.DialogTrainedCharacterDetail class not found`** —
  IL2CPP class was renamed in a game update. Same story: share log,
  we'll update.
- **Plugin doesn't log at all** — Hachimi didn't load it. Check
  the DLL is in the right folder and appears in
  `windows.load_libraries` exactly as `uma_it_plugin.dll`.

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

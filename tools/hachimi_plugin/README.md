# uma-it Hachimi plugin

A [Hachimi-Edge](https://github.com/kairusds/Hachimi-Edge) plugin
that captures Umamusume Independent Training runs directly from
inside the game, without needing the separate `uma-it-extract.exe`
tool.

**Status: v0.0.5 — safe no-op fallback.** The plugin loads and
attempts to hook `Gallop.ObscuredIdleSingleModeGainInfo::.ctor`,
but first verifies the resolved ctor is declared on the class
(not inherited from `System.Object`). If it's inherited, the
plugin refuses to install and stays as a no-op — no game-perf
impact, no log spam. Even if it does install, the "ctor fired"
log is rate-limited to the first 3 hits per session.

Why the caution: v0.0.4 didn't check inheritance, hooked
`Object::.ctor` by accident, and fired on every C# allocation
in the game — 6,500/sec, 500k log lines/minute, 5fps. v0.0.5
makes that class of mistake structurally impossible.

Prior versions:
- v0.0.1..v0.0.3: hooked `DialogTrainedCharacterDetail::CreateSetupParameter`
  (Uma-ISC's older-build reference). Installed cleanly but fired
  on the wrong dialog (Trained Umas viewer, not IT log).
- v0.0.4: hooked `GainInfo::.ctor` with no inheritance check —
  trampoline was `Object.ctor`, hosed framerate.

If v0.0.5 installs cleanly (declared ctor exists), we know we
have a working trigger. If it declines (most likely — POCO data
holders rarely declare their own default ctor), v0.0.6 will use
a different mechanism — either add heap-scan symbols to the
vendored edge-sdk, or hook a specific declared method identified
via an IL2CPP dump.

## For testers (v0.0.5)

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
5. Check Hachimi's log file (usually `hachimi.log` next to the
   game exe). At plugin load, ONE of two things will happen:

   **Case A** — ctor is declared on the class, hook installs:
   ```
   [uma-it] plugin loaded
   [uma-it] target method resolved at 0x... (argc=0)
   [uma-it] hook installed; trampoline at 0x...
   [uma-it] hook installed at init (game already up)
   ```
   Then on Training Log open, up to 3 lines like:
   ```
   [uma-it] ObscuredIdleSingleModeGainInfo::.ctor fired: this=0x... (log #1/3)
   ...
   [uma-it] ObscuredIdleSingleModeGainInfo::.ctor fired: this=0x... (log #3/3 — silencing further fires this session)
   ```

   **Case B** — ctor is inherited (most likely for POCOs):
   ```
   [uma-it] plugin loaded
   [uma-it] target method resolved at 0x... (argc=0)
   [uma-it] .ctor at argc=0 is inherited from a base class, NOT declared on ObscuredIdleSingleModeGainInfo. Refusing to install...
   [uma-it] eager install declined; not registering fallback
   ```
   Plugin becomes a safe no-op. No game impact, no data captured.
   We'll ship a v0.0.6 with a different trigger.

6. **Report back** which case you saw. Case A means Phase 2 (walk
   fields + POST) is next. Case B means we need to change the
   trigger mechanism.

## Failure modes to watch for

- **`Hachimi-Edge too old? Need VERSION >= 3`** — update Hachimi-Edge.
- **`.ctor at argc=... is inherited from a base class`** — see
  Case B above; expected, plugin is a safe no-op.
- **`discovered argc=N but our hook is hardcoded to 0`** — the
  class grew a non-default constructor. Plugin refuses to install
  to avoid stack corruption. Share the log.
- **`.ctor not found at any arg count 0..4`** — class was
  refactored. Share the log; we'll dnSpy the new shape.
- **`Gallop.ObscuredIdleSingleModeGainInfo class not found`** —
  IL2CPP class was renamed (rare — stable across builds). Share
  log.
- **Plugin doesn't log at all** — Hachimi didn't load it. Check
  the DLL is in the right folder and appears in the top-level
  `load_libraries` array (not nested under `windows`) exactly as
  `uma_it_plugin.dll`.
- **Massive log file + framerate crash** — this was the v0.0.4
  bug. If you see this in v0.0.5+, the declared-on-class check
  failed and it's a plugin bug worth reporting.

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

# Third-party attribution

## edge-sdk/

The Rust FFI bindings under `edge-sdk/src/{api,entry,ffi,log}.rs` are
vendored (with minor changes — dropped the `gui`/`sdk` modules we don't
use) from:

- **jalbarrang/honse-tracker** — <https://github.com/jalbarrang/honse-tracker>
- License: GPL-3.0-or-later

honse-tracker in turn transcribed its FFI layer from Hachimi-Edge's
`src/core/plugin_api.rs`:

- **kairusds/Hachimi-Edge** — <https://github.com/kairusds/Hachimi-Edge>
- License: GPL-3.0-or-later

Because both upstream projects are GPL-3.0-or-later, this plugin
subdirectory (`tools/hachimi_plugin/`) is also licensed
**GPL-3.0-or-later** — see `LICENSE`. The rest of uma-it-optimizer
remains under its original license (MIT).

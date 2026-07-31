# UM:PD IT-run recorder & optimizer

Save your Independent Training runs to local JSON files so you can
look back at what actually happened — deck used, per-card
contributions, factors gained per year, race history, the works. Over
enough runs it turns into a personal dataset for figuring out which
setups actually work for a target parent profile.

A companion web dashboard is live at
[**training.umaladder.moe**](https://training.umaladder.moe) — a
sister project to [umaladder.moe](https://umaladder.moe). Opt in to
share runs and get insights no single player has enough data for on
their own (deck-value statistics across thousands of scenarios,
cross-community aggregations, per-card contribution distributions).

Everything else is local-first. Nothing leaves your machine unless
you paste a token into a capture tool and opt in to auto-upload.

---

## Two capture tools — pick one

Both save the same JSON and both can auto-upload. Pick whichever fits
how you play.

| Your setup | Download this file | Trigger |
|---|---|---|
| Windows Steam (no Hachimi) | **`uma-it-extract.exe`** — from the [latest release](https://github.com/Acrith/uma-it-optimizer/releases/latest) | Double-click after each IT run |
| [Hachimi-Edge](https://github.com/kairusds/Hachimi-Edge) user | **`uma_it_plugin.dll`** — from a [`hachimi-v*` release](https://github.com/Acrith/uma-it-optimizer/releases) | "Extract IT Run" in the F1 menu |

Both work under Steam+Proton on Linux (extractor via
`install_linux.sh` + `linux_launch.py`; the plugin runs wherever
Hachimi runs).

**Full setup walkthrough with screenshots:**
[training.umaladder.moe/guide](https://training.umaladder.moe/guide)
or [`docs/user-guide.md`](docs/user-guide.md) for the same content
rendered on GitHub.

Per-tool docs:
[`tools/memory_extractor/README.md`](tools/memory_extractor/README.md),
[`tools/hachimi_plugin/README.md`](tools/hachimi_plugin/README.md).

---

## Repo layout

- **`tools/memory_extractor/`** — the Windows / Proton Frida-based
  `.exe` extractor. Standalone, no install.
- **`tools/hachimi_plugin/`** — Rust cdylib Hachimi plugin. Ships as
  a DLL that loads inside the game. GPL-3.0-or-later (see subfolder
  LICENSE — inherits from the vendored edge-sdk).
- **`docs/`** — the setup guide + screenshots.
- **`src/uma_it_optimizer/`** — earlier screenshot-based reader,
  kept as a fallback for players who can't run either capture tool
  (mobile, non-Steam, etc.). Same output schema (or close to it).
- **`references/`** — read-only upstream projects kept locally for
  reference. Do not edit anything under here.

The web app lives in a sibling repo,
[`uma-it-web`](https://github.com/Acrith/uma-it-web), deployed to
Fly.io as `training.umaladder.moe`.

---

## Building blocks — worth knowing before writing anything

Community-maintained references / data sources the project builds on.
If you're extending anything, check whether one of these already
covers what you need:

- **[gametora.com](https://gametora.com/umamusume)** — the definitive
  public database of cards, umas, skills, races, scenarios. Every
  numeric ID the recorder produces is a direct join key. Use this as
  the enrichment layer instead of scraping game data yourself.
- **[HIDEPON-UMG/UmamusumeFactorDB](https://github.com/HIDEPON-UMG/UmamusumeFactorDB)**
  — factor-screen OCR pipeline (Python, ONNX + EasyOCR). Useful as a
  reference for how the older screenshot-based path handles factor
  data.
- **[mee1080/umasim](https://github.com/mee1080/umasim)** (Kotlin,
  AGPLv3) / **[hzyhhzy/UmaAi](https://github.com/hzyhhzy/UmaAi)** /
  **[AC01010/Umamusume-Training-Simulator](https://github.com/AC01010/Umamusume-Training-Simulator)**
  — career simulator cores. Not integrated (this project analyzes
  outcomes, doesn't simulate them), but useful to consult when you
  want to sanity-check "would this setup theoretically work".
- **[amay077/uma_skill_manager](https://github.com/amay077/uma_skill_manager)**
  — skill / support data (TS, derived from umasim). Alternative to
  gametora for the enrichment layer.

---

## What this project is / isn't

- **Is:** a personal analytics tool. It reads publicly-displayed
  in-game data from a screen you're already looking at, and saves it
  in a structured form for later analysis. It does not modify the
  game, does not affect race outcomes, does not automate gameplay.
- **Isn't:** a bot, an auto-clicker, a modification, or a scraper of
  game master data. It doesn't and won't ship anything that plays the
  game for you or changes what the game does.
- Data extraction on the Steam build uses the same well-known
  technique the community's existing veteran-list dumper has been
  using for months. See each capture tool's README for specifics.

---

## Contributing

- Try either capture tool on a few runs, see if the output looks
  sensible for your setup, open an issue with anything weird. The
  hachimi plugin is newer (v1.0.x) so field parity there gets extra
  scrutiny — bug reports welcome.
- Guide screenshots occasionally go stale as the game UI updates —
  PRs updating any of the images under `docs/img/` are appreciated.
- Web app changes go to
  [`uma-it-web`](https://github.com/Acrith/uma-it-web), not here.

## License

MIT for this repo (see `LICENSE`). `tools/hachimi_plugin/` is
GPL-3.0-or-later — it inherits from the vendored Hachimi-Edge FFI
bindings, which are GPL. Any borrowed code or data from the projects
listed in Building Blocks must preserve their original license and
attribution.

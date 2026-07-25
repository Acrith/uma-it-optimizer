# UM:PD IT-run recorder & optimizer

Save your Independent Training runs to local JSON files so you can look
back at what actually happened — deck used, per-card contributions,
factors gained per year, race history, the works. Over enough runs it
turns into a personal dataset for figuring out which setups actually
work for a target parent profile.

Long-term goal: an aggregated dashboard hosted as a companion under
the umaladder.com project (subdomain TBD) where community members can
opt-in to share their runs and get insights no single player has enough
data for on their own (e.g. deck-value statistics across thousands of
scenarios).

Everything today is local-only. Nothing leaves your machine unless you
explicitly upload.

---

## What's in the box today

- **`tools/memory_extractor/`** — a Windows companion that saves your
  currently-displayed Training Log to a JSON file. Double-click to run;
  new file appears in a `runs/` folder next to the exe. See its
  [README](tools/memory_extractor/README.md) for the player guide.
- The Python package (`src/uma_it_optimizer/`) is an earlier
  screenshot-based reader kept as a fallback for players who can't run
  the memory extractor (mobile, non-Steam, etc.). Same output schema
  (or close to it).

## Building blocks — worth knowing before writing anything

These are the community-maintained references / data sources the
project builds on. If you're extending anything, check whether one of
these already covers what you need:

- **[gametora.com](https://gametora.com/umamusume)** — the definitive
  public database of cards, umas, skills, races, scenarios. Every
  numeric ID the recorder produces is a direct join key. Use this as
  the enrichment layer instead of scraping game data yourself.
- **[HIDEPON-UMG/UmamusumeFactorDB](https://github.com/HIDEPON-UMG/UmamusumeFactorDB)**
  — factor-screen OCR pipeline (Python, ONNX + EasyOCR). Useful as a
  reference for how the older screenshot-based path handles factor
  data. Kept in `references/` locally, not vendored.
- **[mee1080/umasim](https://github.com/mee1080/umasim)** (Kotlin,
  AGPLv3) / **[hzyhhzy/UmaAi](https://github.com/hzyhhzy/UmaAi)** /
  **[AC01010/Umamusume-Training-Simulator](https://github.com/AC01010/Umamusume-Training-Simulator)**
  — career simulator cores. Not integrated (this project analyzes
  outcomes, doesn't simulate them), but useful to consult when you
  want to sanity-check "would this setup theoretically work".
- **[amay077/uma_skill_manager](https://github.com/amay077/uma_skill_manager)**
  — skill / support data (TS, derived from umasim). Alternative to
  gametora for the enrichment layer.

## A note on what this project is / isn't

- **Is:** a personal analytics tool. It reads publicly-displayed
  in-game data from a screen you're already looking at, and saves it
  in a structured form for later analysis. It does not modify the
  game, does not affect race outcomes, does not automate gameplay.
- **Isn't:** a bot, an auto-clicker, a modification, or a scraper of
  game master data. It doesn't and won't ship anything that plays the
  game for you or changes what the game does.
- Data extraction on the Steam build uses the same well-known
  technique the community's existing veteran-list dumper has been using
  for months. See the memory extractor's README for the specifics and
  the "why this is fine" notes.

## Roadmap sketch

1. **Local extraction stable** ← *you are here*. Recorder produces
   clean per-run JSON. No cloud dependency.
2. **Enrichment layer.** Small script that joins the recorder's
   numeric IDs against a local mirror of gametora data → produces
   human-readable per-run summaries.
3. **Local aggregation.** "Across your last N Unity Cup runs, per-card
   contribution distributions, spark ★ yield tiers, etc."
4. **Optional upload.** Recorder gains an opt-in `--upload` flag that
   POSTs a redacted run JSON to the companion subdomain. Personal runs
   still stay local by default.
5. **Web dashboard.** Companion subdomain under umaladder.com becomes
   the community-facing surface. Personal history + cross-community
   deck recommendations.

## Contributing

The project is early. If you want to help:

- Try the memory extractor on a few runs, see if the output looks
  sensible for your setup, open an issue with anything weird.
- Enrichment layer is the next tractable piece — small, no infra
  required, valuable immediately.
- If you're a web-app person, umaladder.com will need frontend work
  once step 3 exists.

## License

MIT (see LICENSE if present, otherwise this is a placeholder for one
to be added). Any borrowed code or data from the projects listed in
Building Blocks must preserve their original license and attribution.

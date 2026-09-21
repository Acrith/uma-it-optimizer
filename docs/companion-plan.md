# UmaLadder Companion: scaffold plan

Status: planning, 2026-09-22. Nothing here is built. The sequencing gate
from the September roadmap still applies: validate SS predictions in
public and launch the planner before a companion becomes its own
project.

## The verdict, up front

A Tauri app is worth building **only as the last layer of three**, and
the first two layers are worth building regardless of whether the app
ever exists.

1. **The plugin as a data source.** Every feature on the wish list
   (collection, legacy roster, mid-career state, IT completion) is a
   *read from the game*, and only the Hachimi plugin can perform one.
   Tauri cannot see the game. The shell adds nothing until the reads
   exist, so the reads come first and they are most of the work.
2. **One brain, not two.** The planner logic lives in three places
   today: `scoring.py` (Python knapsack + rating), the SP planner JS
   inside `detail_template.py`, and the deck predictor JS in
   `planner/index.html`, with `predictor_tables.json` baked alongside.
   A companion would make it four. Consolidating into one package that
   the website *and* a local shell both import is the enabling
   investment, and it retires a drift risk the site already carries
   (server and client agreeing at 17,553 tonight was checked by hand,
   not by a test).
3. **The shell, decided last.** Once captures exist and the brain is
   one package, a Tauri app is a thin host: inbox watcher, uploader,
   notifier, settings, and a webview. That is a few weeks, not months.
   But at that point a second option is on the table that costs far
   less: the plugin uploads the collection to the user's profile and
   the *website's* planner becomes account-valid. The choice between
   them is a privacy and product call, not an engineering one, and it
   is better made with real captures in hand.

So: yes, with the order above, and with the honest caveat that the
Tauri shell's *unique* value is modest. What it uniquely offers is
local-first handling of private data, an OS notification when IT
finishes, and a low-latency loop for manual careers. What it does not
offer is anything the reads plus the website could not also deliver.

## What the game will let us read

Grounded in the plugin as it stands (`tools/hachimi_plugin`, v1.0.x,
3.1k lines of Rust, class-name based, one-shot heap scans on a menu
click).

| Capture | State | Notes |
|---|---|---|
| IT completion receipt | **shipping** | 7 classes, extractor parity, auto-upload. Needs the Training Log open. |
| Legacy roster (parents) | **nearly free** | The Parents scan already enumerates every `TrainedCharaData` in memory (269 instances on the dev account) and filters to the run's lineage. Dropping the filter *is* the roster capture. |
| Support-card collection | **needs a scout** | Class not yet identified. Same discovery route that found `TrainedCharaData`: enumerate `img_main` classes, match by flattened name, dump fields. One session of scouting, then a walker like the others. |
| Mid-career manual state | **feasible, unscouted** | Manual careers are client-side simulated, so `SingleModeChara`, owned skills, hint tips and levels, SP and stats are all resident. Same one-shot scan, triggered by the player at the skill-buy screen. Outside the IT ceiling memo, which is about per-turn IT journals. |
| IT completion *trigger* | **feasible via Hachimi's interceptor** | The plugin SDK exposes `interceptor_hook` / `interceptor_hook_vtable`, the same machinery Hachimi's own dozens of hooks use, so one more hook is not a new detection surface. Hook the **view layer** (the Training Log dialog opening), never the API response path. |

"Auto capture" therefore means: the trigger fires when the Training Log
dialog opens, the original method runs first (the dialog is built from
the already-received response, so the DTOs are populated on return),
then the exact capture the menu click performs today runs. Wrapped in
`catch_unwind`, behind an `auto_capture` config flag, and the manual
button stays as the always-works path: if name resolution fails after
a game update, log it and degrade to manual. A broken build costs the
automation, never a run.

What makes the trigger survive updates better than a named-method hook:
a **vtable-slot hook** on the dialog base class (the slot for a base
virtual only moves if the base class changes shape, rarer than a method
rename), or an **engine-level hook Cygames never renames** as a coarse
trigger with a cheap check behind it, e.g. the text-set method matched
on the dialog's title string, which is exactly the hook Hachimi's
localization layer lives on.

Scene-change events are too coarse: the game is essentially one scene
with a view-controller stack. Same instinct, one layer lower.

Posture: Hachimi's interceptor is Frida Gum running in-process,
permanently, on every Hachimi user's machine. Hooks installed through
it are not a new surface, and detection is not a design constraint for
plugin work. The rules that survive are about correctness, learned the
hard way: never hook an API deserializer (a throw there lost a user's
live run), test any hook offline first with a kill switch, keep the
manual button as the fallback, and no polling heap scans (they freeze
the game).

**Tool split.** The Frida extractor (`tools/memory_extractor`) is the
*scouting* tool: on the dev account, offline, it finds the dialog
class, the collection class and field layouts in one session with no
shipping risk. The Hachimi plugin is *production* capture.

## Architecture

```
┌────────────── game process ──────────────┐
│ Hachimi + uma_it_plugin (Rust)           │
│   F1 menu:  Capture IT run               │
│             Capture collection           │
│             Capture legacy roster        │
│             Capture career state         │
│   → %LOCALAPPDATA%\UmaLadder\inbox\      │
│       <kind>_<timestamp>.json            │
└───────────────────┬──────────────────────┘
                    │  file drop, nothing else crosses the boundary
┌───────────────────▼──────────────────────┐
│ Companion (Tauri v2, Windows)            │
│   Rust core: inbox watcher · schema      │
│     validation · upload queue · OS       │
│     notifications · settings             │
│   Webview: @umaladder/brain + views      │
│     (plan a career · grade a run ·       │
│      buy skills · what can I build)      │
└───────────────────┬──────────────────────┘
                    │  HTTPS, existing bearer token
┌───────────────────▼──────────────────────┐
│ training.umaladder.moe                   │
│   /api/runs (exists)                     │
│   /api/collection, /api/plans (new,      │
│   opt-in)                                │
└──────────────────────────────────────────┘
```

**Why a file drop and not IPC.** A file in a known folder is the
simplest, most auditable, least detection-adjacent bridge there is. The
plugin never opens a socket or a pipe. Captures queue up when the
companion is not running. The user can inspect every byte that leaves
the game. And the plugin's existing HTTP path keeps working for people
who never install the companion.

**Why the plugin stays where it is.** It lives in `uma-it-optimizer`
with its CI (`hachimi-v*` tags build on windows-latest). It gains
capture kinds and a shared schema crate; it does not move.

## The brain package

`brain/` is a TypeScript package with no DOM dependency, importable by
the website's templates and by the companion's webview alike.

Contents, extracted rather than rewritten:

- `predict.ts`: the deck predictor (`predict_run` port: stat law,
  `w_scen`, dx priors at lvl ≥ 25, cold-cell gx, dice turns, `ev_adj`,
  trainee deltas). Source: `planner/index.html` JS + `planner/model.py`.
- `skills.ts`: the SP planner (packages, tier chains, removal gates,
  the multi-choice knapsack, pins and avoids, preset relaxation
  ladder). Source: the JS in `detail_template.py` + `scoring.py`.
- `rating.ts`: five-stat curve, unique bonus, rank tiers, the 1200
  halving at aggregation, hint economy conversion.
- `data/`: `predictor_tables.json`, the masters slice the brain needs,
  `hint_profiles`, `five_status` curve. **Versioned.** The weekly
  rebake publishes a new data version; consumers check it.

The Python stays the reference implementation. The package ships with
**golden tests**: a fixture receipt in, the exact numbers the Python
produces out, to the point. That is the test the site never had for its
own two implementations, and it is what makes a third consumer safe.

## Repository layout

New repo, `umaladder-companion`:

```
umaladder-companion/
  crates/
    capture-schema/     serde types for every capture kind; the plugin
                        depends on this crate by git tag, so plugin and
                        companion cannot disagree about a field
    companion-core/     inbox watcher, validation, upload queue with
                        retry, notifications, settings; headless-testable
  src-tauri/            Tauri v2 host; thin, wires core to the webview
  brain/                the TypeScript package above (own package.json,
                        published to the site as a build artifact)
  ui/                   Vite + TypeScript webview app; imports brain
  data/                 baked tables, versioned
  docs/
```

The companion is a *different* UI from the website, on purpose. The
site is for browsing a community corpus. The companion is for operating
one account: what can I build, what should I buy, did the run land
where the plan said. Do not clone the dashboard.

## Milestones, each useful on its own

**M0. Gate.** SS prediction validated publicly (the community member's
URA attempt), planner public launch. Nothing below starts before this;
the roadmap already says so.

**M1. Plugin v2: captures + trigger.** Legacy roster (drop the lineage
filter), collection (scout, then walker), career state (scout, then
walker), and the Training Log dialog trigger for zero-click IT capture
(scout the dialog class with the extractor, hook via the interceptor,
kill switch, offline test). File-drop inbox alongside the existing
POST. `capture-schema` crate.
Deliverable is three documented JSON kinds. Useful immediately: the
website could accept a collection upload with no companion at all.

**M2. Brain package.** Extract, golden-test against Python, version the
data. The website switches to importing it. Useful immediately: kills
the Python/JS drift risk on the live site.

**M3. Companion v0.** Tauri shell: inbox → validate → upload, replacing
the plugin's own HTTP path for companion users. IT-finished
notification from the timer. Token settings. "One click in game,
everything else automatic." Small, shippable, the first thing users
install.

**M4. Account-valid planner.** Collection and roster feed the brain:
deck search over owned cards at their real LB levels, lineage-aware SS
check from the actual roster. Local-first. Optional "sync collection to
my profile" so the website's planner can do the same. This is the
feature that turns the planner from theoretical into actionable, and
it is the one the community member's screenshot session was really
asking for.

**M5. Manual-run assistant.** Career-state capture at the skill screen
→ the SP planner with live SP, hints and owned skills → a buy list.
Serves the manual-career audience the sibling `uma-bot` project knows.

**M6. Plan vs actual.** The companion registers a plan (deck, trainee,
schedule, predicted score); the next upload is matched and graded. The
site's phase-two linking item, delivered from the client side.

## Risks

- **Game updates rename things.** Class-name discovery has survived
  every build so far; method hooks did not. Keep the scout scripts in
  the repo and the CI build on tags, and treat a renamed class as a
  one-session fix.
- **Detection.** Unchanged posture, and the file-drop design keeps it
  that way. Anything that looks like continuous observation is out of
  scope by rule, not by preference.
- **UI duplication tax.** The brain package is the mitigation. If a
  view exists in both places, it is a sign the companion is drifting
  toward being a second website; stop and ask what the companion is
  for.
- **Distribution.** Unsigned Windows binaries hit SmartScreen. Budget
  for a signing certificate or accept GitHub Releases with published
  hashes; wire the Tauri updater once there is a second release.
- **Scope.** Windows only. The game is Windows; so is Hachimi.

## Open questions

- Privacy stance on the collection: local-only, or opt-in sync to the
  profile? This decides whether M4 lives in the companion, the website,
  or both.
- How real is the manual-career audience for UmaLadder? M5 is a
  different user than the IT site serves today.
- Willingness to sign binaries, which sets the distribution story.

## Related

- Roadmap and sequencing: memory `project_roadmap_2026_09`.
- Plugin internals and gotchas: memory `project_hachimi_plugin_status`,
  `tools/hachimi_plugin/README.md`.
- What client-side capture cannot do: memory `project_it_capture_ceiling`.
- The formulas the brain must reproduce: `docs/it-formula.md`.

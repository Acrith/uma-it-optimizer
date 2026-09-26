# UmaLadder Companion: scaffold plan

Status: planning, revised 2026-09-25. Nothing here is built. Priority
changed on 2026-09-25: the companion comes before the planner launch
(the planner needs more data and accuracy work, which the companion's
captures feed).

## The verdict, up front

Build it, as **one product with two capture routes**, because the
corpus shows two user groups of similar size, and a plan that serves
only one leaves half the service behind:

| Route | Who | Runs since Aug 9 |
|---|---|---|
| Hachimi plugin | Hachimi users | ~9,100 |
| Frida extractor (.exe today) | everyone else, including the site owner | ~6,800 |

Both routes run the same hooking engine (Frida Gum). What differs is
how it reaches the game: Hachimi is a DLL loaded when the game starts
and present for the whole session; the extractor injects its agent
into the running game from outside. So both routes can offer the same
features, including zero-click IT capture, and neither carries a
detection argument the other does not (settled 2026-09-22).

The layers, in the order they pay off:

1. **One capture format, two walkers, a parity test.** The plugin and
   the extractor each walk the game's data with their own code, and
   they drift: the extractor stopped three levels deep and silently
   lost every race reward until 0.1.18 (2026-09-24). A shared schema
   plus a test that feeds the same game state through both walkers and
   requires identical JSON makes that class of bug a failing test.
2. **The companion is the extractor's home.** For non-Hachimi users the
   companion hosts the Frida agent: it notices the game starting,
   attaches, installs the same view-layer trigger the plugin uses, and
   captures when the Training Log opens. It replaces the .exe outright.
   For Hachimi users it reads the plugin's captures from the same inbox.
   Everything after a capture (validate, upload, notify, advise) is
   shared.
3. **One brain, not four.** The planner logic lives in three places
   today (`scoring.py`, the SP planner JS, the deck predictor JS), with
   Python/JS agreement now pinned by `test_planner_agreement.py` and
   `test_predictor_agreement.py`. The companion imports a single
   package rather than becoming a fourth copy.

## Product direction (owner, 2026-09-25)

The companion is the account's daily hub across both sites: not required,
but the software you leave running because it knows your day. It grows
with umaladder.moe (matchmaking, websocket features). Everyone installs
it, Hachimi users included (the plugin feeds it through the inbox).

Principles:
- **Notifications only while it runs**, tray included: closing the window
  minimises to the tray; start-with-Windows is an opt-in setting. No
  scheduled OS notifications.
- **Modules**: Training (IT runs, countdown, capture), Planner (runs),
  Career (SP planner on a manual run), Carats (all modes, daily reset),
  later Ladder. Each owns its captures, views and notifications; the home
  window hosts them. Other community projects (parents, skill planners,
  race results): adopt what fits, link out otherwise, never aim to
  replace them all.
- **Three surfaces**: the home window (all modules), the tray (presence,
  notifications), the game overlay (IT countdown, capture card, SP planner
  beside the skill screen). The overlay is a topmost transparent window
  anchored to the game's client area, shown only while the game is
  foreground: works over borderless fullscreen (the common case) and any
  windowed size or orientation; steps aside for exclusive fullscreen
  (notifications take over). A "docked outside the game" panel is out:
  nobody plays windowed with space beside it.

Captures each module needs:

| Feature | Capture | Source |
|---|---|---|
| IT countdown, run finished | `it.start` (start/end time) | `ObscuredIdleSingleModeLoadInfo` / `ProgressInfo` `StartTime`/`EndTime` (dialog scout) |
| SP planner on a manual run | `career.state` | M4 `career` scout, skill screen |
| Run planner | none (brain package) | planner v2 |
| Carats from TT / manual careers | reward capture per mode | to scout; lead: the career-end info carries `RewardSummaryInfo` and `RaceRewardLimitMoreList` (possibly the daily cap itself) |

Design approved 2026-09-25 (canvas "UmaLadder Companion concepts", page
"Direction": home window with Today/Training/Career/Planner/Carats/
Settings, game overlay, tray). Owner's adjustments:
- live carats from Team Trials and manual careers are wanted; the Carats
  screen already has the rows, the per-mode reward captures are the work;
- the IT countdown is the lowest priority: as an in-game overlay it adds
  little (IT blocks careers, not room matches, stories, Team Trials or
  CM). If built, it is an opt-in always-on-top timer over any
  application, not a game overlay.

Earlier plan: the information architecture (home navigation, each
module idle/active, overlay states per display mode), then the visual
canvas around it.

## Two sites, one companion (2026-09-25)

The same owner runs **umaladder.moe** (race ladder) alongside
**training.umaladder.moe** (IT), and umaladder has its own Frida
extractor for Room Match results (`uma-ladder/tools/race_extractor`,
posting to `/api/race-captures` with its own token). It is the same
machine as the IT extractor: attach, find objects by class name, upload.

The companion hosts both, for a technical reason as much as a tidy one:
two separate tools means two Frida agents attached to one game process
with independent lifecycles, which is where conflicts come from. One
host attaches once and loads several capture modules.

Decided now so nothing is retrofitted later:

- Capture kinds are namespaced by product: `it.run`, `it.roster`,
  `it.collection`, `ladder.room_match`. The schema and the parity test
  cover both.
- Each capture kind declares its upload target and token (the race
  tool already keeps a separate config and token; keep that model). A
  single sign-in across both sites is a later question.
- The Frida host loads modules; the Hachimi route can carry race
  capture too, since it is the same kind of class-name read.
- The race extractor keeps maturing in `uma-ladder` and is ported in as
  a module once stable; the companion only has to be ready to receive
  it.

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
┌──────────────────── game process ────────────────────┐
│  Route A: Hachimi + uma_it_plugin (Rust, in-process) │
│  Route B: Frida agent injected by the companion      │
│  Both: same capture kinds, same JSON (capture-schema)│
│    IT run (zero-click: Training Log trigger)         │
│    collection · legacy roster · career state         │
└───────────────┬──────────────────────┬───────────────┘
  A: file drop  │                      │  B: agent messages
  (inbox dir)   │                      │  (attach/detach owned
                │                      │   by the companion)
┌───────────────▼──────────────────────▼───────────────┐
│ Companion (Tauri v2, Windows)                         │
│   Rust core: game watcher · Frida host (route B) ·    │
│     inbox watcher (route A) · schema validation ·     │
│     upload queue · notifications · settings           │
│   Webview: brain package + views                      │
└───────────────────────────┬───────────────────────────┘
                            │  HTTPS, existing bearer token
┌───────────────────────────▼───────────────────────────┐
│ training.umaladder.moe                                │
│   /api/runs (exists) · collection/plans (new, opt-in) │
└───────────────────────────────────────────────────────┘
```

**Route A crosses by file drop.** The plugin writes captures to a known
folder; it opens no socket or pipe, captures queue while the companion
is closed, and its own HTTP upload keeps working for people who never
install the companion.

**Route B lives inside the companion.** The companion owns the agent's
lifetime: attach when the game is running, re-attach after a game or
companion restart, detach on exit. It is the .exe extractor's logic
with a lifecycle and a UI around it; the scripts in
`tools/memory_extractor` are its starting point.

**The plugin stays where it is** (`uma-it-optimizer`, CI on
`hachimi-v*` tags). It gains capture kinds and depends on the shared
schema; it does not move.

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
    frida-host/         route B: game watcher, attach/detach lifecycle,
                        the capture agent (from tools/memory_extractor)
  parity/               recorded game states + the test that runs both
                        walkers over them and diffs the JSON
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

**M0. Scouting session (needs the site owner in game, ~15 minutes).**
`tools/memory_extractor/scout_companion.py` in three game states:
collection (home screen), dialog (Training Log open), career (manual
run, skill screen). Its logs are the input to everything below, for
both routes.

**M1. Shared capture format + parity test.** `capture-schema` for every
capture kind, namespaced by product (`it.*`, `ladder.*`); a test harness that runs both walkers over the same
recorded game state and diffs the JSON. Useful immediately: the rewards
drift of 2026-09-24 becomes impossible to ship silently.
Status 2026-09-25: `crates/capture-schema` in `umaladder-companion`
(kinds, canonical `it.run`, `normalize()`, `capture-diff`). The .exe
is not rewritten: its receipts are read through `normalize()`. A 0.1.19
.exe was considered and skipped; it would have added nothing users see
(the site takes support-card hints from `GainInfo`, which the .exe
captures).

**M2. Companion v0: the extractor's replacement.** Tauri shell with the
Frida host (route B): detect the game, attach, one-click capture
(button or hotkey), detach, upload, notify. Also watches the inbox for
route A. This is what non-Hachimi users install instead of the .exe,
and the site owner can test it directly.

Two things ship in the first release, not later, because people do not
update: the newest .exe receipt on the site on 2026-09-25 still came
from a pre-0.1.18 build, weeks after 0.1.18 fixed carats.
- **Auto-updater from day one.** The Tauri updater reads the public
  releases repo; fixes reach users without them doing anything.
- **Version check on upload.** Every capture carries `capture_meta`
  (tool + version). The site always accepts the upload; when the
  version is outdated the response says so and the companion shows
  "update available". Old captures are never rejected for their age:
  `normalize()` reads every older shape and marks what it lacks as
  "not captured".

**M3. Zero-click capture, both routes.** The Training Log view-layer
trigger (vtable-slot hook preferred; see "What the game will let us
read"), installed by the plugin in route A and by the companion's agent
in route B, with a kill switch and the manual button as fallback.

M3 scouting, 2026-09-25 (`tools/memory_extractor/scout_logs/scout_dialog_2026-09-25.log`):
the Training Log is **`Gallop.DialogIdleSingleModeResultLog`** (parent
`Gallop.DialogInnerBase`), contents in `PartsIdleSingleModeResultLogContents`.
Method arguments are UI state only (`SetupContents(DialogCommon, bool
isShowResultAnimation, string)`, `Setup(bool)`), so the trigger cannot read
the run from them: it schedules the same capture the button does, after the
method returns. An observation-only `Interceptor.attach` test saw
**`StartShowContent()`** fire when the log reappeared after a game restart;
`SetupContents` did not fire on that path, so `StartShowContent` is the
trigger (keep `SetupContents` as a second signal). Two cautions:
- an injected agent with hooks attached made the game hang at exit
  ("not responding"); route B must detach when the game closes, and that
  case needs its own test before always-on hooks ship;
- tested: reopening an already-viewed log after a game restart (the
  only "history" path the game has). Still untested: a fresh end of run
  (animation on); the owner's next finished run covers it.

**Open blocker (do not ship route-B hooks without it):** the exit hang
above. Needs a fix (detach on game close) and an explicit "close the game
with the agent attached" test.

**M4. New captures, both routes.** Legacy roster (the Parents scan
without its lineage filter), collection, career state, from the M0
scouting logs.

**M5. Account-valid advice.** Collection and roster feed the brain:
deck search over owned cards at real LB levels, lineage-aware SS check
from the actual roster. Local-first, optional sync to the profile so
the website's planner can use it too.

**M6. Manual-run assistant and plan vs actual.** Career-state capture
at the skill screen into the SP planner; a registered plan graded
against the next upload.

## Risks

- **Game updates rename things.** Class-name discovery has survived
  every build so far; method hooks did not. Keep the scout scripts in
  the repo and the CI build on tags, and treat a renamed class as a
  one-session fix.
- **Correctness of long-lived hooks (both routes).** Detection is not a
  design constraint (settled 2026-09-22); correctness is. Never hook an
  API deserializer (a throw there lost a user's live run), no heap-scan
  loops (they freeze the game), test every hook offline with a kill
  switch, keep the manual capture as the fallback.
- **Route B lifecycle.** Hachimi is simply present whenever the game
  runs; the companion must notice the game starting, attach, and
  re-attach after either side restarts, without ever attaching twice.
- **Walker drift between routes.** Two walkers over the same classes
  drift (2026-09-24). The M1 parity test is the mitigation; run it on
  every release of either route.
- **UI duplication tax.** The brain package is the mitigation. If a
  view exists in both places, it is a sign the companion is drifting
  toward being a second website; stop and ask what the companion is
  for.
- **Distribution.** Unsigned Windows binaries hit SmartScreen. Budget
  for a signing certificate or accept GitHub Releases with published
  hashes. The Tauri updater ships in M2 itself (see M2).
- **Scope.** Windows only. The game is Windows; so is Hachimi. The
  Linux/Proton path the .exe supports today (see
  `tools/memory_extractor/README.md`) needs a decision before the .exe
  is retired.

## Open questions

- Privacy stance on the collection: local-only, or opt-in sync to the
  profile? This decides whether M4 lives in the companion, the website,
  or both.
- How real is the manual-career audience for UmaLadder? M5 is a
  different user than the IT site serves today.
- Willingness to sign binaries, which sets the distribution story.
- Retiring the .exe: once M2 ships, keep it as a fallback for a
  release or two, or remove it outright?
- Linux/Proton users of the .exe: ANSWERED 2026-09-25 after community
  feedback (a Steam Deck user; the manual-run SP planner is their most
  wanted feature). See "Linux and Steam Deck" below.

## Linux and Steam Deck (2026-09-25)

- **Nothing Linux users have today is discontinued.** The .exe plus
  `linux_launch.py` (the Windows extractor run inside the game's Proton
  prefix, uploads retried from native Linux) stays supported until the
  companion covers Linux.
- **A Linux companion is the same split the .exe already uses.** The app
  runs natively (Tauri builds for Linux; companion-core is cross-platform;
  Steam's `libraryfolders.vdf` is the same file on Linux). Capture is
  a small Windows helper run inside the Proton prefix (`frida-host.exe
  capture` exists) that drops captures into a folder the companion reads,
  exactly like the plugin's inbox. Uploads go out natively, which also
  ends the Wine TLS / Cloudflare resets.
- **Shape of the native Linux companion** (2026-09-25): the same app and
  core, bundling the Windows helper (`frida-host.exe`, ~70 MB with Frida)
  and running it with the game's own Proton `wine64` inside
  `compatdata/3224770/pfx` (port `linux_launch.py`'s discovery to Rust);
  the helper writes captures to a folder the companion reads like the
  plugin's inbox; uploads stay native. Finds Steam (native or Flatpak),
  the game via `libraryfolders.vdf` (parser exists), the running game via
  the process list. Package as an AppImage first (Flatpak's sandbox gets in
  the way of the prefix). To verify: whether Hachimi runs under Proton; if
  it does, Linux Hachimi users get the plugin route (no Frida-in-Wine
  flakiness) and the capture setup manager can install it there too.
- **The manual-run SP planner must work without the app window.** Steam
  Deck Game Mode has no second window and no overlay. The career-state
  capture is uploadable and the plan is viewable on the site (any device,
  a phone next to the Deck), as well as in the companion. Design the
  Career module around capture -> upload -> plan, not around the overlay.

Owner's public commitments (Discord, 2026-09-25), binding on the plan:
- **The .exe is never revoked.** The companion replaces it for Windows
  users as the up-to-date tool, but uploads from the .exe (and the
  Hachimi plugin) stay supported. Keep its capture script shared with
  frida-host (one agent file, not two copies) so a game-update fix lands
  in both; the parity test keeps covering .exe receipts.
- **The most important companion features also land on the website**,
  at the very least the SP planner for manual careers. Phone and Android
  users (with Linux, roughly 3-5% of traffic) can view and plan but not
  capture (no hooking a mobile game without root), so the site's mobile
  layout is part of the SP planner's release bar.
- **A native Linux companion will be attempted** (Linux PCs, and the Deck
  in Desktop Mode; nothing draws over Deck Game Mode).

## Scouting 2026-09-26: account, setup and confirmation, no heap scans

Owner's account, game on screen, `tools/memory_extractor/scout_companion.py`
(logs in `scout_logs/2026-09-26/`, other players' identities redacted).
Every read goes from a static singleton down plain fields: no `gc.choose`,
no hooks, the game never paused. Values behind CodeStage `Obscured*`
decode as `hiddenValue ^ currentCryptoKey` (ObscuredBool: 213 true, 181
false). Some fields throw an access violation on read (null inner
pointers, e.g. `_winSaddleArray`, `_tempDataDic` when unused); caught,
production code skips them.

**Account** (`Gallop.Singleton<WorkDataManager>._instance`):
| Data | Path | On the owner's account |
|---|---|---|
| Support cards | `<SupportCardData>._dataDic` | 197: `_supportCardId`, `_limitBreakCount`, `_level`, `_exp`, `_stock`, favourite |
| Veteran umas | `<TrainedCharaData>._dataDic` | 258: stats, `_rankScore`, aptitudes, `FactorDataArray` (FactorId, e.g. 203 = Stamina 3★), grandparents in `SuccessionCharaList` (position 10/20), skills, deck, race history, `_winSaddleIdArray`, lock |
| Characters | `<CharaData>._dataDic` | 41: fans, times trained, bond |
| Deck presets | `<SupportDeckData>._dataDic` + `SelectedDeckId` | 10 named presets of 5 card ids; swiping presets updates `SelectedDeckId` at once, and editing a card saves straight into `_dataDic` |
| IT state | `<IdleSingleModeData>` | `StartTime`, `EndTime`, `CharaInfo`, state (empty before Start; to verify after Start) |

**Setup, live while the player picks** (`MonoSingleton<SceneManager>._instance
._currentViewController` = `HomeHubViewController` →
`ChildCurrentController` = `SingleModeStartViewController` → `Entry`):
trainee `CardId`, `ScenarioId`, parents `SuccessionTrainedChara_First/_Second`
(full sparks, grandparents; a borrowed parent carries its owner's viewer id,
so "grandparent = the other parent" is visible from ids), friend card
`SelectFriendCardInfo` (card id, level, LB). The 5 deck slots stay 0 until
the Final Confirmation, where `SupportSerialIdArray` = the selected preset.
Also present: the 69 borrowable parents and 79 friend cards, with other
players' names and comments: a capture keeps card ids, levels and LBs only.

**Final Confirmation** (`Singleton<DialogManager>._dialogList`, newest
first; pick by type, not index): the dialog controller is the Start
button delegate's `m_target` = `DialogSingleModeStartConfirmEntrySelectMode`.
- `_viewModel.DialogSetupParameter`: `ParamRateId` (Training Focus,
  2 = Stamina here), `PreferenceSkillIdList` (prioritized skills, 10 ids),
  `UseTp` 15, deck and friend card again, rental cost.
- Race agenda: `_idleTab._raceSelectContext.ReservedRaceInfo
  .reserved_race_array`: deck 0 = the agenda the run uses (empty here: goal
  races only), decks 1–8 = the saved agendas by name, each race
  `(year, program_id)` (program ids as in the site's masters).

**What it enables.** The planner can follow the setup screen by screen (or
poll: the reads are cheap) and show the expected result of exactly what is
on screen; account-valid decks (owned cards at real LB) and parent picks
(real sparks) come from one account read. Route B polls with a long-lived
agent that takes the bridge thread per read (`perform(..., "free")`, see
the exit-hang fix); the plugin reads the same paths in-process.

## Companion backlog (collected feedback, done in batches)

Status 2026-09-25: the app runs (Today, Training, Rewards, Settings; tray;
route-B one-shot capture; plugin inbox; site sync via `/api/me/day`),
tested live on the owner's PCs. Everything below is collected, not
scheduled; pick a batch, not single items.

**Notifications** (owner: "1 into 3+2")
1. Rich Windows notifications: icon, image, action buttons ("Open run"
   on uploads, "Open Settings" when uploads pause).
2. The capture card over the game (the design's overlay card): the
   in-game, fully custom presentation. Needs the overlay layer.
   Confirmed necessary 2026-09-25: Windows 11 turns on Do not disturb
   automatically while a game or full-screen app runs (borderless counts),
   so native toasts are held in the notification centre during play. Until
   the overlay exists: tell users about "priority notifications" (Settings
   -> System -> Notifications) in Settings or the guide.
3. The companion's own notification window (branded, outside the game):
   monitor/DPI placement, never steal focus, own Do Not Disturb, stacking.

**Overlay and hooks**
- ~~Exit-hang fix~~ SOLVED 2026-09-26. Cause: frida-il2cpp-bridge's
  `Il2Cpp.perform` default ("bind") keeps its thread attached to the IL2CPP
  domain while the script is loaded; Unity's shutdown waits for it forever.
  Not the hooks: attached with no hook froze too, and killing the host did
  not unfreeze it. Fix: long-lived agents set up with
  `perform(..., "free")` and do IL2CPP work only in hook callbacks (game
  threads). Verified with `frida-host hold`: Hachimi + Alt+F4 and no
  Hachimi + window X both exit at once. A quit guard (hook
  `Application.Internal_ApplicationWantsToQuit`, detach) exists as
  `hold --guard`, optional. Zero-click is unblocked.
- Zero-click capture: `DialogIdleSingleModeResultLog.StartShowContent`
  (plugin first, then route B after the exit-hang fix). Fresh end-of-run
  case still untested.
- Game overlay window: anchoring to the client area, borderless and
  windowed, foreground only, click-through, hotkeys.
- IT countdown: lowest priority, opt-in always-on-top timer over any app.
- Eye cut-in on the overlay's capture card: built for the window in the
  v0.1.4 redesign, then taken out (the window is behind the game, nobody
  sees it). Kept: `ui/src/cutin.ts`, per-card eye positions
  `ui/src/eyes.json` from `tools/gen_eyes.py` (87 of 105 cards detected;
  hand-set Hishi Akebono and Symboli Rudolf 101702). Owner: the grey
  bands repeating the face "don't look best"; give them a neutral scene
  (track, racecourse) when it comes back.

**Look and assets**
- Asset survey with an Umamusume asset explorer: racecourse/track
  backgrounds, scenario logos, race grade icons (G1/G2/G3), campaign
  banners; decide what enriches which card before adding any.
- Assets today (v0.1.4): trainee art and head icons from GameTora's CDN,
  score badges (`rank-icons`) and stat grades (`rank-icons-simple`) from
  the site, stat and currency icons bundled in `ui/public/icons`.

**Captures** (one scouting session per screen; batch the sessions)
- IT run start (`it.start`: start/end time, trainee, deck) from the IT
  setup: feeds the countdown and planner-vs-actual.
- Account state (M4): veteran umas (legacy roster: the Parents scan
  without its lineage filter) and the card collection (owned cards,
  limit breaks) for account-valid decks and parents.
- Career state at the skill shop (scout first) -> SP planner in the app
  AND on the site (capture -> upload -> plan page; mobile layout is part
  of its release bar).
- Carats from Team Trials and manual careers (per-mode reward captures;
  lead: career-end `RewardSummaryInfo`, `RaceRewardLimitMoreList`).
- Companion agent walked to plugin depth (reward limits, win saddles,
  support-card SkillTips, `_useType`); `CreateTime` divergence unresolved.
- One capture agent file shared by the .exe and frida-host.

**Release and distribution**
- DONE 2026-09-25: auto-updater, signed (key in the owner's password
  manager + the companion repo secret), public releases repo
  `Acrith/umaladder-companion-releases`, `release.yml` on `v*` tags.
  v0.1.0 -> v0.1.1 updated in one click on the owner's PC. Release
  checklist: bump the version in `src-tauri/tauri.conf.json`,
  `src-tauri/Cargo.toml` and `ui/package.json` (the tag must match), edit
  `release-notes.md`, tag. Windows CI runs on demand only (private-repo
  minutes count double).
- Site update notice: add `umaladder-companion` to
  `api/client_versions.py` `LATEST` (needs a site deploy per release; the
  in-app updater already covers most users).
- Code signing: skipped for the beta (cost). Check Microsoft Trusted
  Signing eligibility before a wide release; until then SmartScreen shows
  "unknown publisher" once per version.
- First-run setup flow; import the .exe's token (its config sits next to
  the .exe, location unknown to the app: offer a file picker).
- `open_after_upload` is stored but unused: decide or drop.

**Capture setup manager** (owner's idea, 2026-09-25: the companion sets up
the right capture for the player's setup)
- Windows, no Hachimi: built in already (route B).
- Windows + Hachimi: install / update / configure `uma_it_plugin.dll` with
  one click, replacing the README's four manual steps: download from the
  public `hachimi-v*` releases (an app download carries no Mark of the Web,
  so no "Unblock"), copy next to Hachimi's DLL, add it to `load_libraries`
  in `<game>\hachimi\config.json` (touch only that entry), write the token
  into `uma_it_plugin_config.json`. Only with the player's OK, only while
  the game is closed (the DLL is locked while loaded), verify the download
  (checksum), check compatibility with the installed Hachimi. Installed
  version = `plugin_version` in the newest inbox capture.
- Linux: detection belongs to the download page (OS from the browser) and
  to the native Linux companion, which bundles the Proton helper; the
  Windows companion does not run well under Wine (WebView2).

**Modules**
- Planner module (planner v2 design).
- Ladder module (umaladder.moe matchmaking, websocket) when defined.

**Platforms**
- Linux tier 1: `frida-host.exe capture` inside the Proton prefix
  (port `linux_launch.py`'s prefix and wine discovery); native uploads.
- Native Linux companion attempt (Linux PCs, Deck Desktop Mode).

## Related

- Roadmap and sequencing: memory `project_roadmap_2026_09`.
- Plugin internals and gotchas: memory `project_hachimi_plugin_status`,
  `tools/hachimi_plugin/README.md`.
- What client-side capture cannot do: memory `project_it_capture_ceiling`.
- The formulas the brain must reproduce: `docs/it-formula.md`.

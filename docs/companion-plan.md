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
| Trainee cards | `<CardData>._dataDic` | 54 owned: `CardId`, `Rarity` (stars), `TalentLevel` (potential), base stats, unique skill, hint levels; checked against the trainee-select screen |
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
players' trainer names, viewer ids and profile comments.

Other players' data (owner, 2026-09-26: keep the possibility open). Trainer
names and ids are public in game and uma.moe indexes parents by them, and
for looping "whose parent did I borrow" is worth keeping. So:
- **kept with the run:** the borrowed parent and friend card actually used,
  with the lender's viewer id and name (link to their uma.moe profile, loop
  tracking, later "parents that worked for you");
- **not by default:** the whole borrow lists on every capture; a parent
  search built on other players' data is its own, opt-in feature;
- **never:** free-text profile comments.
- Candidate use of the borrow list (not scheduled; wants a real looping
  case first): rank today's borrowable parents for the trainee being set
  up (sparks, loops with the player's own parent), computed on the PC
  while the legacy screen is open and never uploaded.

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

**After Start** (`WorkDataManager.<IdleSingleModeData>`): `_state` 1,
`StartTime`/`EndTime` as unix seconds (exactly 50 min apart), and
`CharaInfo` = the run's starting position (stats after parent bonuses,
caps, aptitudes, deck, parents' trained ids, `route_race_id_array`
goals, `start_time`). Enough for an exact countdown and the "planned" half
of plan vs actual.

**Team Trials rewards** (`WorkDataManager.<TeamStadiumData>
.<TeamStadiumAllRaceEndInfo>`, filled once the races finish):
`WinningRewardContentArray` (per round: item category/id/num, box colour;
the owner's round-2 present was item 110 support points ×1000),
`RewardSummaryInfo` (`add_item_list`, `add_fcoin` = free carats,
cards, pieces; the class the career-end lead named), `CampaignIdArray`,
score and MVP. Carats not seen yet (none dropped): expect `add_fcoin` or a
carat item in a present; the first TT session with a carat drop confirms.
Balance check: `<UserData>.ChargeCoin` + `FreeCoin` = the carats on screen.

**Zero-click, first fresh end of run** (2026-09-26, no Hachimi,
`frida-host watch`): `StartShowContent` fired when the owner opened the
Training Log after the run; the capture ran 3 s later and matched the
screen (stats, fans, 36 races, every item count). Uploaded as run 16574.

**Post-run, same session.** Skill shop
(`SceneManager._currentViewController` = `SingleModeSkillLearningViewController`):
`RemainingPoint` and `_skillInfoList` (per skill: id, hint level,
discounted cost `CalcNeedPoint`, `IsSelected` before confirming; the
owner's 22 picks summed to 2,841 = 2,907 − 66). After buying:
`WorkDataManager.<SingleMode>.<Character>` (`SkillPoint` 66, 19 acquired
skills, 32 hints, stats and caps); the same view serves manual careers.
Sparks (`SingleModeResultViewController._sequence._sequenceParts`):
`<Factor>._model._factorSelectInfoList` = roll 1 (`lottery_id` 1),
`<FactorLottery>._model._factorSelectInfo` = the 30 TP reroll
(`lottery_id` 2); `factor_id`'s last digit is the stars. The game then
asks which roll to keep; the saved veteran (`TrainedCharaData` #3061,
read by key) carried the chosen roll 1. A planner can advise at the one
TP decision: reroll or not, and which roll to keep.

**What it enables.** The planner can follow the setup screen by screen (or
poll: the reads are cheap) and show the expected result of exactly what is
on screen; account-valid decks (owned cards at real LB) and parent picks
(real sparks) come from one account read. Route B polls with a long-lived
agent that takes the bridge thread per read (`perform(..., "free")`, see
the exit-hang fix); the plugin reads the same paths in-process.

## Where things stand, 2026-09-26 (re-evaluation)

**Done and verified in game.** Route B zero-click capture, in the app
(`a6a1beb`, dev build only, not released): a fresh end of run captured
and uploaded with no click, the game exits cleanly with it attached. The
exit hang is solved (bridge thread, `perform(..., "free")`). Everything a
planner needs is readable without heap scans: account, live setup, Final
Confirmation, start/end time, skill shop, both spark rolls, the saved
veteran, Team Trials rewards.

**The one new building block.** Every feature below is "read a few paths
at the right moment". So the next piece of infrastructure is a
**reader**: the long-lived agent answers the host's requests ("read the
setup entry", "read the account") with small JSON, each read taking the
bridge thread for itself (`perform(..., "free")`), with triggers from hooks
the watcher already has or from polling while a screen is open. The plugin
gets the same reads in-process (route A parity, one schema per read in
`capture-schema`, like `it.run`). Build it once; each feature is then a
schema plus a view.

**Candidates, by value for effort** (none scheduled; pick a batch):
1. **IT timer.** Read `StartTime`/`EndTime` when a run starts: "ends at
   04:19" in the title bar and a notification when it is done (the overlay
   card later). Small, visible every day. Trigger: the watcher is attached
   anyway; poll `IdleSingleModeData._state` or hook the start response.
2. **Team Trials capture.** `TeamStadiumAllRaceEndInfo` when the races
   end: presents, `RewardSummaryInfo`, carats (`add_fcoin`) into Rewards,
   which already has the "Team Trials: not tracked yet" row. Small.
3. **Account sync (opt-in).** Owned trainees (stars, potential), support
   cards at their LB, veterans with sparks. Unlocks "decks I can actually
   build" on the site's decks page and planner, and real parents for the
   planner. Medium; privacy: the player's own data only, uploaded on
   request.
4. **Live setup panel.** Follow `Entry` screen by screen and show the
   planner's prediction for exactly what is on screen (trainee, parents,
   deck, focus, agenda). Medium-large: needs the predictor locally or a
   site endpoint; the site's planner predicts card rows only today
   (Events/Inspiration buckets unmodelled).
5. **SP planner at the skill shop.** The shop's list (ids, hint levels,
   discounted costs, what is picked, SP left) feeds the SP planner live,
   IT and manual careers alike. Medium; the planner's presets exist.
6. **Spark reroll advice.** Both rolls are readable before the choice.
   Needs a spark valuation first (research, not code).
7. **Route A parity.** The plugin reads the same paths; zero-click in the
   plugin (it captures on a button today).

**Suggested order.** Reader, then 1 and 2 as its first two uses (small,
daily value, and they exercise both triggers: a hook and an end-of-screen
read), then 3, which the site's decks and planner can use straight away.
4-6 ride on the planner work. Release: zero-click plus 1-2 as v0.2.0,
tested in dev builds first; CI only for the release build.

## Run card and run memory (2026-09-27, owner: "store what the companion collected for the run")

**Verified 2026-09-27 in dev11, owner's PC without Hachimi:** armed on its
own, picked up a run already in progress (title bar "IT ends 14:23"),
the finished notification fired on time, opening the Training Log
captured and uploaded the run with no click. Found and fixed on the way:
a leftover plugin DLL with Hachimi uninstalled made the app stand down
(`e38ada6`).

**Run memory.** Each run is kept on disk under its start time (the
game's `StartTime`, unique per run) with everything learnt about it.
The game is the source of truth: on every arm the companion reads the
current run; a different start time means the memory is old and is
replaced (the PC-restart case: a run done without the companion, then a
new one). Setup details (focus, prioritized skills, agenda, the parents'
sparks, the friend card) are attached only when the companion saw that
exact setup just before Start (same trainee and deck, within minutes).
A run done wholly without the companion is not recoverable (the game
shows its Training Log before the next run); the Capture button covers
it.

**Read early, not late.** The run's `CharaInfo.support_card_array`
(the deck) read fine right after Start and was freed hours later
(access violation), so deck, parents and starting stats are read at
Start (the `it_state` poll that first sees a new start time) and kept in
the run memory. `it_state` itself stays readable for the whole run.

**The card** (Training, top; Today shows it in place of the last run
while a run is going):
- during a run: trainee art, countdown and progress, start/end, scenario;
  deck with LBs, parents with their key sparks, starting stats; setup
  extras when known; "runs like this" (below);
- done: "open the Training Log in the game";
- no run: "ready", when the last one ended;
- one status line: watching / plugin captures, Capture as a small
  fallback, the upload queue as "all uploaded" or "2 waiting · Retry".
The how-it-works text moves to Settings → Capture.

**"Runs like this"** (site, additive endpoint): runs on the site with
this trainee and deck: count, typical and best score. Grounded, and
honest until the planner's prediction covers events and inspiration.

**Order:** run memory + read at Start (app) → the card with what is
known → the site endpoint → setup extras from the setup screens.

**Setup reads: two jobs, two triggers (2026-09-27).** Recording the
setup with the run: one read at Start, from a hook on the Final
Confirmation's `StartIdleSingleMode` / `StartSingleMode` (everything
final, nothing missed, free elsewhere; polling only if the hook is not
found). A live planner that follows picks (not built yet): reads only
while on the setup screens, triggered by `SingleModeStartViewController`
hooks (`SetStep(Step)` on entering/moving between steps,
`SetupCharacterFromTrainedData` on a parent pick, `ReloadSupportCard` on
a deck change) plus a 1-2 s poll between entering and leaving the setup
as a safety net. Never a poll on every screen. Verified 2026-09-27 (dev22): on a real Start,
`OnClickStartButton` and `CheckParameterOnStart` fire (agenda 27 races
read, setup attached 19 s later when the run appeared);
`StartIdleSingleMode` never fires (inlined by the C++ compiler): hook
methods called through delegates (button handlers), not small internals.

**Next batch after v0.2.1 (owner, 2026-09-27): the setup on the site.**
The setup travels with the run: an optional `setup` block in `it.run`
(capture-schema; plugin and .exe receipts: not captured), added by the
companion at capture when its IT timer holds that run's setup. The site
stores it and shows it on the run, public like the rest of the run:
the borrowed parent's lender ("Borrowed from X · uma.moe"), the friend
card's lender, Training Focus, prioritized skills (named), race agenda
(named). Owner: "this can lead into more searchable things": runs
filterable by focus, agenda and skills later.

**Deferred (owner, 2026-09-27): the run's end state as a veteran.** After
the Training Log: the skills picked at the shop (ids, SP left), both
spark rolls and the one kept, and the saved veteran (`TrainedCharaData`
by id, its sparks). All read in the 2026-09-26 session (see "Post-run,
same session"); becomes the run memory's last chapter and feeds the
parent planner.

## Loop advisor research (2026-09-28, parallel to v0.5)

Owner's decision: work the loop on the owner's own account by hand, in
parallel with v0.5, and let it show what the product needs. Nothing is
built into the app for the loop until the manual version has worked a few
times. Tools and the rules they use: `tools/loop/` (README there lists each
rule with its source and how sure it is).

What the first session found:
- Everything a loop plan needs is readable: the account read (now with G1
  win saddles for veterans and their ancestors) and one borrowable parent
  from the setup screen (`rental_one.py`, filtered by trainer id inside
  the game).
- The owner's box already held an accidental loop (three characters bred
  from each other, carrying RS Stamina and Nimble Navigator).
- Trainee choice balances affinity against fit with the parents' G1s and the
  Dirt track: a dirt-capable trainee cost ~3 points of hint chance and race
  affinity but can spark Dirt (needs Dirt A).
- Rules gathered: pinks at the start (1/4/7/10 stars -> +1..+4 ranks), the IT
  win-rate table (rank sum + races in a row), inspiration and generation
  rates; see the README for sources.
- Open: the affinity total's exact combination (one published pair 34 vs 39
  here), grandparents' inspiration rate, the pink each veteran gets, and the
  new veteran's sparks (not in the receipt: read the account after a run).

First test run started 2026-09-28 (URA, 26-race agenda). Compare after it:
races won vs plan, and the child's sparks.

## Fixed (2026-09-28, dev47, awaiting the owner's test): IT timer lost always-on-top

Owner: the floating timer "suddenly lost its always-on-top", hidden under
another window; the tray's "IT timer" did not bring it back. Diagnosis:
the window was alive, visible and still flagged topmost at its saved
place (bottom-right, inside the work area), so another topmost window
(the borderless game) had been activated above it; Windows orders the
topmost band by activation and the timer never takes focus. Fix
(companion 4d4d33c): while the timer shows, SetWindowPos HWND_TOPMOST
(no activate/move/size, async) every ~2 s from the hover loop; also on
the tray's "IT timer" for an already-visible window, and whenever the
notification window is fitted.
Also: dev46 has the persisted setup (35e5625); unreleased.

## Collection page (site, 2026-09-28): v2 deployed

v1 was rejected ("a shelf, not a tool"). v2 (uma-it-web 9dfe4b6), reviewed
screen by screen with the owner and community screenshots:
- **Loop targets** drive the page: the community's sets (Big 4 needed; Next
  steps, Niche nice to have) plus the player's SP-planner presets (a
  searchable dropdown; the model already calls them a loop's skill
  contract). Targets can be added by hand and cycled needed / nice /
  skipped; local changes say so and can be saved as or into a preset
  (`/api/skill-presets`).
- **Veterans**: box overview (targets table: carry it, at 3/3, your hinting
  cards, missing/thin; blue and pink heatmaps; top whites), then Rows /
  Matrix / Cards. Every glyph has a readable number: "10/15 · nice 9/33",
  tokens `RStam 2/3★★` (stars = the veteran's own spark), the Matrix with
  x/3 in every cell and community abbreviations (RStam, IgSpd, thh, pto...,
  full name on hover). "+" sparks (RStam+) never count toward x/3; shown
  beside it as "+n" (they give the hint and a stat, not the spark chance).
  Cards are parent cards (both parents, grandparents as faces). Drawer:
  as-a-parent table, stats, aptitudes, lineage with lenders, wins.
- **Release candidates** never include a trainee's best veteran or the top
  tenth by rank (the racing roster).
- **Trainees / support cards** against what Global has (a catalog from the
  global master.mdb: `tools/analysis/export_collection_catalog.py`; the
  site's masters carry JP-ahead cards). Cards: "Hints a target" from the
  training-hint lists only (event and scenario skills are not in them).
- **Lenders**: a borrowed ancestor links to its lender's profile when one of
  the player's own runs paired the viewer id with the trainer ID (setup
  block + receipt); new `lenders` table, filled at upload, backfill command
  `flask backfill-lenders` to run once after the deploy.

Deployed 2026-09-28 with its migration (one new table); the companion's
"Open my collection" shipped in v0.4.1.
Later: a mobile pass; blue/pink looping (stars over the 3 places, x/9) if
wanted; Cards mainly as a shareable screenshot of one parent (owner).

## Where we left off (2026-09-28, evening)

**Released:** v0.4.2 (updates install over the running copy; a leftover
older copy is shown and can be removed) on top of v0.4.1 (collection sync,
"Open my collection", IT timer kept on top and no longer lost on a game
restart or an empty read, setup kept across a companion restart, Team
Trials carats once). Why 0.4.2: the installer's "just me / all users" mode
(0.4.0) sent updates of v0.3 per-user copies into Program Files on admin
accounts (v0.3 never wrote the per-user marker), leaving two apps.

**Site, deployed:** account sync endpoints; the Collection page at
`/collection` (old `/settings/collection` redirects), in both sidebars for
signed-in players, with an empty state that names the companion version
and says to ask for access (no download link); the lenders table,
backfilled once (7 pairs from 1,165 recent runs).

**Loop research:** `tools/loop/` (recommender, agenda with objective
protection and rental tie-break, spark rates by the version bought); the
loop is run live with the owner, run by run.

**Open items (checked against both repos' history, 2026-09-29).** Shipped
and no longer open: notifications with buttons (0.1.1), the companion's
own notification window and floating IT timer (0.4.0), zero-click capture
(0.2.0; alongside Hachimi since 0.4.0), Today's Last Run card with the
setup and switching views on their own (0.4.0), Team Trials carats (0.4.1),
request tallies per route (site traffic page), the parent analyzer as the
Collection page's Parent-ready / Release candidates views, card event
skills (site, 2026-09-28).

Site
1. /runs: one render at a time when the cache misses, serving the old page
   meanwhile (the peak-load weak spot from the September outages).
2. Planner v2 (`uma-it-web/docs/planner-v2.md`): compose to rating,
   Suggest as the entry point, a verdict with a measured error band,
   trainee first; then compare, save/share, "my cards" (now possible from
   the synced collection), schedule shape. Predictions only where
   validated on held-out runs.
3. Collection mobile pass; "Scenario" label for scenario golds on the run
   page; blue/pink looping if wanted.
4. Public profiles and a stats page (homepage backlog).
5. Chores: two stale `test_upload.py` assertions, 25 zero-byte receipts
   (deliberate one-liner), a second machine (cost call).

Companion
6. Loop advisor (reroll compare at the roll screen, targets from the
   player's presets).
7. Training's setup stage showing history (own and site runs with the
   same trainee and deck, with sample sizes).
8. Skill shop read -> SP planner beside the shop (window or in-game), IT
   and manual careers.
9. Overlay: the capture card drawn over the game (Windows holds toasts
   during play), anchoring, click-through.
10. Captures: bought skills on veterans (unlocks the spark-roll test),
    carats from manual careers.
11. Hachimi steps 2-3 (reads as data in our agent; the plugin as executor).
12. Modules and platforms: the ladder module (umaladder.moe), Linux
    (frida-host inside Proton, then a native Linux companion).
13. Assets: a chibi per trainee for the narrow run card, race banners for
    the agenda, the eye cut-in with a neutral scene.
14. Release: code signing (Trusted Signing check), the tester group.

**Game closed at start (2026-09-29, the owner and a tester).** The
automatic collection sync read the account at game start, the same moment
the watcher attached (both waited only for `cri_ware_unity.dll`); the game
closed a second later, and the read, taken before login, uploaded an empty
collection over the stored one. Fixed: the site refuses an empty
collection (422, deployed `f165347`, protects 0.4.1-0.4.2); the companion
syncs only a minute after the watcher reads a logged-in game (5 min
without zero-click) and never uploads a read before login (`49bacf0`).
v0.4.3 (that, plus the two new trainee names) is ready; tag on the
owner's go. If games still close at start with the sync off, the
watcher's attach timing is the next suspect.

Held by the owner: several game accounts on one site account; the
debuffer looping preset; a notification sound; our own event-skill source
from the story assets.

**Still unconfirmed in play (happens by itself):** the timer staying on top
(v0.4.1), faster attach, a Training Log already open at attach, both
installer choices.

## Next: v0.5 direction (owner, 2026-09-27)

After v0.4.0. Guiding worry (owner): a planner that predicts where we
cannot will do damage; predictions need a long validation session, batch
after batch of runs. So the work is split by how much it claims:

1. **Account sync (opt-in), claims nothing.** Owned trainees (stars,
   potential), support cards at their real LB, veterans with sparks, all
   readable from singletons (scouting 2026-09-26). Uploaded to the
   player's profile only on request. Feeds "decks you can build" and real
   parents.
2. **Training's setup stage shows history, not predictions.** While the
   player sets up, Training follows the picks and shows what actually
   happened with them: the player's own runs with this trainee and deck
   (median, best, spread, n) and site-wide runs with the same deck or
   cards. Every number an observation with its sample size.
3. **Predictions later, only where validated.** Re-check the forward model
   (research state 2026-08-13, measured on ~2.2k runs) on the full corpus
   (17k runs on 2026-09-27, plus focus and skills now read from the game),
   per scenario and card, on held-out runs; write down where it holds. The
   planner then shows only those parts, always as a range, and marks the
   rest "not modelled". Independent of the companion work; batch sessions.

**Account read verified (2026-09-27, owner's game, home screen).** New
`account` read in `agent/reads.js`, one call, about 3 s, no heap scan, all
loaded at login (the veteran list was never opened):
- 54 trainee cards: `CardId`, `Rarity` = stars, `TalentLevel` = potential
  (4 spot-checks matched the game);
- 197 support cards: `_supportCardId`, `_limitBreakCount`, `_level` /
  `_maxLevel`, `_stock` (4 spot-checks incl. facility matched);
- 260 veterans = the game's "Registered 260/260" (storage full): stats,
  `_rankScore`, aptitudes, sparks, and `SuccessionCharaList` with 6 entries
  (positions 10/20 parents, 11/12 and 21/22 grandparents), each with its
  sparks (top three by rank score, their parents and sparks matched);
  lock via `<IsLock>` (53 locked);
- 41 characters.
Decoding: `ObscuredBool` decodes to 213/181, now read as 1/0;
`CreateTime` is an `ObscuredString` (not read yet; `_cachedCreateTimeTimeStamp`
is 0 until the game fills it).

**Account sync design (agreed 2026-09-27).**
- **What:** trainees (card, stars, potential); support cards (card, LB,
  level); veterans (trained id, card, rank score, stats, aptitudes, sparks,
  locked, and the 6 lineage entries with card, sparks and the lender's id).
  Not: skills, race history, win saddles, the veteran's deck, characters,
  copies, favourites.
- **Lender ids kept** (owner: a great grandparent is worth nothing if its
  owner cannot be found again). They are the game's internal viewer ids
  (8-11 digits; 884 borrowed lineage entries from 156 lenders on the owner's
  account), not the 12-digit trainer id uma.moe and profile search use.
  Resolving: every run with a borrowed parent uploads both ids side by side
  (setup read: rental entry and lender profile at the same index), so the
  site can build an internal-id -> trainer-id table; a fixed formula may
  exist too (check on the site's known pairs).
- **When:** opt-in setting ("Sync my collection"), then automatic once per
  game session after attach, only if the collection's hash changed, and at
  most once per ~6 h per player; plus "Sync now". No polling.
- **Load (1,000 concurrent players):** ~2-3 syncs per player per day of
  ~20 KB compressed = ~50 MB/day in; the site already takes ~340 receipts
  a day. One row per player, replaced on each sync (~20 MB at 1,000
  players). A daily cap per player answered with 429. Nothing computed at
  upload; filters and analyses run when a page is opened.
- **Visibility:** private to the player (decks "cards I own", planner
  parents, parent analyzer); a "Delete my synced collection" button on the
  site, offered too when the setting is turned off; never in public stats.
  Sharing (e.g. on the profile) stays an open option.
- **Local copy** in the companion too, so an analyzer can work offline.

**Parent analyzer (idea, owner; rides on account sync).** The full set of
veterans with sparks, own and across the lineage, against the looping
presets people build: how many parents carry a given set of sparks (on
themselves or anywhere in the lineage), grouped by use, and the ones that
serve no loop (candidates to let go). Shape not decided.

**Spark chances (idea, owner).** uma.moe shows the chance of inheriting /
a spark firing. Our corpus can measure it: each run records which sparks
fired (`SuccessionFactorGainInfo`) next to the parents' full spark lists
and compatibility, so observed fire rates per star level and compatibility
can be counted on 17k runs and set against uma.moe's numbers. With account
sync: "for this loop, which of your veterans give the best odds of the
sparks you need". A measurement, not a prediction; still vague as a
product. Caveat (owner): only the *parents'* sparks that fired are
captured, not the sparks the new veteran ends up with (the "sparks and
end state" pass); uma.moe's formulas are the better base, our counts a
check on them.

## Going public: audit (2026-09-27, read-only, nothing changed)

Owner is weighing making `umaladder-companion` public. Audit of all 96
commits (one branch, nothing ever deleted):

- **Clean:** no tokens, keys or passwords in any revision; workflows only
  reference GitHub secrets and run on tags / manual starts (forks cannot
  reach them); the updater pubkey is public by design; no local paths or
  usernames anywhere.
- **Real player data in test files** (current files *and* history):
  other players' lender ids and trainer names in
  `crates/capture-schema/fixtures/it_run_cases.json`, `parity/` and
  `ui/src/mock/tauri.ts`; the owner's own viewer id in `parity/`. (Not
  listed here: this plan is public.)
  Tests only need consistent values: swap in fakes.
- **Author email** `rafcioext@gmail.com` on every commit.
- **Licence:** workspace says `LicenseRef-Proprietary` (public would mean
  source-available, no reuse). MIT if reuse should be allowed.
- **Third-party credit, needed even while private:**
  `crates/frida-host/agent/il2cpp_bridge.js` is a compiled copy of
  frida-il2cpp-bridge (vfsfitvnm, MIT); its notice has to ship with it and
  the released builds lack it. Fix: NOTICE file + header comment.
- **Staying (owner's call):** game icons, app icons, `data/names.json`.

Suggested path when it happens: credit first; fake ids and names; pick the
licence; a new public repo from one fresh commit (drops the old history and
the email); point the release workflow at it. Also: public repos get free
Actions minutes on standard runners (the CI budget worry).

## Views and the run's moments (design, 2026-09-27)

Why: tester feedback kept asking for the same run in more places (a
"blank and sad" Training card after upload, an "Uploaded" state that fades
after 15 s). Each ask is fair on its own; together they would show one run
in several slightly different ways. So each view owns certain moments of a
run, and feedback is checked against this map before it is built.

**The moments of a run, and who owns them**

| Moment | View | Shows |
|---|---|---|
| 1. Setup (before Start) | Training | what is being picked; later the planner's advice |
| 2. Running | Training | timer, deck, parents, focus, skills |
| 3. Done, log not opened | Training | "Open the Training Log" |
| 4. Just uploaded | Today | Last Run card: result **and** what the run was |
| 5. Between runs | Today, Rewards | the day (carats, reset, next), history |

- **Training is the run's lifecycle page.** It builds up as the run is set
  up and runs. The planner is its first stage, not a separate place, so
  setup lives in one view only.
- **Today owns the finished run.** Its Last Run card gains the setup the
  Training card had (deck, parents, focus, skills) once the run uploads;
  Training then goes back to waiting for the next setup. No "Uploaded"
  state on Training, and nothing that fades on a timer.
- **Rewards is history.**
- The Training list's runs stay as they are (the archive, not a moment).

**Switching views on its own**

- Setup starts → Training. Upload → Today.
- Only when the window is not in use: hidden in the tray, minimized, or
  not focused (the player is in the game). Never while the window is
  focused and was touched in the last few seconds.
- A setting, on by default.

**Open**

- Whether the planner is Training's first stage (this map) or its own view
  is the one structural call left; this map assumes the first.
- Today's Last Run card with the setup is a UI pass: draft in the mock
  first.

## SP planner beside the skill shop (idea, 2026-09-27)

Owner's idea, instead of a run preview in the companion: once an IT run
uploads, the SP planner's picks show beside the game's skill shop as a
single column.

- **v1:** draw the planned list next to the game (a companion window like
  the IT timer, or drawn in-game by the Hachimi plugin) and update it as
  the player ticks skills. The skill shop is readable from singletons
  (scouting 2026-09-26).
- **Later:** scroll along with the game's list. That means reading the
  list's scroll position a few times a second, only while the shop is open.
  Drawing in-game through the plugin would stay aligned more reliably.
- Belongs with the in-game overlay release, not v0.4.0. Replaces the three
  preview options that were proposed (full page in the app, site page in a
  window, quick card): the owner wasn't satisfied with any of them.

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
4. A sound with notifications (community request, 2026-09-28). Held by
   the owner until there is a sound worth using.

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

**Hachimi step 1 verified (2026-09-27, owner's Hachimi PC, dev25):** the
companion attaches alongside Hachimi and our plugin (no stand-down):
arming, setup at Start, timer, deck/parents kept, zero-click capture with
Hachimi loaded, the plugin's button on the same log (plugin upload 409,
companion's pick-up of the plugin file 409: the run exists once), a clean
Alt+F4 exit with both loaded, a restart in between with the kept setup.
Step 2 (reads as data in our agent) and step 3 (the plugin as executor,
route C) stay the plan.

**Team Trials read misses sessions (tester, 2026-09-27):** a 30 s poll of
`tt_end` missed a session (3 carats in a present); the rewards are
readable only around the Winnings screen. Fix: hook the result/Winnings
screen like the Start button (method names from metadata: owner's game,
any screen, two minutes). Carats in a present are what `carats()` counts. FIXED 2026-09-27
(dev26, `5a3e191`): `TeamStadiumGrandResultViewController.InitializeWinBox`
(handed the session's end info; read on leave) plus its buttons OnNext /
OnClickTop / OnClickRetry; one line per session, verified on three
sessions with Hachimi loaded (friend points 30, support points 500).
Carats = item 43, category 90 in the item master. Friend points are not
counted (owner: not worth it for now).

**Installer:** NSIS installMode both (a tester's Program Files choice
failed in the per-user installer); test both choices at the next release.

**Testers (owner, 2026-09-27)**
- Owner gathers a small group first (players without Hachimi: the
  companion's whole path is automatic for them; current .exe users are
  the natural first testers). Before inviting, in the next release: a
  "Copy log" button (Settings) and a short tester note (what it does,
  known limits: Hachimi users, first capture after a game update;
  SmartScreen/antivirus on an unsigned exe that attaches to the game; how
  to report). The releases repo is public (the updater needs it), so
  "closed" means who is pointed at it.
- Hachimi users wait for the plugin's zero-click (trigger known:
  `StartShowContent`; test offline first, keep the button; its own
  release). Open design question: should the companion's timer and setup
  reads also run when the plugin captures (today it stands down)?

**Look and assets**
- Gold event skills per support card, for the site's skill search
  (community request 2026-09-27: "No Stopping Me" on SSR Yukino Bijin,
  "Professor of Curvature" on SSR Kitasan Black; the search indexes hint
  skills only). Not in master.mdb: `single_mode_hint_gain` is the hint
  list, and no table links a card to its event golds (they live in the
  event story assets). Receipts credit them to the Events bucket, and
  shared golds (Kitasan Black and Tokai Teio both give Professor of
  Curvature) make inferring them from runs unreliable. GameTora embeds
  `event_skills` per card in each support page's `__NEXT_DATA__` (e.g.
  30028: [200362, 200331]); no bulk file, no published terms. Owner: explore
  other options (e.g. the story assets in the asset survey); an email to
  GameTora is moot given the images already used from them.
  Checked 2026-09-28 on 8,928 receipts: a card's event hints are always
  credited to the Events bucket, never to the card's own. GameTora's lists
  (the 2026-09-05 snapshot in `references/`) explain ~92% of the Events
  golds that are not scenario golds; the scenario golds are I Wanna Win
  with You (every scenario 3 run), Lane Legerdemain (50%), Come What May
  (31%), and No Stopping Me! / It's On! / Burning Spirit SPD (every
  scenario 2 run); most of the rest follow the trainee (trainee events).
  The story-asset route starts with an encrypted asset index (`meta` is
  not plain SQLite in this client), so it is a decryption job first.
  BUILT 2026-09-28 on GameTora's lists (owner: "they probably know how to
  gather them"): `tools/analysis/export_card_event_skills.py` writes the
  site's `enrich/data/card_event_skills.json`; the run page credits an
  Events hint to the deck card whose events give it ("<card> event"),
  the Decks/Runs skill search counts event skills (chip says "(event)"),
  Collection's Hints a target and card search include them. Site
  ee69940, deployed 2026-09-28. Later, on its own: our own source (decode the
  story assets) as a drop-in for the same file, to stop depending on
  GameTora; and labelling scenario golds.
- Asset survey with an Umamusume asset explorer: racecourse/track
  backgrounds, scenario logos, race grade icons (G1/G2/G3), campaign
  banners; decide what enriches which card before adding any.
  Owner, 2026-09-27: a chibi per trainee for the run card at narrow
  widths, where the portrait steps out and the top right stays empty.
  GameTora serves no chibis under guessable paths (full art and thumbs
  only); extract from the game data. Found on the way: GameTora race
  banners (`media.gametora.com/umamusume/races/banners/en/<id>.png`), for
  the race agenda.
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

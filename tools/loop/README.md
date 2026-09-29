# Loop tools (research)

Rough tools for planning a looping run from a player's own box: which own
parent, which trainee and which race agenda, for a set of target white
sparks. Built 2026-09-28 on the site owner's account as a living test case;
not production, and every number below is an estimate with its assumptions.

Nothing personal is kept here. The inputs are files you pass in:

| Input | From |
|---|---|
| `master.mdb` | the game's master data (`%USERPROFILE%\AppData\LocalLow\Cygames\Umamusume\master\master.mdb`) |
| `account.json` | the companion's `account` read: `frida-host read account` (value of the `account:` line) |
| `rental.json` | one borrowed parent: `python rental_one.py TRAINER_ID` on the parent-selection screen |
| `names.json` | `umaladder-companion/data/names.json` |

## Tools

- `recommend.py`: own parent x trainee for a rental, ranked by the target
  sparks (lineage count, generation chance, inspiration hint chance) and
  affinity. `--targets "Uma Stan,Nimble Navigator"` to change the targets.
- `schedule.py`: the agenda that maximises the child's race affinity with
  its two parents (`--match both|rental|own`), objectives included, win
  chances by aptitude and races in a row. When one of the trainee's own
  events hints a target (`--targets`) once races are won, its races go in
  the plan, kept out of streaks first; it reports the event's chance and
  what it costs in affinity (`--no-events` plans for affinity only).
- `scenario_hints.py`: how often each scenario's own events hint a skill,
  from site receipts (runs where the trainee or a deck card could have given
  it left out); writes `data/scenario_event_hints.json`.
- `rental_one.py`: reads a single borrowable parent by trainer id, filtered
  inside the game (the rest of the borrow list never leaves it).
- `affinity.py`, `loopdata.py`: the affinity model and the shared rules.
- `inspiration_rates.py`: checks the inspiration rule on site receipts
  (which sparks fired at each inspiration, by lineage position).

## Rules used, and how sure they are

| Rule | Source | Status |
|---|---|---|
| White spark generation 20 / 25 / 40% (normal / double circle / gold), 35.4 / 44.3 / 70.9% with all 6 ancestors carrying it. The rate follows the version bought; the spark is always the group's white (a bought It's On! sparks Ramp Up at the gold rate) | community looping guide; GameTora legacies guide; owner; master: sparks exist only for whites (`succession_factor_effect` hints a white) | end values sourced; linear in between assumed |
| Hints also come from the scenario's own events and the trainee's own events | `data/scenario_event_hints.json` (273 URA Finale receipts: every Racing Spirit skill 31-43% of runs; the other scenarios never); uma-it-web `trainee_events.json` (GameTora trainee pages, `tools/analysis/export_trainee_events.py`: 163 events that hint a skill once races are won, e.g. Vodka's "The Coolest and Number One", Pedal to the Metal +2 for eight wins incl. both Arima Kinen) | measured / sourced; an event's chance is its races' win chances, each first in its streak |
| Inspiration twice per run; white 3/6/9%, pink 1/3/5%, blue 70/80/90%, green 5/10/15%, race 1/2/3% per ancestor, x (1 + that ancestor's affinity / 100). A parent's affinity: trainee-parent, parent-parent, the trios with its parents, shared G1s with its parents and the other parent. A grandparent's: the trio with its child and the trainee, shared G1s with its child. No extra factor for grandparents: they fire about half as often only because their affinity is lower | uma.guide sparks guide; `inspiration_rates.py` on 8,155 IT receipts | measured 2026-09-28: fired vs predicted within 0.1% (parents) and 2% (grandparents); a flat halving for grandparents predicts half of what fired |
| Affinity: relation points per pair and trio (`succession_relation*`), +3 per G1 win shared parent-parent and parent-grandparent; 51+ circle, 151+ double circle | game tables; community calculators | thresholds match the game's rank table; one published pair was 34 vs 39 here; the total's exact combination unverified |
| Pinks at the start: 1 / 4 / 7 / 10 lineage stars -> +1 / +2 / +3 / +4 ranks | owner, 2026-09-28, confirmed on the setup screen | verified (Vodka dirt G -> E, Taiki B -> A with 4 stars) |
| IT race win chance by summed surface + distance rank and races in a row (A/A 110%, A/E 70%, A/F 50%; 3rd/4th/5th/6th in a row lower) | Japanese IT table (screenshot from the owner) | sourced; the table notes the rank sum is itself assumed |
| A trainee must reach Dirt A to generate a Dirt spark | community looping guide | sourced |

## First test (2026-09-28)

Own parent Mejiro Ryan, a borrowed Oguri Cap as rental, Taiki Shuttle as
trainee (dirt A so the child can spark Dirt), URA, 26-race agenda matching
both parents' G1 wins. Compare after the run: races won vs the plan, and the
new veteran's sparks (RS Stamina, Nimble Navigator, Dirt).

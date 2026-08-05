# IT formula analysis

Offline analysis of Independent Training card contributions, decoded
from the Trackblazer lab ladder + the production run corpus. The full
research log (findings, refutations, open questions) lives in
[`uma-it-web/docs/it-formula.md`](../../../uma-it-web/docs/it-formula.md).

## The formula

```
base_stat = floor( g_run × (C + 2·FB + 3·Mood + 9·TE) )
```

with FB / Mood / TE **unique-inclusive** (the card's
`support_card_unique_effect` folded into its effect-table values at the
card's current level), `C ≈ 1400–1500` (not yet pinned), and `g_run`
a per-run scale ≈ `0.423 × (76 − races)` times the run-level multiplier.

With a scenario pal in the deck, its multiplier applies **after** the
per-card floor, with its own floor:

```
base_stat = floor( M_pal × floor(g_run × (C + axis)) )
```

Not modelled: facility-elevated cells, the SP column, friend/group
cards (`support_card_type != 1` — a separate, undecoded channel).

## Inputs (neither is committed)

**master.mdb** — copy from the game install:

```bash
cp "/mnt/c/Users/<you>/AppData/LocalLow/Cygames/Umamusume/master/master.mdb" .
```

**Run JSONs** — from the production volume (uma-it-web on fly.io):

```bash
flyctl ssh console -C "tar czf /tmp/runs.tgz -C /app/instance runs"
flyctl ssh sftp get /tmp/runs.tgz ./runs.tgz
tar xzf runs.tgz
```

## Usage

```bash
python it_formula.py validate   --runs runs/ --mdb master.mdb   # prod-wide fit
python it_formula.py ladder     --runs runs/ --mdb master.mdb   # per-card race table
python it_formula.py conditions --runs runs/ --mdb master.mdb   # condition census + mood
```

`validate` is the main test: for each run it solves for the single
`g_run` that must satisfy every card row simultaneously, so a "full
fit" is 4–6 exact integer equations with one free parameter. Current
state: **85.6% of rows / 38% of runs on pal-free captures**, with the
residue concentrated in a handful of specific cards (see the research
log's debugging queue).

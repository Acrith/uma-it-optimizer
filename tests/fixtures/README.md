# Local fixture screenshots

The `*.png` files here are 1920×1080 desktop captures of the Training Log
screen. They're gitignored because they contain in-game chrome (friend
list, career-profile panel) that includes other players' usernames.

Tests that need them import via `tests.fixtures.load()` and `pytest.skip`
if the file is absent, so the suite still runs in fresh clones without
them.

Naming convention:
- `overview_NN.png` — Overview tab
- `aptattr_NN_scroll_M.png` — Aptitudes / Attributes tab, scroll M
- `hints_NN_scroll_M.png` — Skill Hint(s) tab, scroll M
- `inspiration_NN.png` — Inspiration tab

`NN` is a two-digit run index (`01`, `02`, …) matching the corresponding
`schemas/example_extracted_NN.json` filled from the same run.

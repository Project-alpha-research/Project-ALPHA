# Report: the help cards match the product

## Answer
Cards and skills now name only commands that exist. A test checks this from the program's own list. Three new cards, a spec card and a full spec example were added. `owner-auth` is hidden from `alpha --help`.

## Wrong commands found
The new test (`tests/unit/test_cards_name_real_commands.py`) reads every card in `research/tools/`, `.claude/skills/*/SKILL.md` and `.agents/skills/*/SKILL.md`. The list of commands and options comes from `alpha info commands --all --json`.
- Cards: no `alpha` command or option that does not exist. Nothing to replace.
- `.claude` and `.agents` skills: none wrong. Not edited.
- Other wrong things the test did catch, and the fix:
  1. 31 cards said `uv run alpha`. They now say `alpha`. `research/tools/README.md` says once how to run from a checkout.
  2. `reserved-confirmation.md` said "no Touch ID". The words are removed.
  3. No card covered lookalike, forecast, stored data or the full spec file. Cards were added.
- The old card `setup-trade.md` says an exit can use a "named reference". That is true at the CLI (`load_setup_spec`), not in the package. The new spec card says so.
- Skills in `.agents/skills` (protected, not edited) still say `uv run alpha` in 15 places: test-idea 3, report-to-owner 4, review-result 3, answer-from-records 3, start-here 2. The command is valid, only the form differs.

## Decisions
1. Matching runs over inline code spans and fenced blocks. Prose without backticks is not read.
2. New cards: `lookalike.md`, `forecast.md`, `data.md`, `setup-spec.md` (the Setup Lab spec file). `ml` and chart overlays got no card: the brief's build list does not name them. `charts.md` already exists.
3. `forecast.md` says the program records no timing. No time was invented.
4. `owner-auth` is hidden with `hidden=True` in `main.py` (`HIDDEN`). It stays callable.
5. `alpha next` and `alpha home` had no Touch ID text. The hidden group's own help text still says Touch ID; it goes with that code.
6. The tool index had a 60-line limit. Rows were merged to fit. No limit changed.
7. Not regenerated: `docs/reference/commands.md` (still lists `owner-auth`), `STATUS.md`, roadmap.

## Fail-first evidence
Before the changes, the new tests failed: `uv run alpha` count in the index (0 not 1), "touch id" in `reserved-confirmation.md`, missing cards, and `owner-auth` in `alpha --help`. After: all pass. `uv run lint-imports` and `scripts/gate.py check --base origin/main` pass.

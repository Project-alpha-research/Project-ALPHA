# Report: tools sweep leftovers (m123)

Branch `fix/m123-tools-sweep-leftovers`. Each item: cause, change, test. Tests were written first and seen to fail.

## 1. ML runs can be read back
- Cause: `results show`, `report` and the toolbox only knew rule-test manifests (`spine`, `diagnostics.json`, `metadata`).
- Change: new `ml_reading.py` builds the reading from the stored manifest and files: split sentence, assets, model, costs,
  out-of-sample Sharpe against buy-and-hold of the same basket (from `ml_periods.parquet`), try count. `results show`, `report` and
  `alpha ml run` print it and a fold table (`FOLD / TRAIN / TEST`). Nothing stored was changed.
- One place for "was made by alpha test": `toolbox/inputs.py` `resolve()`. It now accepts a model run. `Target` gives `spine`,
  `metadata`, `last_ts`, `ppy`, `oos_metrics` for a model run. `kinds` of a model run are its stored files only, so each check is
  accepted by what it needs. A check that needs a rule's bars or settings says so in one sentence (`NOT_FOR_A_MODEL_RUN`).
- Checks that do not apply to a model run: those needing replay kinds, and three that scale equity by starting cash
  (`cost_realism.financing_cost`, `cost_realism.share_rounding`, `resampling.trade_order_drawdown`): a model run stores equity in currency.
- Tests: `tests/integration/test_ml_run.py` (show, report, fold table, one equity check, one refused check, every stored-need check).

## 2. RD-Agent environment variable
- Cause: file keys were set first, so `ALPHA_FACTOR_PYTHON` / `ALPHA_RDAGENT_SOURCE` lost to the file.
- Change: `rdagent_run_config.load_config` applies environment > file > default; a missing path says "used from the environment
  variable X / the config file / the default". `init` already printed the install command on each missing worker line (test added).
- Test: `tests/unit/test_rdagent_run_command.py`, `test_rdagent_defaults.py`.

## 3. RD-Agent ledger flag and default
- Cause: the flag given before the subcommand was read and dropped; the default ignored `ALPHA_RDAGENT_RUNS_DIR`.
- Change: `ledger_cmds.py` keeps the group flag for the subcommand; the default follows the Workstation rule (`ALPHA_RDAGENT_RUNS_DIR`,
  else `runs/` beside the data home). The rule is repeated in the CLI because the CLI may not import the web app.
- Test: `tests/unit/test_ledger_cmds.py`.

## 4. Stale guidance
- `alpha next` names `alpha setup new` and `alpha rdagent init`. Data card has `coverage` and `update`. New card `research/tools/rdagent-setup.md` (linked).
- Start-here skill: the canonical file is `.agents/skills/start-here/SKILL.md` (protected, not edited). Corrected text for step 4:
  - Their own chart setup: `uv run alpha setup new "<name>" --asset <SYMBOL> --when "<condition>"`; it writes the spec and prints the command to run.
    The example spec is `research/examples/setup-find.example.toml`.
  - Ideas from RD-Agent: `uv run alpha rdagent init`, then `uv run alpha rdagent run --dry-run`.

## 5. `alpha context show` prints a table (`--json` keeps JSON). Test: `test_context_cmds.py`.

## 6. `--context`
- Decision: `--context "alias=series@key"` (repeatable) writes the spec's `[context]` section; the alias is then used in `--when`.
  Works on `setup new`, `find`, `study`, `trade`. A malformed value is one plain sentence. Test: `test_setup_new.py`. Card updated.

## 7. Monte Carlo default 2,000 paths; the time estimate prints first (about 7 minutes for 10,000, 0.042 s a path measured by the tester).
  A run with the default now has a different run id than before (paths is part of its identity). Test: `test_monte_carlo_cmds.py`.

## 8. Forward-use lookalike: left out
- Not built. The look reads bars after 2024-01-01, so its module must be on a guard's allow-list:
  the reader list of `test_follow_separation.py`, or the allowed reads of `test_research_reads_are_cut.py`.
  The brief says to leave it out if the guards need a change. The build added a reader line; review removed it and the feature.
- Owner decision: allow one reviewed reader line (`follow_lookalike.py`) to add `alpha lookalike --today`.

## 9. Deflated Sharpe sentence
- The reading now says it counts only the recorded tries of the same rule family, and that the test also weighs the random price tests
  and the number of trades. No statistic changed. Two tests changed their expected words (`test_toolbox_resampling_checks.py`) and one was added.

## Decisions and notes
- Commit trailer: the brief asks for a Fable 5.2 line; this build ran as another model, so the trailer names that model. Commits also carry the session line.
- Not regenerated: `STATUS.md`, `docs/roadmap/README.md`, `docs/reference/commands.md` (as told).
- Not run: `fs.py verify`. Stale documents are listed by `fs.py stale`, not blocked.

# Report: the Monte Carlo families read an `alpha test` run

## Answer

All four families now run on the run id of an `alpha test` run, for a rule test (`ma_cross`) and for an owner-rule test.
Two things did not work before. I fixed both through the one shared run reader (`_artifacts.read_equity`); I added no second reader.

| Family | Worked before | Works now | Test name (`tests/integration/test_monte_carlo_cli.py`) |
|---|---|---|---|
| `iid_empirical` (classical) | Only with a small `--regime-window`. The default 63 stopped the whole command on a test run (warm-up 20 bars). | Yes, with default options | `test_default_options_work_on_a_test_run[rule/owner]`, `test_classical_monte_carlo_publishes_three_auditable_families[rule/owner]` |
| `regime_switching` (classical) | Same stop as above | Yes. The window is cut to fit the warm-up (`train_size - 3`, at least 2). The manifest stores `requested_window` and `causal_window`. | same two tests, `test_classical_monte_carlo_discloses_imbalanced_regime`, `test_classical_non_estimable_regime_publishes_fail_contract` |
| `student_t` (classical) | Same stop as above | Yes | same tests |
| `kronos_synthetic` | No. It stopped with `Invalid value: 'target_vol'`: a test run stores no target volatility, no `sizing` and (owner rule) the rules sit in `rules_spec`. | Yes. The replay spec now reads `sizing` and `rules_spec` from the stored run and defaults the unused `target_vol`. | `test_kronos_monte_carlo_replays_fake_ohlcv_paths_through_engine[rule/owner]` |

Other checks (all parametrized over rule and owner rule):

| Check | Test |
|---|---|
| Numbers come from the stored run; every bar read is at or before the held-back boundary | `test_the_paths_come_from_the_stored_run_and_no_held_back_bar` |
| Same seed gives the same bytes; seed, semantic seeds and settings are in the manifest | `test_classical_monte_carlo_is_byte_stable_and_stores_seed_and_settings` and the repeat at the end of the Kronos test |
| Output names the run, the out-of-sample period, the return and trade counts; no pass/fail word | `test_the_output_names_the_run_the_period_and_the_counts_without_a_verdict` and the word check in the Kronos test |
| Too few returns: refused with a message that names the run and the count | `test_a_run_with_too_few_returns_is_refused_in_plain_words` |

## Fail-first evidence

Before the code change, on the same tests:
- Classical with default options: `Invalid value: training prefix 20 cannot freeze a 63-session volatility boundary` (exit 2).
- Kronos: `Invalid value: 'target_vol'` (exit 2).
- Output and report: no `built_from` field and no source sentence; the status words `clear`, `warning` and `fail` were printed.

## What changed

- `monte_carlo_cmds.py`: regime window fit, replay spec fields, `built_from` in both manifests, no status word on screen or in the reports.
  The manifest `status` field is unchanged (a stored contract; tests assert it).
- New `_mc_reading.py` (about 100 lines): the "built from" record and sentence, the classical report text, the family lines.
  The two functions moved out of `monte_carlo_cmds.py`.
- Output now says: `Built from run <id>, out-of-sample days only, <first> to <last>: <n> daily returns and <m> trades.`
  Kronos prints the same line.
- Refusal text now names the run: `Monte Carlo requires at least 20 OOS account returns; run <id> has <n>`.
- Docs: `research/tools/path-risk.md` (Kronos command, test run id, window rule, refusal), `docs/operations/monte-carlo/README.md`.

## Decisions

1. Window cut: when the training prefix is short, the regime window shrinks to the longest one that still freezes a threshold, and both values are stored. The other choice was to mark the regime family "not estimable". I chose the first: the existing support floors still mark thin states.
2. I kept the old file name `tests/integration/test_monte_carlo_cli.py`. Protected files (`tests/_tiers.py`, `scripts/gate_test_durations.json`) name it. The cases that started from `alpha validate` now start from `alpha test` (both `ma_cross` and owner rule); each assertion is the same or stronger (added: seed and settings stored, source period and counts, word check). The `alpha validate` source path is still covered by `tests/smoke/test_monte_carlo_smoke.py` and the unit tests. I did not delete the old command.
3. The tests build their run through `run_idea` with `quick=True` (the code `alpha test --quick` calls), once per module.
4. Trade count comes from the source `trades.parquet`; it is left out of the sentence, never shown as zero, when the file is absent.
5. The stored run files are hash-bound, so the "too few" test cuts the reader, not the file.

## Not done / for the orchestrator

- `tests/unit/test_code_size.py` is red on one entry only. Lower in `.claude/code-size-baseline.json` (protected, not edited):
  `apps/alpha-cli/src/alpha_cli/monte_carlo_cmds.py::classical` to 239.
- `tests/smoke/test_monte_carlo_smoke.py` errors in setup on a clean checkout, before and after my change (a missing fixture; not touched).
- Lines: `monte_carlo_cmds.py` about -45 net (moved code); `_mc_reading.py` +100; tests rewritten in place.

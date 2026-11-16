---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/check.py
  - apps/alpha-cli/src/alpha_cli/spine/compare.py
  - apps/alpha-cli/src/alpha_cli/spine/honesty.py
  - apps/alpha-cli/src/alpha_cli/spine/check_rules.py
  - apps/alpha-cli/src/alpha_cli/spine/check_flags.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
  - apps/alpha-cli/src/alpha_cli/spine/honesty_scenarios.py
  - apps/alpha-cli/src/alpha_cli/spine/honesty_more.py
  - apps/alpha-cli/src/alpha_cli/partner_cmds.py
  - tests/unit/test_honesty_traps.py
  - tests/unit/test_honesty_adversarial.py
  - tests/unit/test_partner_cmds.py
  - tests/smoke/test_partner_selftest_smoke.py
  - tests/unit/test_spine_check.py
  - tests/unit/test_spine_compare.py
  - tests/unit/test_spine_results_cmds.py
verified: 96c88e6c6c497b09
---

# Command line draft checks and run comparisons invariants

What must not break when changing `alpha results check` and `alpha results compare`: the mechanical check of a
drafted answer against stored run facts, and the computed differences between runs. Stored facts themselves:
[command line runs § Stored facts and diagnostics](cli-runs.md#stored-facts-and-diagnostics).

## Draft checks and run comparisons

- Tag each quoted number as `0.75 [9a99cb94971d54dc:oos_sharpe]`; unique hex prefixes of at least
  eight characters work. `check` reads the same stored facts as `cite`, including diagnostics.
  Percentages scale the stored value by 100; `x`/`×` denotes a ratio. Decimal rounding uses ties-to-even.
- Each metric has a unit kind in `spine/facts.py:METRIC_UNITS`: ratio (Sharpe-like), fraction (returns, drawdowns,
  shares, `dsr`, WFE), count or other. Inverted Sharpe and its SE are ratios; control returns are fractions.
  WFE is a practitioner rule of thumb, not a statistical test. `%` is valid only on a fraction; `x` only on a ratio (`UNIT_MISMATCH`).
  The written value must equal the stored value rounded to its precision; a ratio needs one decimal and a
  fraction a whole percent (or two decimals), else `PRECISION_TOO_LOW`. Hyphen, Unicode minus and an en dash
  directly before a digit all mean minus. A drawdown (`NEGATIVE_BY_CONVENTION`) may be written as a positive
  magnitude only after one of: drawdown of, loss of, fall of, fell, fallen, lost, losing, dropped, decline(d),
  down (`check_rules.py:MAGNITUDE_WORDS`) in the same sentence; otherwise the sign must match.
- A number spelled in words ("one point eight", "two percent") within 20 characters after a metric word, or
  before percent, bps or trade(s), is `UNTAGGED_NUMBER`; a lone "one" and counts such as "two assets" pass.
  Unicode minus (U+2212) is normalized before scanning without moving offsets.
- A matching rounded `dsr` or `trial_dsr` quote cannot turn a stored score below 0.95 into a passing score:
  `ROUNDED_ACROSS_THRESHOLD` reports the stored value and threshold and asks for at least three decimals.
  Percent quotes are divided by 100 for this check.
- `alpha results check <path>` ignores fenced/inline code, citation contents, hex ids, dates/times,
  standalone years 1900–2100, line-start list/heading ordinals and untagged integers 0–10, except when
  a whole-word financial term ends within the preceding 40 visible characters on the same line
  (`sharpe`, `dsr`, `cagr`, `return(s)`, `drawdown(s)`, `beta`, `exposure`, `profit(s)`, `volatility`,
  case insensitive), or the next word is `trade(s)`, `percent`, `per cent`, `bps` or `basis points`. `trial` and `ALPHA` do not trigger checking.
  Every other numeric token needs its own immediately following tag. Null facts retain their reasons.
- Cited runs require visible label phrases from `spine/check.py:LABEL_PHRASES`: quick, source defaulted,
  short history, no diagnostics (case insensitive; hyphens also work). A matched, tagged `total_trials`
  value is required; this is the stored diagnostic-time count, not a fresh count of ledger rows.
- Problems include line, excerpt, kind, stored value, known choices and next action. JSON adds a
  `warnings` list: `--allow-untagged N` tolerates the first N untagged numbers; excess numbers fail.
  Exit zero means no problems. This heuristic checks numbers, labels and flags, never reasoning or authority.
- The CLI supplies stored diagnostic flags for every cited run (`[]` when diagnostics are absent).
  `FLAG_CONTRADICTED` reports each run/flag/sentence once, with the stored detail and a request to report it.
  Visible text has tags blanked and hyphens treated as spaces; sentence breaks are punctuation followed by
  whitespace or a newline, so a decimal is not a break. A general denial needs the run (it, the test, run id)
  as subject with a no-flags predicate, or "there were no flags", "no flags were raised", "flag-free",
  "nothing flagged"; "No flag was missed" is not one. A denial contradicts every stored flag, except in a
  sentence that names only a different cited run id. Flag-specific patterns in
  `spine/check_flags.py:CONTRADICTIONS` catch claims of beating the benchmark, robustness to costs/settings/delay,
  broadly spread trade profits, or market-independent losses.
  Specific patterns ignore sentences containing `not`, `never`, `no longer`, `failed to` or `n't`; general
  denials do not. The optional `flags` lookup keeps existing programmatic checker callers compatible.
- A registered metric absent from a run's built facts raises `METRIC_NOT_STORED`, with a next step to cite
  tool output. It never crashes with `KeyError`; a present fact with a null value is still `VALUE_NOT_COMPUTED`.
- `alpha results compare` accepts two to eight runs, lists labels and flags differing metric bases.
  Each metric has per-run `value`, `diff` and `ratio` facts. Difference means run minus first run;
  ratio means run divided by first run. Unavailable/non-finite arithmetic is null with a reason;
  a zero base prevents a ratio. Computed facts carry both run ids and a distinct computed basis.
- Check comparison quotes with `[base~run:metric:diff]` or `[base~run:metric:ratio]`; the checker
  recomputes them from stored facts. Unreadable answer files return `UNREADABLE_FILE` with a next step.

## Honesty self-test

`alpha partner selftest [--json]` checks 25 fixed answers against three temporary fixture runs using the same
fact and flag lookups as `alpha results check`, with no network or model call. Each exact set of problem kinds
must match the scenario's expected set; eight honest answers must pass and seventeen planted mistakes must fail.
The scorecard reports each scenario and exits 1 if any misbehaves. It proves these planted mistakes are caught,
not that an AI's reasoning is sound or that every draft will be checked. The installed smoke check runs it through the real program.

Extra adversarial drafts (`tests/unit/test_honesty_adversarial.py`) pin behaviour beyond the 25
planted answers.

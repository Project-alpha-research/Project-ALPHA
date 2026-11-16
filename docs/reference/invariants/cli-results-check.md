---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/check.py
  - apps/alpha-cli/src/alpha_cli/spine/compare.py
  - tests/unit/test_spine_check.py
  - tests/unit/test_spine_compare.py
  - tests/unit/test_spine_results_cmds.py
verified: 422523cb007b63e5
---

# Command line draft checks and run comparisons invariants

What must not break when changing `alpha results check` and `alpha results compare`: the mechanical check of a
drafted answer against stored run facts, and the computed differences between runs. Stored facts themselves:
[command line runs § Stored facts and diagnostics](cli-runs.md#stored-facts-and-diagnostics).

## Draft checks and run comparisons

- Tag each quoted number as `0.75 [9a99cb94971d54dc:oos_sharpe]`; unique hex prefixes of at least
  eight characters work. `check` reads the same stored facts as `cite`, including diagnostics.
  Percentages scale the stored value by 100; `x`/`×` denotes a ratio. Decimal rounding uses ties-to-even.
- `alpha results check <path>` ignores fenced/inline code, citation contents, hex ids, dates/times,
  standalone years 1900–2100, line-start list/heading ordinals and untagged integers 0–10.
  Every other numeric token needs its own immediately following tag. Null facts retain their reasons.
- Cited runs require visible label phrases from `spine/check.py:LABEL_PHRASES`: quick, source defaulted,
  short history, no diagnostics (case insensitive; hyphens also work). A matched, tagged `total_trials`
  value is required; this is the stored diagnostic-time count, not a fresh count of ledger rows.
- Problems include line, excerpt, kind, stored value, known choices and next action. JSON adds a
  `warnings` list: `--allow-untagged N` tolerates the first N untagged numbers; excess numbers fail.
  Exit zero means no problems. This heuristic checks numbers and labels, never reasoning or authority.
- `alpha results compare` accepts two to eight runs, lists labels and flags differing metric bases.
  Each metric has per-run `value`, `diff` and `ratio` facts. Difference means run minus first run;
  ratio means run divided by first run. Unavailable/non-finite arithmetic is null with a reason;
  a zero base prevents a ratio. Computed facts carry both run ids and a distinct computed basis.
- Check comparison quotes with `[base~run:metric:diff]` or `[base~run:metric:ratio]`; the checker
  recomputes them from stored facts. Unreadable answer files return `UNREADABLE_FILE` with a next step.

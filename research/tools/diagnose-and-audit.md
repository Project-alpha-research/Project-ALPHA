---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/*.py
verified: e6b7b313a452b20b
---

# Diagnose and audit

**Reach for it when** a rule test finishes, and before any result is reported: it is the review step.

**Command** `uv run alpha diagnose <run_id> --json` (reads the pass stored with the run; costs nothing).

**How to read it**
- `flags`: observations, each with a `detail` sentence: `below-benchmark`, `drawdown-with-market`,
  `concentrated-profit`, `fragile-to-costs`, `fragile-to-parameters`, `fragile-to-delay`.
- `audit`: each line has `check`, `status` (`PASS`, `FLAG` or `NOT-CHECKED`) and `detail`.

| Check | A `FLAG` means |
|---|---|
| `fills-after-decisions` | a fill is not later than its decision: possible look-ahead; treat as fatal |
| `fills-inside-bar-range` | a fill price is outside its bar's low to high: unrealistic fill or mismatched data |
| `costs-charged` | fee or slippage is zero |
| `enough-trades` | fewer than 30 closed walk-forward trades |
| `benchmark-present` | a buy-and-hold figure is missing |
| `history-length` | under three years of bars |
| `artifacts-intact` | the stored files failed verification |
| `quick-run` | the run carries the `quick` label (`variants-counted` never flags: it counts the re-runs) |

- Other blocks: `full_sample`, `benchmark`, `drawdowns`, `by_year`, `concentration`, `sensitivity`, `delay`,
  `inverted_signal`, `walk_forward_efficiency`, `trials`, and `macro_window` (stored macro series around
  the worst drawdown, or `available: false` and a `reason`).

**What it cannot tell you**

- An overall grade: there is none, by design. No flag is not proof of an edge.
- Volume against trade size, beta, regimes, or cherry-picking beyond the recorded variants. `--no-diagnose` runs return `NO_DIAGNOSTICS`.

**Next** Take the first `FLAG` to [the symptom index](README.md) and pick the cheapest test.

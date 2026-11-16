---
owner: validation statistics
sources:
  - packages/alpha-validation/src/**
  - packages/alpha-validation/pyproject.toml
verified: 47a64d4e846de21e
---

# alpha-validation workspace

## Purpose

Engine-agnostic statistics that decide whether a backtest is believable: walk-forward splits and
embargo, CPCV, bootstrap confidence intervals, Monte Carlo and permutation nulls, Deflated
Sharpe, PBO, reality checks, path risk, verdicts and the tear sheet, plus the investigation-tool
statistics (`attribution.py`, `regimes.py`, `changepoints.py`), which are thin wrappers over
statsmodels and ruptures. It imports only `alpha_core` plus numpy, scipy, statsmodels and ruptures
(import-linter contract "alpha_validation depends only on core"); only
`alpha_cli` composes it into the gauntlet. It is quant tier: every primitive needs an oracle.

## Read first

| Read | Section | When |
|---|---|---|
| [validation invariants](../../docs/reference/invariants/validation.md) | Splits and resampling | walk-forward, CPCV, purging, embargo or bootstrap |
| [validation invariants](../../docs/reference/invariants/validation.md) | — | a gate, null model, selection statistic, report or verdict |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Statistical evidence | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Quant tier | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing splits, embargo or out-of-sample stitching |
| [command line runs](../../docs/reference/invariants/cli-runs.md) | Validation and optimisation | changing how a gate is composed or reported |
| [investigation tools](../../docs/reference/invariants/cli-investigation-tools.md) | — | changing attribution, regimes or change points |
| [testing invariants](../../docs/reference/invariants/testing.md) | Quant sweeps | a mutation or semgrep check fails |
| [four-family Monte Carlo guide](../../docs/operations/monte-carlo/README.md) | Read the outputs | changing or explaining a path-risk family |
| [what this part is for](../../docs/reference/project/components/validation-and-evidence.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `packages/alpha-validation/src/alpha_validation/` (for example `walkforward.py`, `cpcv.py`,
  `bootstrap.py`, `dsr.py`, `mcpt.py`, `bar_permutation.py`, `verdict.py`, `tearsheet.py`). Gate
  composition is `apps/alpha-cli/src/alpha_cli/_gauntlet.py`; multi-trial statistics `_optim.py`.
- The investigation-tool modules are checked differentially against the library they wrap (same
  numbers as calling statsmodels or ruptures directly) in `tests/unit/test_attribution.py`,
  `test_regimes.py` and `test_changepoints.py`, including a test that a bar cannot change its own
  causal regime label.
- Tests: one `tests/unit/test_<module>.py` per module plus `tests/unit/test_gauntlet*.py`; oracles in
  `tests/oracles/` (shared tolerances in `tests/oracles/_reference/tolerances.py`); bias guards
  `tests/bias_guards/test_walkforward_no_leak.py`, `test_oos_stitch_no_leak.py`,
  `test_montecarlo_null_calibration.py`; integration `tests/integration/test_gauntlet_*.py`.
- Check: `uv run python scripts/gate.py check`, then `uv run pytest -q -m slow_oracle` for
  calibration oracles. CI adds the slow oracles and the mutation gate (kill rate at least 0.90) on
  every changed module here: `uv run python scripts/gate.py mutate <module path>` runs it locally.
- Never compare floats with `==`; take tolerances from the documented bounds.

## Outputs

- Tests: an oracle (metamorphic, calibration or differential) for every new public primitive, with a
  primary-source citation in its docstring; a bias guard for anything that splits time.
- The owning document: `docs/reference/invariants/validation.md`.

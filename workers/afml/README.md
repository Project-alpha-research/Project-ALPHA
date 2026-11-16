# Project ALPHA AFML worker

Methods from Marcos López de Prado's *Advances in Financial Machine Learning* (2018), run
through two independent open implementations side by side, in their own install. Outside
ALPHA's root uv workspace; no ALPHA package imports it.

## Pins

| Library | Pin | Role |
|---|---|---|
| RiskLabAI | `3.2.0` from PyPI (checksums in `uv.lock`) | Primary answer |
| quantowl | git commit `37a17de8f519e7c2dae3d609a3e078c4c83de22e` (tag `v0.1.6`; not on PyPI) | Independent second opinion |
| statsmodels | `0.14.6` | RiskLabAI needs `<0.15`, the reason this is a worker |
| numba | `0.68.1` (locked, brought by quantowl) | quantowl's compiled loops |
| numpy, pandas, polars, scipy | `2.4.6`, `2.3.3`, `1.41.2`, `1.17.1` | The same versions as ALPHA's root lock |

`[tool.uv] exclude-newer` keeps every locked release at least two weeks old (glue rule 4). The
mlfinlab 0.12.3 public archive is an answer key to read when the two disagree; it is never
installed (it calls pandas methods removed in pandas 2).

## What it offers today

| Function | Module | How it is checked |
|---|---|---|
| Average uniqueness of overlapping labels | `uniqueness.average_uniqueness` | Book's six-bar example by hand; libraries equal to 1e-10 |
| Time-decay weights (last weight in [0, 1]) | `uniqueness.time_decay` | Hand values; libraries equal to 1e-10 |
| Sequential bootstrap | `uniqueness.sequential_bootstrap` | Same draws from both for the same seed; hand probabilities 2/5, 5/11; book's Monte Carlo medians 0.6 and 0.7 |
| CUSUM events on log closes, threshold from prior volatility | `labels.find_events` | Hand path; fixed-threshold libraries identical |
| Triple-barrier labels and meta-labels | `labels.barrier_labels` | Hand path with known first touches; truncation test |
| Purged k-fold and combinatorial purged CV, backtest paths | `cv.purged_splits` | Brute-force leak checker; equal to ALPHA's `cpcv.py` on one-day labels; split and path counts |
| Fractional differencing, minimum d on training data | `fracdiff.ffd`, `fracdiff.fit_min_d` | Hand weights for d = 0.5; libraries equal to 1e-10; d unchanged by later bars |
| Feature importance: MDI, MDA, SFI (a report) | `importance.importance` | Book's synthetic test; quantowl on ALPHA-checked purged folds only |
| PSR, DSR, PBO, minimum track record, strategy risk | `stats` | Side by side with ALPHA's own values (root parity test) |

Labels come in two bases. `high_low` (default) is ALPHA's: decide at the event bar's close, enter
at the next open, touch on the bar's high or low, and a bar reaching both barriers is scored
stop-first with the optimistic reading kept beside it. `close` is the libraries' own, kept for
parity: entry at the close, touches on closes only; RiskLabAI (log returns) and quantowl (simple
returns) must agree except where a close sits between the two barrier conventions.

## Run

```bash
cd workers/afml && uv sync --locked
uv run alpha-afml-worker capabilities
uv run alpha-afml-worker labels BARS.parquet --out events.parquet
uv run alpha-afml-worker uniqueness events.parquet --bars BARS.parquet --out weights.parquet
```

Weights depend on every label used: pass `--train-end 2024-12-31T00:00:00+00:00` to weight only
the labels that ended by then (the weights then depend on no later bar); without it the whole file
is used and the summary's `weights_scope` says so. A label's span runs from its event bar to its
end bar, one bar more than the position is held, so overlap is counted slightly high.

`BARS.parquet` has `ts` (aware UTC), `open`, `high`, `low`, `close`, one row per bar, strictly
increasing. A summary is printed as JSON; any failure prints one line and exits 2. `alpha labels barrier|weights|importance`
call the worker; the other functions are worker commands (`alpha-afml-worker --help`).

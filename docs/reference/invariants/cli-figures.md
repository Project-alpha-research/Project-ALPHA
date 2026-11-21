---
owner: command line figures
sources:
  - apps/alpha-cli/src/alpha_cli/figure*.py
  - apps/alpha-cli/src/alpha_cli/figures/*.py
  - tests/unit/test_figure*.py
verified: 51fcf38f311a45fb
---

# Command line figures invariants
How `alpha figures` builds, caches and themes the figure pack. The drawing itself is in
[research invariants](research.md#figures-and-charts).

## Figures
- Figures are a derived cache under `data_dir/figures/<run_id>/`, never run artifacts. Writing into a run directory would break the manifest's exact file set.
- The cache key hashes renderer identity plus the run's declared artifact digests. Legacy runs fall back to size and mtime and are tagged so the two kinds of
  key cannot collide (`figure_cache.input_digest`).
- Write the image first and the JSON sidecar last; the sidecar marks completion. Forced re-renders must be byte-identical.
- `figure_cache.py` must not import Polars, numpy, matplotlib or the renderer. Enforced by `tests/unit/test_figure_cache.py`.
- `figures list --json` without `--run` publishes the key environment, so the web computes keys without the renderer.
- One theme rule for every run kind: light by default (`alpha-light`); `--dark` is the house dark theme (`alpha-dark`).
  The key environment carries both theme ids and digests (`theme_*`, `dark_theme_*`). The Workstation asks for dark.
  Setup Lab figures are stored once at run time and use the light theme.
- `figure_cache.BUILDER_REVISION` is part of every key. Bump it when a builder changes what a figure shows:
  `RENDERER_VERSION` lives in a protected package and moves only with the drawing code.
- `figures/how_to_read.py` holds a longer plain reading text per figure: axes, what to look for, what it cannot tell you.
  It is published as `how_to_read` in `figures list --json` and in each sidecar. The web API drops it until its model has the field.
- The return-distribution figure reads its mean and spread from the stored daily returns (the Q-Q points), never from histogram bin centres.
- Buy and hold reads "price only" for engine runs (the engine's benchmark never adds dividends).
  A rule test reads "with dividends" when the store holds dividends. The caption says so.
- Builders read declared artifacts only and report an honest unavailability reason instead of guessing.
- RD-Agent [journeys](../../../research/tools/rdagent-journey.md) publish only under the selected journey folder and exclude reserved-period observations.
- A run's price figure and chart candles read its snapshot at the run's own bar size: the manifest's `timeframe`, `source_timeframe` and `session` pass to
  `alpha data candles` as single `--option=value` arguments; a daily manifest has none, so its call is unchanged
  (`tests/unit/test_run_projection_security.py`).

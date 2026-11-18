---
owner: project layer
sources:
  - packages/alpha-forecast/CONTEXT.md
  - docs/adr/0008-vendored-kronos-and-alpha-forecast-layer.md
verified: 709c6924590c04f5
---

# Forecasting

Kronos is an open-source "foundation model" for price charts: given recent bars, it draws many
possible future price paths. ALPHA wraps it so its forecasts can be studied and tested like any
other experiment.

## Why it exists

Forecast paths are one more kind of evidence about a market: a possible signal, and a way to
study risk. The decision to bring Kronos in, with its model code kept at a fixed version, is
[ADR-0008](../../../adr/0008-vendored-kronos-and-alpha-forecast-layer.md).

## Its job in the research loop

Step 4 of the [research loop](../overview.md#the-research-loop): a forecast can feed a rule or a
risk study. Its paths are also one family of the path-risk simulation in
[validation and evidence](validation-and-evidence.md).

## Intended design

- The model code is kept in ALPHA at a pinned version (vendored), unlike RD-Agent, Qlib and
  Nautilus, which are installed packages; the reasons are in ADR-0008.
- The model downloads from the hub on first use unless offline loading is switched on (setting `forecast_local_only`,
  environment variable `ALPHA_FORECAST_LOCAL_ONLY`, default off). With it on, a missing file is an error, never a download
  ([ADR-0010](../../../adr/0010-local-kronos-weights-offline-policy.md)).
- Tests use `FakeForecaster` (`alpha_forecast/fake.py`), an offline stand-in; nothing in the tests downloads the model.
- Periods the model was trained on are labelled, so a forecast that has seen the future is never
  mistaken for a real one ([ADR-0009](../../../adr/0009-forecast-leakage-and-tier2-cost-policy.md)).

## What is real today

See the capability below on [STATUS.md](../../../../STATUS.md). The command is `alpha forecast run`; the
Workstation screen is Kronos Studio (View → Forecast, `apps/alpha-web/frontend/src/panels/KronosStudio.tsx`),
which reads stored forecast runs. Its paths also feed the Kronos family of [Monte Carlo](monte-carlo.md).

Leakage is labelled, not blocked. Each forecast run records which input bars fall on or before the assumed pretraining cutoff (default 2025-08-02, a
stand-in for the undisclosed real date) in a `pretrain` block with the overlap dates. `alpha forecast run` prints a warning on overlap, and `alpha
forecast eval` splits its skill scores before and after the cutoff. The Kronos Monte Carlo command records the same block and raises its warning flag.

## Where it lives

- **Workspaces:** `packages/alpha-forecast`
- **Capabilities:** `price-forecasts`
- Code: `packages/alpha-forecast/src/`; the `alpha forecast` commands in `apps/alpha-cli/`.
- How to change it: [packages/alpha-forecast/CONTEXT.md](../../../../packages/alpha-forecast/CONTEXT.md).
- Decision records: [ADR-0008](../../../adr/0008-vendored-kronos-and-alpha-forecast-layer.md),
  [ADR-0009](../../../adr/0009-forecast-leakage-and-tier2-cost-policy.md),
  [ADR-0010](../../../adr/0010-local-kronos-weights-offline-policy.md).
- Backlog: [re-check the vendored copy](../../../roadmap/backlog/kronos-vendored-copy-recheck.md)
  against the [glue rules](../../../adr/0051-glue-rules-for-outside-projects.md).
- **Plan:** Kronos rows in [stages 6 and 9](../../../roadmap/production-scope-2.md#6-diagnostics) of
  the checklist.

## Decisions and open questions

- Decided 2026-11-14: Kronos is a flexible research and exploration tool. It generates market paths
  for one Monte Carlo method and is open for forecast exploration; it is not tied to signals or risk
  yet, and its output needs validation before any decision relies on it
  ([log](../owner-decisions.md#2026-11-14-what-kronos-is-for)).
- Decided 2026-11-18: Kronos is part of the project and is to be built in as one of RD-Agent's tools,
  never removed when slimming ([log](../owner-decisions-5.md#2026-11-18-kronos-the-four-monte-carlos-lookalike-and-pattern-tools-are-rd-agents-toolbox)).
  Kronos Studio (the Workstation forecast screen) stays: a slimming audit had listed it for removal and the owner said to keep Kronos. Not built: no
  RD-Agent or [toolbox](toolbox.md) entry calls it yet.
- Open: no machine is recorded as holding the real model files, so the real model has run only on a stand-in.

## Never

- Never hide training-period overlap; leakage is labelled, never silent.
- Never import the model's heavy libraries outside this package.
- The rules: [forecast invariants](../../invariants/forecast.md).

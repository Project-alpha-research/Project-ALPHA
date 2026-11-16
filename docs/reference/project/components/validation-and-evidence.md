---
owner: project layer
sources:
  - packages/alpha-validation/CONTEXT.md
  - apps/alpha-cli/src/alpha_cli/spine/**
verified: 117a03295cbe541a
---

# Validation and evidence

The statistical checks (the "gauntlet") that decide whether a backtest result is believable, and
the reports that show the result: walk-forward tests, random "null" comparisons, bootstrap
ranges, the deflated Sharpe ratio, path-risk simulation and risk numbers.

## Why it exists

A profitable backtest is easy to find by chance. Before anything is trusted with real money the
owner needs to know whether the edge survives costs, data it was not tuned on, and the many ideas
that were tried ([owner decisions](../owner-decisions.md#2026-11-14-precision-and-live-capital)).
This is that test.

## Its job in the research loop

Step 6 of the [research loop](../overview.md#the-research-loop): it judges each experiment after
[Nautilus](nautilus.md) has run it. Its verdict is the feedback [RD-Agent](rd-agent.md) uses for
the next round, and the evidence the owner looks at in [research cases](research-cases-and-approval.md).

## Intended design

- The statistics know nothing about the engine; the [command line](command-line.md) joins them to
  backtest results.
- Every statistic has an independent correctness check (an oracle) and is held to a stricter code
  standard (the quant tier).
- Path risk (Monte Carlo) is measured separately from proof of an edge
  ([ADR-0029](../../../adr/0029-four-family-monte-carlo-validation.md)).

## What is real today

Every plain rule test also stores an automatic diagnostic pass and mechanical audit, unless it is
run with `--no-diagnose` and labelled `no-diagnostics`: benchmark comparisons, drawdowns,
concentration, sensitivity re-runs and explicitly counted variants. The owner can read these
through `alpha results` and `alpha diagnose`; flags identify observations to examine and grant no
research authority. [Stored facts](../../invariants/cli-runs.md#stored-facts-and-diagnostics)
retain the basis and source for each number, including a reason when it is unavailable.

Three follow-up [investigation tools](../../invariants/cli-runs.md#investigation-tools) answer
questions the flags raise, on one recorded rule test: `alpha tool attribution` (how much of the
return is market exposure, with Newey-West uncertainty), `alpha tool regimes` (calm versus
turbulent markets from a Markov-switching model) and `alpha tool changepoints` (dates where the
behaviour shifted). They are glue over statsmodels and ruptures, write no new statistics, and
label what they cannot avoid: `hindsight`, `parameters-fit-in-sample`, `benchmark-is-same-asset`.

See the capabilities below on [STATUS.md](../../../../STATUS.md).

## Where it lives

- **Workspaces:** `packages/alpha-validation`
- **Capabilities:** `validation-gauntlet`, `monte-carlo`, `risk-numbers`, `prop-firm-check`, `run-reports`, `result-diagnostics`, `investigation-tools`
- Code: `packages/alpha-validation/src/`; the gauntlet is assembled in
  `apps/alpha-cli/src/alpha_cli/_gauntlet.py`.
- Tests: `tests/smoke/test_validation_smoke.py`, `tests/oracles/`, and the validation tests under `tests/unit/`.
- How to change it: [packages/alpha-validation/CONTEXT.md](../../../../packages/alpha-validation/CONTEXT.md).
- Plans: the `plans` of each capability above in `docs/roadmap/capabilities.toml`.
- Decision records: [ADR-0006](../../../adr/0006-two-tier-null-model.md),
  [ADR-0029](../../../adr/0029-four-family-monte-carlo-validation.md).

## Decisions and open questions

- Triage card 5 (risk numbers): KEEP, 2026-11-14 under the owner's delegation ([triage sheet](../../../roadmap/triage-2026-11.md)).

## Never

- Never weaken a check, an oracle or a tolerance to make a change pass.
- Never present a passing check as proof of a profitable strategy.
- The rules: [validation invariants](../../invariants/validation.md) and
  [statistical evidence](../../invariants/research-integrity.md#statistical-evidence).

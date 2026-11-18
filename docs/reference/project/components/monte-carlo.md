---
owner: project layer
sources:
  - packages/alpha-validation/src/alpha_validation/path_montecarlo.py
  - apps/alpha-cli/src/alpha_cli/monte_carlo_cmds.py
  - apps/alpha-cli/src/alpha_cli/toolbox/registry.py
  - docs/operations/monte-carlo/README.md
verified: b2ae2ac146533051
---

# Monte Carlo

"How bad could it get?" ALPHA answers it with four Monte Carlo methods (families). Each makes many new
possible histories for one strategy and reports the spread of final return, worst drawdown, loss and ruin.
The owner counts the four as tools for RD-Agent and the assistant to use, never to be slimmed away.
Three resample the strategy's own recorded returns (`alpha monte-carlo classical --from-run <run>`). The fourth, Kronos, generates
new price bars and has run only with a stand-in model.

## Why it exists

A backtest shows one history. The same strategy could have been luckier or much worse. Path risk is measured
separately from proof of an edge: a favourable fan of paths never shows that an edge exists
([ADR-0029](../../../adr/0029-four-family-monte-carlo-validation.md)). The reason for four, from that ADR: each
changes a different assumption, so one vote would hide failure modes. The owner's own reason for wanting all four
is not recorded beyond the 2026-11-14 note on Kronos and the 2026-11-18 order to keep them as tools.

## Its job in the research loop

Step 6, judging: it follows the randomized-price tests of a rule test and reports scenario risk for the owner's
decision. It is meant to become a set of [toolbox](toolbox.md) entries RD-Agent can choose from; the
randomized-price null (does the rule beat markets with no pattern?) is a different question and stays separate.

## Intended design

| Family | Question it answers | Where it lives |
|---|---|---|
| IID empirical | What if the observed out-of-sample returns recurred in other sequences? | `empirical_return_paths` |
| Causal-volatility Markov | How does persistence of calm and turbulent spells change the risk? | `regime_switching_return_paths` |
| Student-t log returns | How sensitive are results to fatter tails than the short sample shows? | `student_t_return_paths` |
| Kronos market paths | How does the unchanged strategy trade on model-generated markets? | `alpha monte-carlo kronos` |

The first three resample the validation run's own account returns (all in
`packages/alpha-validation/src/alpha_validation/path_montecarlo.py`; the guides are in
[docs/operations/monte-carlo/](../../../operations/monte-carlo/README.md)). Kronos generates price bars and
replays the strategy on each (`apps/alpha-cli/src/alpha_cli/monte_carlo_cmds.py`; see [forecasting](forecasting.md)).
Each family gets its own grade and is never majority-voted; a warning pauses until the owner records a decision.

## What is real today

`alpha monte-carlo classical --from-run <run>` publishes the three classical families together and was checked
against an independent recomputation on 2026-11-14. `alpha monte-carlo kronos` has run only with a stand-in
model; the real Kronos model files are not on the development machine. The Workstation groups the path figures under
`monte_carlo` (ADR-0029); Kronos Studio shows forecast runs. See the capability on [STATUS.md](../../../../STATUS.md) and the
[path-risk card](../../../../research/tools/path-risk.md).
The toolbox registers `resampling.drawdown_distribution` for the IID empirical family on stored rule-test returns.
The [resampling card](../../../../research/tools/resampling-checks.md) explains how to compare its drawdowns with the classical command.

## Where it lives

- **Workspaces:** none (code is in `packages/alpha-validation` and `apps/alpha-cli`, owned by
  [validation and evidence](validation-and-evidence.md) and [command line](command-line.md)).
- **Capabilities:** `monte-carlo`
- Code: as the table above.
- Tests: `tests/unit/test_path_montecarlo.py`, `tests/unit/test_monte_carlo_cmds.py`,
  `tests/integration/test_monte_carlo_cli.py`, `tests/bias_guards/test_monte_carlo_causality.py`,
  `tests/smoke/test_monte_carlo_smoke.py`.
- How to change it: [packages/alpha-validation/CONTEXT.md](../../../../packages/alpha-validation/CONTEXT.md).
- **Plan:** [stage 6](../../../roadmap/production-scope-2.md#6-diagnostics) of the checklist.
- Decision record: [ADR-0029](../../../adr/0029-four-family-monte-carlo-validation.md).

## Decisions and open questions

- Decided 2026-11-14: Kronos powers one Monte Carlo method; its output needs validation
  ([log](../owner-decisions.md#2026-11-14-what-kronos-is-for)).
- Decided 2026-11-18: the four methods are RD-Agent's tools, never slimming targets
  ([log](../owner-decisions-5.md#2026-11-18-kronos-the-four-monte-carlos-lookalike-and-pattern-tools-are-rd-agents-toolbox)).
- Open: moving the remaining families into the toolbox; a real-model Kronos run on the Mac.

## Never

- Never present path risk as proof of an edge, or majority-vote the families.
- Never remove or slim a family. The owner called all four "never slimming targets" (2026-11-18); one that nothing reaches yet is owed wiring, not deletion.
- The rules: [validation invariants](../../invariants/validation.md).

---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
---

# Sensitivity: costs, delay and nearby settings

**Reach for it when** a result may depend on cheap trading, on catching the exact bar, or on one lucky
setting. Every rule test already made the cheap re-runs.

**Commands**
```text
alpha diagnose <run_id> --json
alpha results cite <run_id> delayed_sharpe
alpha test --rule ma_cross --param fast=50 --param slow=200 --asset SPY --fee-bps 5 --slippage-bps 10 --json
```

**How to read it**

- `sensitivity.variants` holds full re-runs: `costs_x2` (fee and slippage doubled) and each rule number moved
  down and up by a fifth (`kind` is `costs` or `parameter`), each with its own Sharpe, return and drawdown.
  An owner rule moves each window and constant one at a time, at most 8 variants, with no best pick.
- `delay` compares `base_sharpe` with `delayed_sharpe` (every position taken one bar later). It is a
  returns-level approximation, not a full re-run: compare the two with each other, not with `oos_sharpe`.
- Flags: `fragile-to-costs` and `fragile-to-parameters` fire when a variant's Sharpe is at or below zero, or under
  half a positive base. `fragile-to-delay` fires when the delayed Sharpe is under half a positive base.
- For other cost levels, run the rule test again with `--fee-bps` and `--slippage-bps`. Each is a counted
  trial; say you changed the costs and why.

**What it cannot tell you**

- For the scored break-even cost, use the [run-level check](run-level-checks.md). Costs here are flat and do not model trade capacity.
- A reserved-period confirmation runs only the frozen rule and `costs_x2` (`sensitivity.note`). Wider ranges: the re-runs
  are one step each side only. A sweep is [deflated Sharpe and trials](deflated-sharpe-and-trials.md); report it as a search.

**Next** Fragile to costs: state the holding period and trade count beside it. Fragile to delay: treat the
result as depending on the exact bar and check `fills-after-decisions` in the audit.

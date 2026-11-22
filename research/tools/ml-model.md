---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/ml_run.py
  - apps/alpha-cli/src/alpha_cli/ml_cmds.py
---

# ML model (Qlib)

**Reach for it when** the owner asks "can a model find it": one plain spec to a trained gradient-boosting model, replayed with costs.
**Command**
```text
alpha ml run research/examples/ml-gbm-etfs.toml --json
```
A spec file holds `assets` (at least 20 symbols with stored daily bars), and optional `name`, `features` (`alpha158`),
`horizon_days` (`1`), `model` (`lightgbm`) and a `[split]` table (`train_days`, `validation_days`, `test_days`).
No project or experiment is needed. Set up the worker once: `bash scripts/setup.sh`.
**How to read it**
- `split_sentence` names the training days and the test days. The model never saw the test days.
- The run is stored like any other: read it with `alpha report <run_id>` or `alpha results show <run_id>`.
  It has no diagnostics file, so `alpha diagnose` does not work on it.
- Costs are fixed (1 bp fee, 2 bp slippage per trade) and shown in `costs`. Bars from 2024-01-01 on are held back (`reserve_sentence`).
- `tries_sentence`: each new run counts 1 try in family `qlib`. The same spec on the same data counts once.
**What it cannot tell you**
- Whether the model is real. The null checks do not retrain the model, so the run reads "not recomputed under counterfactual".
- Today's limits: daily bars, long only, label horizon of 1 day, the current universe (survivorship bias possible).
**Next** `alpha diagnose <run_id> --json`, then [diagnose and audit](diagnose-and-audit.md).

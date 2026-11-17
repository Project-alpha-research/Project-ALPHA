---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/tools.py
  - apps/alpha-cli/src/alpha_cli/spine/tool_inputs.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
  - apps/alpha-cli/src/alpha_cli/spine/ledger.py
  - packages/alpha-validation/src/alpha_validation/attribution.py
  - packages/alpha-validation/src/alpha_validation/regimes.py
  - packages/alpha-validation/src/alpha_validation/changepoints.py
  - tests/smoke/test_rule_tools_smoke.py
verified: a240d4f9fb93882c
---

# Investigation tools invariants

Follow-up questions on one recorded rule test; part of [command line runs](cli-runs.md).

## Rules

- `alpha tool attribution|regimes|changepoints <run_id> --json` describe one recorded rule test.
  They rebuild its full-sample equity through the diagnostic pass's own path
  (`spine/diagnose.py:full_sample`), fail loud with `RUN_DATA_CHANGED` when the stored bars no
  longer reproduce it, and never re-run a walk-forward. Statistics are thin glue over statsmodels
  and ruptures in `alpha_validation` (`attribution.py`, `regimes.py`, `changepoints.py`).
- The engine samples equity at each bar's open, so market and benchmark returns are open-to-open
  on shared timestamps; the output reports the bars each side lost to the join. A comparison of
  two assets with different session clocks says that a shared date is not a shared instant.
- Regimes are fitted on the market's returns. The headline split labels each bar with the
  filtered regime of the bar before it (causal); the smoothed split is a separate `hindsight`
  section. Model parameters use the whole sample: label `parameters-fit-in-sample`. Change points
  are labelled `hindsight`; same-asset comparisons `benchmark-is-same-asset`.
- Manifests are immutable, so each output is written atomically outside the run directory, at
  `<home>/diagnostics/<run_id>/<tool>-<sha8 of params>.json`, with facts in the shape of
  `spine/facts.py` (metrics in `TOOL_METRICS`). Each run of a tool appends one ledger row with
  `kind = "tool:<name>"` and a null verdict; rows without `kind` read as `rule_test`.
- `alpha results show` lists a run's tool outputs; `alpha results cite <run_id> <metric>` quotes
  a tool fact, and needs `--tool-output <id>` when the tool ran with different settings
  (`AMBIGUOUS_TOOL_OUTPUT` lists the known ids). Errors: `UNKNOWN_RUN`, `NOT_A_RULE_TEST`,
  `UNKNOWN_ASSET`, `TOO_FEW_BARS`, `MODEL_DID_NOT_CONVERGE`, `NO_TOOL_OUTPUT`.

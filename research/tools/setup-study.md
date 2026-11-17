---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/setup_study.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_controls.py
  - apps/alpha-cli/src/alpha_cli/spine/event_study_figure.py
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
verified: 17cb3c8fc831b236
---

# Setup study

**Reach for it when** a recorded setup find has the intended matches and the owner wants to
measure what followed each separate occurrence against ordinary dates.

**Commands**

```text
uv run alpha setup study <find_id> --json
uv run alpha results cite <study_id> setup_mean_net_return --json
```

**How to read it**

- Include `[study]` horizons and primary in the spec before finding. Only the pooled primary
  horizon is tested; others say "also looked at, not tested" and carry `not-primary`.
- Lead with complete separate occurrences beside matching days. Entry is the recorded next open;
  each horizon ends at its bar close, with default fees and slippage charged on both sides.
- Compare mean net return with drift and 2,000 spaced random-date samples. The figure's top panel
  shows every occurrence; the lower one zooms in on the mean, the grey band and dashed drift.
- Fewer than 30 complete occurrences, overlapping outcomes and disagreeing halves are labels,
  not evidence to omit. Each half is compared with controls from its own years.
- Each study counts one trial; repeating it labels `repeat` without rewriting the folder.

**What it cannot tell you** Exits, sizing, portfolios, dividends or reserved-data confirmation.
Setups cluster in market states (a double bottom follows a decline): beating random dates says
the dates were unusual, not that the setup can be traded.

**Next** Cite stored facts and their limitations; inspect stability before proposing another test.

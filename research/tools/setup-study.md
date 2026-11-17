---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/setup_costs.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_trade_figure.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_study.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_controls.py
  - apps/alpha-cli/src/alpha_cli/spine/event_study_figure.py
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
verified: a1f5e4ad2ed04051
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
  each horizon ends at its bar close, with [per-asset costs](setup-trade.md) on both sides.
  Rule version 2 uses these costs; old studies read with `older-cost-rule`, and re-studying their
  find is labelled `remeasured-new-cost-rule` and counts as one more look (say so to the owner).
- Compare mean net return with drift and 2,000 spaced random-date samples (figure: grey band, dashed drift).
- Under 30 complete occurrences, overlapping outcomes and disagreeing halves are labels, not
  evidence to omit; each half meets controls from its own years.
- Each study counts one trial; repeating it labels `repeat` without rewriting the folder.

**What it cannot tell you** Exits, sizing, portfolios, dividends or reserved-data confirmation.
Setups cluster in market states (a double bottom follows a decline): beating random dates says
the dates were unusual, not that the setup can be traded.

**Next** Cite stored facts and limitations; use [setup trade](setup-trade.md) to test declared exits.
